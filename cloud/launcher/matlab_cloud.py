"""All-project MATLAB cloud workflow. Invoked by matlab-cloud.cmd; stdlib only.

Startup creates missing project buckets, uploads source, and collects completed
outputs. The interactive console monitors jobs and accepts explicit run/stop
commands. Source synchronization mirrors eligible local files under project/,
including deletions; output data and immutable run snapshots are preserved.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from concurrent.futures import ThreadPoolExecutor, as_completed


TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED"}
ACTIVE = {"QUEUED", "SCHEDULED", "RUNNING"}
RESERVED = re.compile(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
SOURCE_EXCLUDE = (
    r"(?i)(^|[\\/])(\.git|\.codex|\.agents|\.omni|outputs|results|downloads|credentials)([\\/]|$)"
    r"|(^|[\\/])\.env($|\.)|(^|[\\/])matlab-cloud\.json$"
    r"|(^|[\\/])cloud[\\/](diagnostics|launcher)([\\/]|$)"
    r"|(^|[\\/])(credentials[^\\/]*|service[-_]account[^\\/]*|[^\\/]*private[-_]key[^\\/]*)(\.json|\.pem|\.key)$"
)
EXCLUDED = re.compile(SOURCE_EXCLUDE)
AUTH_READ_COMMANDS = (
    ("auth", "list"), ("projects", "describe"),
    ("artifacts", "docker", "images", "describe"),
    ("storage", "buckets", "describe"), ("storage", "objects", "list"),
    ("storage", "objects", "describe"), ("batch", "jobs", "list"),
    ("storage", "cat"),
    ("batch", "jobs", "describe"), ("logging", "read"),
)


def authentication_failure(text):
    text = text.casefold()
    return any(message in text for message in (
        "reauthentication failed", "problem refreshing your current auth tokens",
        "do not currently have an active account", "no active account selected",
        "invalid_grant", "request had invalid authentication credentials",
    ))


class CloudError(RuntimeError):
    pass


class CommandError(CloudError):
    def __init__(self, args, returncode, stdout, stderr):
        self.args_list = args
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        detail = (stderr or stdout).strip()
        super().__init__(f"Google Cloud command failed ({returncode}): {detail}")


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise CloudError(f"Cannot read JSON configuration {path}: {exc}") from exc


def inside(path, parent):
    try:
        Path(path).resolve().relative_to(Path(parent).resolve())
        return True
    except ValueError:
        return False


def is_link(path):
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def safe_parts(name):
    """Reject cloud object names that cannot safely round-trip to Windows."""
    if not isinstance(name, str) or not name or "\\" in name:
        raise CloudError(f"Unsafe relative cloud filename: {name!r}")
    parts = name.split("/")
    for part in parts:
        if (not part or part in {".", ".."} or part[-1:] in {".", " "}
                or RESERVED.match(part) or re.search(r'[<>:"|?*\[\]#\x00-\x1f]', part)):
            raise CloudError(f"Cloud filename cannot safely map to Windows: {name!r}")
    return parts


def safe_destination(root, name):
    destination = Path(root).joinpath(*safe_parts(name))
    if not inside(destination, root):
        raise CloudError(f"Output path escapes its download directory: {name}")
    current = Path(root)
    for part in safe_parts(name):
        if is_link(current):
            raise CloudError(f"Download directory contains a link/junction: {current}")
        current = current / part
    if is_link(current):
        raise CloudError(f"Download destination is a link/junction: {current}")
    return destination


def hash_file(path, algorithm="sha256"):
    before = path.stat()
    hasher = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            hasher.update(chunk)
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise CloudError(f"File changed while being verified: {path}")
    return hasher.digest()


@dataclass
class Project:
    directory: Path
    name: str
    key: str
    bucket: str
    config: dict

    @property
    def source_uri(self):
        return f"gs://{self.bucket}/project"

    @property
    def outputs_uri(self):
        return f"gs://{self.bucket}/outputs"


class Context:
    def __init__(self, gcloud, root, settings, dry_run=False, allow_auth_login=False):
        self.root = Path(root).resolve()
        self.settings = settings
        self.dry_run = dry_run
        self.allow_auth_login = allow_auth_login and not dry_run
        self.auth_account = ""
        self.auth_needed = threading.Event()
        self.project = str(settings["project"])
        self.region = str(settings["region"])
        self.env_image = str(settings["environment_image"])
        self.env_digest = ""
        self.project_number = ""
        self.run_dir = self.root / "state" / ("workflow-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8])
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.log_path = self.run_dir / "workflow.log"
        self._sequence = 0
        self._log_lock = threading.RLock()
        self._prompt_active = False
        self._deferred_messages = []
        executable = Path(gcloud)
        # Avoid cmd.exe expansion of JSON strings, folder names or regular expressions.
        if executable.suffix.lower() in {".cmd", ".bat"}:
            script = executable.parent.parent / "lib" / "gcloud.py"
            if not script.is_file():
                raise CloudError(f"Cannot locate SDK Python entry point: {script}")
            self.gcloud_command = [sys.executable, str(script)]
        elif executable.suffix.lower() == ".py":
            self.gcloud_command = [sys.executable, str(executable)]
        else:
            self.gcloud_command = [str(executable)]

    def log(self, message):
        message = str(message)
        with self._log_lock:
            if self._prompt_active:
                self._deferred_messages.append(message)
            else:
                print(message, flush=True)
            with self.log_path.open("a", encoding="utf-8") as stream:
                stream.write(datetime.now(timezone.utc).isoformat() + " " + message + "\n")

    def prompt(self, message):
        # Background work continues while the prompt is idle. Defer its console
        # messages until Enter so they never interrupt a half-typed command.
        with self._log_lock:
            self._prompt_active = True
        try:
            return input(message)
        finally:
            with self._log_lock:
                self._prompt_active = False
                for text in self._deferred_messages:
                    print(text, flush=True)
                self._deferred_messages.clear()

    def authenticate(self):
        if (not self.allow_auth_login or threading.current_thread() is not threading.main_thread()
                or not sys.stdin.isatty()):
            raise CloudError("Google Cloud sign-in is required. Run gcloud auth login in a CMD window, or start matlab-cloud without --once/--dry-run to open browser sign-in automatically.")
        self.log("Google Cloud sign-in is required. Opening browser login; complete it to continue.")
        environment = os.environ.copy()
        environment["CLOUDSDK_CORE_DISABLE_PROMPTS"] = "0"
        environment["PYTHONIOENCODING"] = "utf-8"
        args = self.gcloud_command + ["auth", "login"]
        if self.auth_account:
            args.append(self.auth_account)
        args.extend(["--force", "--brief"])
        # Inherit console input/output. Never capture or save sign-in URLs/codes.
        result = subprocess.run(args, env=environment, shell=False)
        if result.returncode:
            raise CloudError("Google Cloud sign-in was cancelled or failed. Restart matlab-cloud to try again; startup synchronization has not resumed.")
        self.auth_needed.clear()
        self.log("Google Cloud sign-in completed. Resuming verification.")

    def gcloud(self, *args, json_output=False, _retry_auth=True, _raw_output=False):
        original_args = args
        args = [str(arg) for arg in args]
        if not any(arg.startswith("--project") for arg in args):
            args.append("--project=" + self.project)
        if json_output and not any(arg.startswith("--format") for arg in args):
            args.append("--format=json")
        args.extend(["--quiet"])
        environment = os.environ.copy()
        environment.update({"CLOUDSDK_CORE_DISABLE_PROMPTS": "1", "CLOUDSDK_STORAGE_PROCESS_COUNT": "1", "CLOUDSDK_STORAGE_THREAD_COUNT": "4", "PYTHONIOENCODING": "utf-8"})
        with self._log_lock:
            self._sequence += 1
            record = self.run_dir / f"command-{self._sequence:04d}"
        result = subprocess.run(self.gcloud_command + args, text=True, encoding="utf-8", errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment, shell=False)
        record.with_suffix(".stdout.txt").write_text(result.stdout, encoding="utf-8")
        record.with_suffix(".stderr.txt").write_text(result.stderr, encoding="utf-8")
        if result.returncode:
            if authentication_failure(result.stderr + "\n" + result.stdout):
                self.auth_needed.set()
                readonly = any(tuple(args[:len(prefix)]) == prefix for prefix in AUTH_READ_COMMANDS)
                if (_retry_auth and readonly and self.allow_auth_login
                        and threading.current_thread() is threading.main_thread() and sys.stdin.isatty()):
                    self.authenticate()
                    return self.gcloud(*original_args, json_output=json_output, _retry_auth=False, _raw_output=_raw_output)
                if self.allow_auth_login and threading.current_thread() is not threading.main_thread():
                    self.log("Google Cloud sign-in needs renewing. Press Enter at the prompt to sign in and continue.")
            raise CommandError(args, result.returncode, result.stdout, result.stderr)
        if json_output:
            try:
                return json.loads(result.stdout or "null")
            except ValueError as exc:
                raise CloudError(f"Google Cloud returned invalid JSON; inspect {record}") from exc
        if result.stdout.strip() and not _raw_output:
            self.log(result.stdout.strip())
        if result.stderr.strip():
            self.log(result.stderr.strip())
        return result.stdout

    def verify_environment(self):
        accounts = self.gcloud("auth", "list", "--filter=status=ACTIVE", json_output=True)
        if not isinstance(accounts, list) or not accounts:
            self.authenticate()
            accounts = self.gcloud("auth", "list", "--filter=status=ACTIVE", json_output=True, _retry_auth=False)
            if not isinstance(accounts, list) or not accounts:
                raise CloudError("Google Cloud sign-in did not select an active account. Restart matlab-cloud to sign in again.")
        self.auth_account = str(accounts[0].get("account", ""))
        project = self.gcloud("projects", "describe", self.project, json_output=True)
        self.project_number = str(project.get("projectNumber", ""))
        if not self.project_number.isdigit():
            raise CloudError("Cloud project verification did not return a project number.")
        image = self.gcloud("artifacts", "docker", "images", "describe", self.env_image, json_output=True)
        self.env_digest = image.get("image_summary", {}).get("digest", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", self.env_digest):
            raise CloudError("The reusable MATLAB image was not verified by digest.")
        write_json(self.run_dir / "environment.json", image)
        self.log(f"Verified cloud project {self.project} and reusable MATLAB environment {self.env_digest}.")


def default_config(name, project_id):
    slug = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()).strip("-") or "project"
    if not slug[0].isalpha():
        slug = "project-" + slug
    suffix = hashlib.sha256(name.encode("utf-8")).hexdigest()[:8]
    key = (slug[:45].rstrip("-") + "-" + suffix)[:63]
    bucket = (project_id + "-matlab-" + key)[:54].rstrip("-") + "-" + suffix
    return {"project_key": key, "bucket": bucket, "entry_points": [], "machine_type": "e2-standard-8", "cpu_milli": 8000, "memory_mib": 30000, "boot_disk_gb": 100, "max_run_seconds": 259200}


def discover_projects(ctx):
    workspace = Path(os.path.expandvars(str(ctx.settings["workspace_root"]))).expanduser().resolve()
    if not workspace.is_dir():
        raise CloudError(f"Desktop MATLAB workspace was not found: {workspace}")
    ignored = {str(item).casefold() for item in ctx.settings.get("exclude_directories", [])}
    discovered = []
    pending = []
    seen_keys, seen_buckets, seen_names = set(), set(), set()
    for directory in sorted(workspace.iterdir(), key=lambda item: item.name.casefold()):
        if not directory.is_dir() or directory.name.startswith(".") or directory.name.casefold() in ignored:
            continue
        if is_link(directory):
            ctx.log(f"Skipping workspace link/junction {directory.name}; put real project directories directly in the workspace.")
            continue
        safe_parts(directory.name)
        filename = directory / "matlab-cloud.json"
        template = ctx.root / "project-configs" / directory.name / "matlab-cloud.json"
        if filename.exists():
            config = read_json(filename)
        elif template.exists():
            config = read_json(template)
            pending.append((filename, config))
        else:
            config = default_config(directory.name, ctx.project)
            pending.append((filename, config))
        if not isinstance(config, dict):
            raise CloudError(f"Project configuration must be a JSON object: {filename}")
        if config.get("enabled", True) is False:
            ctx.log(f"Skipping disabled project {directory.name}.")
            continue
        key, bucket = config.get("project_key", ""), config.get("bucket", "")
        if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", key):
            raise CloudError(f"Invalid project_key for {directory.name}; use a lowercase label up to 63 characters.")
        if not isinstance(bucket, str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", bucket):
            raise CloudError(f"Invalid bucket name for {directory.name}: {bucket!r}")
        if key in seen_keys or bucket in seen_buckets or directory.name.casefold() in seen_names:
            raise CloudError(f"Duplicate desktop name, project_key, or bucket in workspace: {directory.name}. No project synchronization started.")
        seen_keys.add(key)
        seen_buckets.add(bucket)
        seen_names.add(directory.name.casefold())
        discovered.append(Project(directory, directory.name, key, bucket, config))
    if not discovered:
        raise CloudError(f"No enabled project directories were found immediately under {workspace}.")
    # Validate the complete map before creating any local configuration.
    for filename, config in pending:
        if config.get("enabled", True) is False:
            continue
        if ctx.dry_run:
            ctx.log(f"[Preview] Would create {filename}.")
        else:
            # Exclusive creation protects a configuration written concurrently by the user.
            try:
                with filename.open("x", encoding="utf-8") as stream:
                    json.dump(config, stream, indent=2, ensure_ascii=False)
                    stream.write("\n")
            except FileExistsError as exc:
                raise CloudError(f"Configuration appeared during discovery; rerun to load it: {filename}") from exc
            ctx.log(f"Created project settings: {filename}")
    write_json(ctx.run_dir / "project-map.json", [{"desktop_name": item.name, "directory": str(item.directory), "project_key": item.key, "bucket": item.bucket} for item in discovered])
    return discovered


def resolve_project(projects, supplied):
    value = str(supplied).strip().strip('"')
    # A bare desktop folder name is deliberately not interpreted as a cloud key.
    bare = next((project for project in projects if project.name.casefold() == value.casefold()), None)
    if bare is not None:
        return bare
    path = Path(os.path.expandvars(value)).expanduser()
    candidates = [path]
    if not path.is_absolute() and projects:
        candidates.append(projects[0].directory.parent / path)
    for candidate in candidates:
        resolved = candidate.resolve()
        match = next((project for project in projects if project.directory.resolve() == resolved), None)
        if match is not None:
            return match
    raise CloudError(f"Unknown desktop project directory {supplied!r}. Available: " + ", ".join(project.name for project in projects))


def configure_entry(ctx, project, supplied=None):
    from matlab_cloud_run import _entry_points
    if supplied is None:
        _entry_points(project)
        return project
    raw = str(supplied).strip().strip('"')
    if raw.startswith('[') or raw.endswith(']'):
        corrected = raw.removeprefix('[').removesuffix(']').strip('"')
        raise CloudError(f'Do not type square brackets around the script path. Enter: run "{project.name}" "{corrected}"')
    entry_path = Path(raw)
    if entry_path.is_absolute():
        if not inside(entry_path, project.directory):
            raise CloudError("The entry script must be inside the selected desktop project directory.")
        raw = entry_path.resolve().relative_to(project.directory.resolve()).as_posix()
    else:
        raw = raw.replace("\\", "/")
        if raw.startswith(project.name + "/"):
            raw = raw[len(project.name) + 1:]
    updated = dict(project.config)
    updated["entry_points"] = [raw]
    candidate = Project(project.directory, project.name, project.key, project.bucket, updated)
    _entry_points(candidate)
    if EXCLUDED.search(raw):
        raise CloudError("The selected entry script is excluded from source upload; choose a script in the project source tree.")
    old = project.config.get("entry_points", [])
    if old and old != [raw]:
        if ctx.dry_run:
            ctx.log(f"[Preview] Would ask to replace entry_points {old!r} with {[raw]!r} in {project.name}/matlab-cloud.json.")
        elif ctx.prompt(f"{project.name}: replace entry point {old!r} with {raw!r}? [y/N] ").strip().lower() not in {"y", "yes"}:
            raise CloudError("Entry point change declined; no cloud run submitted.")
    if not ctx.dry_run and old != [raw]:
        write_json(project.directory / "matlab-cloud.json", updated)
        ctx.log(f"Saved entry script {raw} in {project.name}/matlab-cloud.json.")
    project.config = updated
    return project


def source_files(project):
    root = project.directory.resolve()
    files = []
    for folder, directories, filenames in os.walk(root, followlinks=False):
        folder = Path(folder)
        allowed_directories = []
        for name in directories:
            if EXCLUDED.search((folder / name).relative_to(root).as_posix() + "/"):
                continue
            if is_link(folder / name):
                raise CloudError(f"Source directory is a link/junction; move the real files into the project or exclude it: {folder / name}")
            allowed_directories.append(name)
        directories[:] = allowed_directories
        for name in filenames:
            path = folder / name
            relative = path.relative_to(root).as_posix()
            if EXCLUDED.search(relative):
                continue
            if is_link(path):
                raise CloudError(f"Source file is a symbolic link; move the real file into the project: {path}")
            safe_parts(relative)
            if not path.is_file() or not inside(path, root):
                raise CloudError(f"Source path cannot be safely uploaded: {path}")
            files.append(path)
    return sorted(files)


def list_objects(ctx, uri):
    try:
        records = ctx.gcloud("storage", "objects", "list", uri.rstrip("/") + "/**", json_output=True)
    except CommandError as exc:
        # An empty wildcard is the only nonzero result treated as an empty prefix.
        # Permission, authentication, network and bucket errors must remain failures.
        message = (exc.stdout + "\n" + exc.stderr).lower()
        if ("matched no objects" in message or "one or more urls matched no objects" in message or "no urls matched" in message) and not any(word in message for word in ("403", "401", "permission", "denied", "timeout", "not found", "404")):
            return []
        raise
    if records is None:
        return []
    if not isinstance(records, list):
        raise CloudError(f"Unexpected object inventory for {uri}")
    return records


def normalize_bucket(ctx, project, owned_buckets):
    if project.bucket not in owned_buckets:
        if ctx.dry_run:
            ctx.log(f"[Preview] Would create private bucket gs://{project.bucket} in {ctx.region}. A globally occupied name will fail safely.")
            return False
        ctx.gcloud("storage", "buckets", "create", "gs://" + project.bucket, "--location=" + ctx.region, "--uniform-bucket-level-access", "--public-access-prevention")
        # Project-scoped membership is the ownership proof, including post-create.
        refreshed = ctx.gcloud("storage", "buckets", "list", json_output=True)
        owned_buckets.update(record["name"] for record in refreshed)
        if project.bucket not in owned_buckets:
            raise CloudError(f"Created bucket was not found in the expected project: {project.bucket}")
    details = ctx.gcloud("storage", "buckets", "describe", "gs://" + project.bucket, json_output=True)
    write_json(ctx.run_dir / (project.key + "-bucket.json"), details)
    ctx.log(f"{project.name}: verified bucket gs://{project.bucket} belongs to this project.")
    return True


def _find_hash(value, names):
    if isinstance(value, dict):
        for name in names:
            if value.get(name):
                return value[name]
        for nested in value.values():
            found = _find_hash(nested, names)
            if found:
                return found
    elif isinstance(value, list):
        for nested in value:
            found = _find_hash(nested, names)
            if found:
                return found
    return None


def verify_file(ctx, path, record):
    if not path.is_file() or path.stat().st_size != int(record.get("size", -1)):
        raise CloudError(f"Missing file or size mismatch: {path}")
    expected = record.get("md5_hash") or record.get("md5Hash")
    if expected:
        actual = base64.b64encode(hash_file(path, "md5")).decode("ascii")
    else:
        expected = record.get("crc32c_hash") or record.get("crc32c")
        if not expected:
            raise CloudError(f"Cloud object has no usable checksum: {record.get('name')}")
        result = ctx.gcloud("storage", "hash", str(path), "--skip-md5", json_output=True)
        actual = _find_hash(result, ("crc32c_hash", "crc32c"))
    if actual != expected:
        raise CloudError(f"Checksum mismatch: {path}")


def verify_source(ctx, project, source_directory=None, source_uri=None, require_mirror=False):
    directory = Path(source_directory) if source_directory is not None else project.directory
    uri = source_uri or project.source_uri
    relative_prefix = uri.split("/", 3)[3].rstrip("/") + "/"
    shadow = Project(directory, project.name, project.key, project.bucket, project.config)
    local = source_files(shadow)
    cloud = {record.get("name"): record for record in list_objects(ctx, uri)}
    for path in local:
        name = relative_prefix + path.relative_to(directory).as_posix()
        if name not in cloud:
            raise CloudError(f"Uploaded source was not found online: {name}")
        verify_file(ctx, path, cloud[name])
    if require_mirror:
        expected_names = {relative_prefix + path.relative_to(directory).as_posix() for path in local}
        extras = {name for name in cloud if isinstance(name, str) and name.startswith(relative_prefix)
                  and not name.endswith('/') and not EXCLUDED.search(name[len(relative_prefix):])
                  and name not in expected_names}
        if extras:
            raise CloudError("Source mirror still contains files absent locally: " + ", ".join(sorted(extras)[:10]))
    ctx.log(f"{project.name}: verified {len(local)} uploaded source files by size and checksum.")
    return len(local)


def synchronize_source(ctx, project, bucket_exists):
    if not project.directory.is_dir() or is_link(project.directory):
        raise CloudError(f"Cannot mirror missing or linked source directory: {project.directory}")
    files = source_files(project)
    total = sum(path.stat().st_size for path in files)
    ctx.log(f"{project.name}: {'previewing' if ctx.dry_run else 'uploading'} {len(files)} source files ({total:,} bytes) to {project.source_uri}/.")
    ctx.log(f"{project.name}: source mirroring removes unmatched files only under {project.source_uri}/; saved outputs and run snapshots are preserved.")
    args = ["storage", "rsync", str(project.directory), project.source_uri, "--recursive", "--checksums-only", "--ignore-symlinks", "--exclude=" + SOURCE_EXCLUDE, "--delete-unmatched-destination-objects"]
    if ctx.dry_run:
        if bucket_exists:
            ctx.gcloud(*args, "--dry-run")
        else:
            ctx.log("[Preview] Upload would run after bucket creation.")
        return
    ctx.gcloud(*args)
    verify_source(ctx, project, require_mirror=True)


def inventory(records, prefix):
    selected = []
    seen = set()
    for record in records:
        name = str(record.get("name", ""))
        if not name.startswith(prefix):
            raise CloudError(f"Output inventory unexpectedly escaped {prefix}: {name}")
        relative = name[len(prefix):]
        if not relative or name.endswith("/") or relative == "README-layout.txt":
            continue
        if relative.casefold() == ".matlab-cloud-download.json":
            raise CloudError("Output filename conflicts with the collector's local verification record: " + name)
        safe_parts(relative)
        normalized = relative.casefold()
        if normalized in seen:
            raise CloudError(f"Case-colliding output filenames cannot be downloaded safely: {relative}")
        seen.add(normalized)
        generation = str(record.get("generation", ""))
        if not generation.isdigit():
            raise CloudError(f"Output object is missing a generation: {name}")
        selected.append({"name": name, "relative": relative, "generation": generation, "size": int(record.get("size", -1)), "md5_hash": record.get("md5_hash") or record.get("md5Hash"), "crc32c_hash": record.get("crc32c_hash") or record.get("crc32c")})
    return sorted(selected, key=lambda item: item["name"])


def download_snapshot(ctx, project, group, records, required=False):
    """Download an immutable object-generation snapshot without replacing old files."""
    prefix = "outputs/" + (group + "/" if group != "retained-root" else "")
    manifest = inventory(records, prefix)
    if not manifest:
        if required:
            raise CloudError(f"{project.name}/{group}: job is finished but has no output objects; logs were archived. No results download was reported as complete.")
        return None
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode("utf-8")).hexdigest()
    safe_parts(group)
    base = ctx.root / "downloads" / project.name / group
    safe_destination(ctx.root / "downloads", project.name + "/" + group + "/snapshot-" + digest[:16])
    target = base / ("snapshot-" + digest[:16])
    completion = target / ".matlab-cloud-download.json"
    if completion.exists():
        saved = read_json(completion)
        if saved.get("inventory_sha256") == digest:
            hashes = saved.get("local_sha256", {})
            valid = len(hashes) == len(manifest)
            for item in manifest:
                path = safe_destination(target, item["relative"])
                if not path.is_file() or path.stat().st_size != item["size"] or hashes.get(item["relative"]) != hash_file(path).hex():
                    valid = False
                    break
            if valid:
                ctx.log(f"{project.name}/{group}: results already downloaded; local checksums verified.")
                return target
            # Keep altered user data; write a new copy instead of overwriting it.
            target = base / ("snapshot-" + digest[:16] + "-recovered-" + uuid.uuid4().hex[:8])
            ctx.log(f"{project.name}/{group}: previous local copy changed; preserving it and downloading a fresh copy.")
    elif target.exists():
        target = base / ("snapshot-" + digest[:16] + "-retry-" + uuid.uuid4().hex[:8])
    if ctx.dry_run:
        ctx.log(f"[Preview] Would download {len(manifest)} output files ({sum(item['size'] for item in manifest):,} bytes) to {target}.")
        return target
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    if project.config.get("batch_mode") == "trial_shards":
        # Group only files with the same destination parent, so the CLI cannot
        # flatten different task folders or collide with identical basenames.
        parents = {}
        for item in manifest:
            local = safe_destination(target, item["relative"])
            local.parent.mkdir(parents=True, exist_ok=True)
            parents.setdefault(local.parent, []).append(item)
        batches = []
        for parent, items in parents.items():
            batch, length = [], 0
            for item in items:
                uri = f"gs://{project.bucket}/{item['name']}#{item['generation']}"
                if batch and length + len(uri) > 16000:
                    batches.append((parent,batch))
                    batch, length = [], 0
                batch.append((item,uri))
                length += len(uri) + 3
            if batch:
                batches.append((parent,batch))

        def transfer_batch(batch):
            parent, objects = batch
            ctx.gcloud("storage", "cp", *(uri for _,uri in objects), str(parent),
                       "--do-not-decompress", "--no-clobber")
            verified = {}
            for item,_ in objects:
                local = safe_destination(target,item["relative"])
                verify_file(ctx,local,item)
                verified[item["relative"]] = hash_file(local).hex()
            return verified

        with ThreadPoolExecutor(max_workers=min(4,len(batches))) as executor:
            for verified in executor.map(transfer_batch,batches):
                hashes.update(verified)
    else:
        for item in manifest:
            local = safe_destination(target, item["relative"])
            local.parent.mkdir(parents=True, exist_ok=True)
            # Every transfer is pinned to its inventoried object generation.
            uri = f"gs://{project.bucket}/{item['name']}#{item['generation']}"
            ctx.gcloud("storage", "cp", uri, str(local), "--do-not-decompress", "--no-clobber")
            verify_file(ctx, local, item)
            hashes[item["relative"]] = hash_file(local).hex()
    after = inventory(list_objects(ctx, f"gs://{project.bucket}/{prefix.rstrip('/')}"), prefix)
    if group == "retained-root":
        after = [item for item in after if "/" not in item["relative"]]
    if after != manifest:
        raise CloudError(f"{project.name}/{group}: cloud outputs changed while downloading. The partial snapshot is retained; rerun to collect a stable snapshot.")
    write_json(target / ".matlab-cloud-download.json", {"inventory_sha256": digest, "objects": manifest, "local_sha256": hashes, "downloaded_utc": datetime.now(timezone.utc).isoformat()})
    ctx.log(f"{project.name}/{group}: downloaded and verified {len(manifest)} output files in {target}.")
    return target


def list_jobs(ctx):
    jobs = ctx.gcloud("batch", "jobs", "list", "--location=" + ctx.region, json_output=True)
    if not isinstance(jobs, list):
        raise CloudError("Unexpected Batch job inventory.")
    write_json(ctx.run_dir / "jobs-latest.json", jobs)
    return jobs


def job_id(job):
    value = str(job.get("name", "")).rsplit("/", 1)[-1]
    if not re.fullmatch(r"[a-z][a-z0-9-]{0,62}", value):
        raise CloudError(f"Unexpected Batch job ID: {value!r}")
    return value


def job_state(job):
    return str(job.get("status", {}).get("state", "UNKNOWN")).upper()


def archive_job(ctx, project, job):
    ident = job_id(job)
    destination = ctx.run_dir / "jobs" / project.name / ident
    description = ctx.gcloud("batch", "jobs", "describe", ident, "--location=" + ctx.region, json_output=True)
    write_json(destination / "job.json", description)
    uid = str(description.get("uid", ""))
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", uid):
        raise CloudError(f"No valid UID returned for Batch job {ident}; refusing to guess its log filter.")
    log_filter = f'labels.job_uid="{uid}"'
    logs = ctx.gcloud("logging", "read", log_filter, "--order=asc", "--freshness=3650d", "--limit=100000", json_output=True)
    write_json(destination / "logs.json", logs)
    if isinstance(logs, list) and len(logs) >= 100000:
        raise CloudError(f"Log export for {ident} reached its record cap; inspect/archive the remaining logs before considering the record complete.")


def collect_outputs(ctx, projects, jobs, failed_projects=None, processed=None, include_historical=True):
    failed_projects = set(failed_projects or [])
    processed = processed if processed is not None else set()
    managed = {project.key: project for project in projects}
    terminal = {}
    active = {}
    failures = []
    for job in jobs:
        project = managed.get(job.get("labels", {}).get("matlab_project"))
        if project is None:
            continue
        ident, state = job_id(job), job_state(job)
        if ident not in processed:
            ctx.log(f"{project.name}: Batch {ident} is {state}.")
        if state in ACTIVE or state in {"STATE_UNSPECIFIED", "UNKNOWN"}:
            active[ident] = project
        elif state in TERMINAL:
            terminal[(project.key, ident)] = job
        else:
            # DELETION_IN_PROGRESS can still contain active compute/writers.
            active[ident] = project
    for project in projects:
        if project.key in failed_projects:
            continue
        if not include_historical and not any(key == project.key and ident not in processed for key, ident in terminal):
            continue
        try:
            records = list_objects(ctx, project.outputs_uri)
            groups = {}
            for record in records:
                name = str(record.get("name", ""))
                if not name.startswith("outputs/"):
                    raise CloudError(f"Unexpected output prefix in {project.bucket}: {name}")
                relative = name[len("outputs/"):]
                if not relative or relative == "README-layout.txt" or name.endswith("/"):
                    continue
                group = relative.split("/", 1)[0] if "/" in relative else "retained-root"
                groups.setdefault(group, []).append(record)
            for (key, ident), job in terminal.items():
                if key != project.key or ident in processed:
                    continue
                archive_job(ctx, project, job)
                group_records = groups.pop(ident, [])
                if not group_records and job_state(job) != 'SUCCEEDED':
                    ctx.log(f"WARNING: {project.name}/{ident} ended {job_state(job)} without output files. No results were downloaded. Logs are archived under {ctx.run_dir / 'jobs' / project.name / ident}.")
                    processed.add(ident)
                    continue
                snapshot = download_snapshot(ctx, project, ident, group_records, required=True)
                if job.get("labels", {}).get("matlab_cloud_mode") == "trial_shards":
                    from matlab_cloud_trials import collect_trial_results
                    collect_trial_results(ctx, project, job, snapshot)
                elif job.get("labels", {}).get("matlab_cloud_managed") == "true" and not any(record.get("name") == f"outputs/{ident}/_TRANSFER_COMPLETE.json" for record in group_records):
                    failures.append(f"{project.name}/{ident}: output transfer completion marker is missing; downloaded files are an unverified partial recovery.")
                processed.add(ident)
                if job_state(job) != "SUCCEEDED":
                    failures.append(f"{project.name}/{ident} ended {job_state(job)}; downloaded outputs are partial.")
            for group, group_records in groups.items():
                if not include_historical:
                    continue
                if group in active:
                    ctx.log(f"{project.name}/{group}: waiting for the active job before downloading its outputs.")
                    continue
                if group in processed:
                    continue
                download_snapshot(ctx, project, group, group_records)
            if not groups and not any(key == project.key for key, _ in terminal):
                ctx.log(f"{project.name}: no retained output data is currently available.")
        except (CloudError, OSError, ValueError) as exc:
            failures.append(f"{project.name}: {exc}")
            ctx.log("ERROR: " + failures[-1])
    return active, failures


def watch_jobs(ctx, projects, jobs=None, once=False, failed_projects=None, expected_job=None):
    jobs = list_jobs(ctx) if jobs is None else jobs
    processed = set()
    failures = []
    previously_active = set()
    if expected_job:
        previously_active.add(expected_job)
    while True:
        present = {job_id(job) for job in jobs}
        missing = previously_active - present
        if missing:
            failures.append("Previously active jobs disappeared before completion could be verified: " + ", ".join(sorted(missing)))
        active, new_failures = collect_outputs(ctx, projects, jobs, failed_projects, processed)
        failures.extend(new_failures)
        if once or ctx.dry_run or not active:
            if active:
                ctx.log(f"{len(active)} managed job(s) still active. Run matlab-cloud again to wait and collect their results.")
            break
        previously_active = set(active)
        interval = max(5, int(ctx.settings.get("poll_seconds", 60)))
        ctx.log(f"Waiting {interval} seconds for {len(active)} managed job(s). Ctrl+C ends this local watcher and leaves cloud jobs running.")
        time.sleep(interval)
        jobs = list_jobs(ctx)
    return failures


class Workflow:
    """Serialize user operations against collection; parallelize independent projects."""
    def __init__(self, ctx, projects):
        self.ctx = ctx
        self.projects = projects
        self.operation_lock = threading.RLock()
        self.errors = []
        self.failed_projects = set()
        self.processed = set()
        self.known_states = {}
        self.submitted_jobs = []
        self.stop_event = threading.Event()
        self.monitor_thread = None

    def _error(self, text):
        text = str(text)
        self.errors.append(text)
        self.ctx.log("ERROR: " + text)

    def sync_all(self, rediscover=True):
        with self.operation_lock:
            if rediscover:
                self.projects = discover_projects(self.ctx)
            self.failed_projects.clear()
            # A fresh explicit sync revalidates cached downloads, including files
            # that a user may have edited since the previous synchronization.
            self.processed.clear()
            buckets = self.ctx.gcloud("storage", "buckets", "list", json_output=True)
            owned = {record["name"] for record in buckets}
            jobs = list_jobs(self.ctx)
            keys = {project.key for project in self.projects}
            self.known_states = {job_id(job): job_state(job) for job in jobs if job.get("labels", {}).get("matlab_project") in keys}
            workers = max(1, min(8, int(self.ctx.settings.get("parallel_projects", 4)), len(self.projects)))
            self.ctx.log(f"Synchronizing {len(self.projects)} project(s), with up to {workers} projects in parallel.")

            def pipeline(project):
                errors = []
                failed = False
                try:
                    exists = normalize_bucket(self.ctx, project, set(owned))
                except (CloudError, OSError, ValueError) as exc:
                    return project.key, True, [f"{project.name}: {exc}"]
                # Upload and output download concern different prefixes. They run
                # concurrently once this project's bucket ownership is verified.
                with ThreadPoolExecutor(max_workers=2) as transfers:
                    upload = transfers.submit(synchronize_source, self.ctx, project, exists)
                    download = None
                    if exists:
                        download = transfers.submit(collect_outputs, self.ctx, [project], jobs, None, self.processed)
                    try:
                        upload.result()
                    except (CloudError, OSError, ValueError) as exc:
                        failed = True
                        errors.append(f"{project.name} upload: {exc}")
                    if download:
                        try:
                            _, downloaded_errors = download.result()
                            errors.extend(downloaded_errors)
                        except (CloudError, OSError, ValueError) as exc:
                            errors.append(f"{project.name} download: {exc}")
                if not exists and self.ctx.dry_run:
                    self.ctx.log(f"[Preview] {project.name}: no output download until the new bucket exists.")
                return project.key, failed, errors

            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [executor.submit(pipeline, project) for project in self.projects]
                for future in as_completed(futures):
                    key, failed, errors = future.result()
                    if failed:
                        self.failed_projects.add(key)
                    for error in errors:
                        self._error(error)
            self.ctx.log("All-project synchronization pass finished.")

    def show_jobs(self):
        with self.operation_lock:
            projects = {project.key: project for project in self.projects}
            found = []
            for job in list_jobs(self.ctx):
                project = projects.get(job.get("labels", {}).get("matlab_project"))
                if project:
                    found.append(job)
                    self.ctx.log(f"{project.name} | {job_id(job)} | {job_state(job)}")
            if not found:
                self.ctx.log("No Batch jobs are currently listed for these desktop projects.")
            return found

    def run(self, directory, entry=None):
        with self.operation_lock:
            project = resolve_project(self.projects, directory)
            if project.key in self.failed_projects:
                raise CloudError(f"{project.name} failed source/bucket verification. Run sync successfully before submitting it.")
            project = configure_entry(self.ctx, project, entry)
            from matlab_cloud_run import run_project
            ident = run_project(self.ctx, project, self.ctx.dry_run)
            if not self.ctx.dry_run:
                self.submitted_jobs.append(ident)
                self.known_states[ident] = "SUBMITTED"
            return ident

    def stop(self, target):
        with self.operation_lock:
            from matlab_cloud_stop import stop_jobs
            result = stop_jobs(self.ctx, self.projects, target)
            # Explicitly stopped jobs may disappear; do not misclassify that as
            # an unexpected loss of a still-running job in the monitor.
            jobs = list_jobs(self.ctx)
            keys = {project.key for project in self.projects}
            self.known_states = {job_id(job): job_state(job) for job in jobs if job.get("labels", {}).get("matlab_project") in keys}
            return result

    def poll(self):
        with self.operation_lock:
            jobs = list_jobs(self.ctx)
            projects = {project.key: project for project in self.projects}
            current = {job_id(job): job_state(job) for job in jobs if job.get("labels", {}).get("matlab_project") in projects}
            for ident, old in self.known_states.items():
                if old in ACTIVE | {"SUBMITTED"} and ident not in current:
                    self._error(f"Previously active job {ident} disappeared before completion was verified. Any retained outputs can still be collected with sync.")
            changed = {ident for ident, state in current.items() if self.known_states.get(ident) != state}
            if changed:
                for job in jobs:
                    ident = job_id(job)
                    if ident in changed:
                        project = projects[job["labels"]["matlab_project"]]
                        self.ctx.log(f"{project.name}: {ident} is now {job_state(job)}.")
            from matlab_cloud_progress import read_progress, print_progress
            for job in jobs:
                project = projects.get(job.get("labels", {}).get("matlab_project"))
                if project and job_state(job) in ACTIVE and job.get("labels", {}).get("matlab_cloud_live") == "true":
                    try:
                        snapshot = read_progress(self.ctx, project, job)
                        if snapshot:
                            print_progress(self.ctx, project, job, snapshot, detailed=False)
                    except (CloudError, OSError, ValueError) as error:
                        self.ctx.log(f"Live progress unavailable for {job_id(job)}: {error}; the monitor will retry.")
            terminal_keys = {job.get("labels", {}).get("matlab_project") for job in jobs if job_state(job) in TERMINAL and job_id(job) not in self.processed}
            eligible = [project for project in self.projects if project.key in terminal_keys]
            if eligible:
                with ThreadPoolExecutor(max_workers=min(4, len(eligible))) as executor:
                    futures = [executor.submit(collect_outputs, self.ctx, [project], jobs, None, self.processed, False) for project in eligible]
                    for future in as_completed(futures):
                        _, errors = future.result()
                        for error in errors:
                            if error not in self.errors:
                                self._error(error)
            self.known_states = current

    def start_monitor(self):
        if self.ctx.dry_run or self.monitor_thread is not None:
            return
        interval = max(5, int(self.ctx.settings.get("poll_seconds", 60)))
        def loop():
            while not self.stop_event.wait(interval):
                try:
                    self.poll()
                except (CloudError, OSError, ValueError, RuntimeError) as exc:
                    self._error(f"Completion monitor: {exc}. It will retry at the next check.")
        self.monitor_thread = threading.Thread(target=loop, name="matlab-cloud-monitor", daemon=True)
        self.monitor_thread.start()
        self.ctx.log(f"Completion monitoring is active every {interval} seconds while this console is open.")

    def close(self):
        self.stop_event.set()
        if self.monitor_thread is not None:
            self.monitor_thread.join()


def split_menu_command(text):
    # Windows paths retain their backslashes; quotes are grouping only, never
    # shell syntax. We never execute this text as a command line.
    tokens = []
    current = []
    quoted = False
    started = False
    for character in text:
        if character == '"':
            quoted = not quoted
            started = True
        elif character.isspace() and not quoted:
            if started:
                tokens.append("".join(current))
                current, started = [], False
        else:
            current.append(character)
            started = True
    if quoted:
        raise CloudError("The command contains an unclosed double quote.")
    if started:
        tokens.append("".join(current))
    return tokens


MENU = 'Commands: sync | run | jobs | progress | stop | help | exit. Type help for complete examples.'


def show_command_help(workflow):
    ctx = workflow.ctx
    ctx.log(MENU)
    ctx.log('Type commands without square brackets and without the matlab-cloud> prompt prefix.')
    for project in getattr(workflow, 'projects', []):
        entries = project.config.get('entry_points', [])
        if entries:
            ctx.log(f'{project.name}: use its configured entry point, or specify a script:')
            ctx.log(f'  run "{project.name}"')
            ctx.log(f'  run "{project.name}" "{entries[0]}"')
        else:
            for candidate in project.config.get('entry_point_candidates', [])[:2]:
                ctx.log(f'  run "{project.name}" "{candidate}"')
            ctx.log(f'  {project.name}: no default entry point; supply a script path inside this project.')
        ctx.log(f'  stop "{project.name}"')
        ctx.log(f'  progress "{project.name}"')
    ctx.log('Other commands:')
    for command in ('sync', 'jobs', 'stop all', 'stop', 'help', 'exit'):
        ctx.log('  ' + command)
    ctx.log('sync repeats synchronization; jobs lists states; stop shows stopping instructions; exit leaves cloud jobs running.')
    ctx.log('To stop a specific job, type stop followed by its actual job ID from jobs. With no active jobs, stop reports Nothing to stop.')


def interactive(workflow):
    ctx = workflow.ctx
    workflow.start_monitor()
    show_command_help(workflow)
    ctx.log("Background transfers continue while this prompt is idle; their messages appear after you press Enter.")
    while True:
        try:
            text = ctx.prompt("matlab-cloud> ")
        except (EOFError, KeyboardInterrupt):
            ctx.log("Leaving the console. Cloud jobs continue; reopen matlab-cloud to resume monitoring.")
            return
        try:
            words = split_menu_command(text)
            if words and words[0].casefold() in {"exit", "quit"} and len(words) == 1:
                ctx.log("Leaving the console. Cloud jobs continue; reopen matlab-cloud to resume monitoring.")
                return
            auth_needed = getattr(ctx, "auth_needed", None)
            if auth_needed is not None and auth_needed.is_set():
                ctx.authenticate()
                ctx.gcloud("projects", "describe", ctx.project, json_output=True, _retry_auth=False)
            if not words:
                continue
            command, arguments = words[0].casefold(), words[1:]
            if command in {"help", "?"}:
                show_command_help(workflow)
            elif command == "sync" and not arguments:
                workflow.sync_all()
            elif command == "jobs" and not arguments:
                workflow.show_jobs()
            elif command == "progress" and len(arguments) == 1:
                from matlab_cloud_progress import show_progress
                show_progress(workflow, arguments[0])
            elif command == "run" and len(arguments) in {1, 2}:
                workflow.run(*arguments)
            elif command == "run" and not arguments:
                show_command_help(workflow)
            elif command == "stop" and len(arguments) == 1:
                workflow.stop(arguments[0])
            elif command == "stop" and not arguments:
                workflow.show_jobs()
                show_command_help(workflow)
            elif len(words) in {1, 2}:
                try:
                    resolve_project(workflow.projects, words[0])
                except CloudError:
                    raise CloudError("Unknown command or project. " + MENU) from None
                workflow.run(*words)
            else:
                raise CloudError("Unknown command or wrong arguments. " + MENU)
        except (CloudError, OSError, ValueError, RuntimeError) as exc:
            workflow._error(exc)


def parser():
    result = argparse.ArgumentParser(description="Automatically create project buckets, upload all desktop projects, download completed outputs, then open a command prompt with background completion monitoring.")
    result.add_argument("command", nargs="*", help='Examples: run "GlOp_cmp" OR run "GlOp_cmp" "main.m". The script path can be omitted with a configured entry point. Do not type square brackets.')
    result.add_argument("--dry-run", action="store_true", help="Preview cloud changes; do not create project settings, upload, download, or submit jobs.")
    result.add_argument("--once", action="store_true", help="Perform one pass and optional command, then return without opening the interactive console.")
    result.add_argument("--settings", help="Alternative cloud-settings.json path.")
    result.add_argument("--gcloud", help="Google Cloud CLI path (normally supplied by the CMD launcher).")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    root = Path(__file__).resolve().parent
    command = args.command
    selected = []
    initial_action = None
    if command:
        if command[0].casefold() == "run":
            if len(command) not in {2, 3}:
                raise CloudError('Use matlab-cloud.cmd run "Project directory" OR matlab-cloud.cmd run "Project directory" "script.m". Do not type square brackets.')
            selected = command[1:]
        elif command[0].casefold() in {"jobs", "sync", "help"} and len(command) == 1:
            initial_action = command[0].casefold()
        elif command[0].casefold() == "stop" and len(command) == 2:
            initial_action = "stop"
        elif command[0].casefold() == "progress" and len(command) == 2:
            initial_action = "progress"
        elif command[0].casefold() == "stop" and len(command) == 1:
            initial_action = "stop_help"
        elif len(command) in {1, 2}:
            selected = command
        else:
            raise CloudError("Unexpected command arguments. " + MENU)
    settings = read_json(args.settings or root / "cloud-settings.json")
    for required in ("project", "region", "environment_image", "workspace_root"):
        if not isinstance(settings.get(required), str) or not settings[required].strip():
            raise CloudError(f"Missing required cloud setting: {required}")
    executable = args.gcloud or os.environ.get("MATLAB_CLOUD_GCLOUD") or shutil.which("gcloud.cmd") or shutil.which("gcloud")
    if not executable:
        raise CloudError("Google Cloud CLI was not found. Install it and authenticate manually first.")
    ctx = Context(executable, root, settings, args.dry_run,
                  allow_auth_login=not args.once and not args.dry_run)
    ctx.log("MATLAB cloud workflow" + (" [PREVIEW - no cloud changes or project manifest writes]" if args.dry_run else ""))
    ctx.log(f"Reports: {ctx.run_dir}")
    projects = discover_projects(ctx)
    if selected:
        resolve_project(projects, selected[0])
    if initial_action == "progress":
        from matlab_cloud_progress import show_progress
        show_progress(Workflow(ctx, projects), command[1])
        return 0
    ctx.verify_environment()
    workflow = Workflow(ctx, projects)
    try:
        workflow.sync_all(rediscover=False)
        try:
            if selected:
                workflow.run(*selected)
            elif initial_action == "jobs":
                workflow.show_jobs()
            elif initial_action == "stop":
                workflow.stop(command[1])
            elif initial_action in {"help", "stop_help"}:
                if initial_action == "stop_help":
                    workflow.show_jobs()
                show_command_help(workflow)
        except (CloudError, OSError, ValueError, RuntimeError) as exc:
            workflow._error(exc)
        if not args.once and not args.dry_run:
            interactive(workflow)
    finally:
        workflow.close()
    failures = workflow.errors
    write_json(ctx.run_dir / "result.json", {"dry_run": ctx.dry_run, "projects": [project.name for project in workflow.projects], "submitted_jobs": workflow.submitted_jobs, "errors": failures})
    if failures:
        ctx.log("Workflow finished with errors:")
        for failure in dict.fromkeys(failures):
            ctx.log("  " + failure)
        return 1
    ctx.log("Preview complete." if ctx.dry_run else "Workflow session ended. Available completed outputs were collected; cloud jobs are left running unless explicitly stopped.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nLocal workflow interrupted. Cloud jobs remain running; run matlab-cloud again to resume collection.", file=sys.stderr)
        sys.exit(130)
    except (CloudError, OSError, ValueError) as error:
        print("ERROR: " + str(error), file=sys.stderr)
        sys.exit(1)
