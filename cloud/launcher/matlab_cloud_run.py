"""Google Cloud Batch launch support for the Windows MATLAB cloud workflow.

Only run_project(..., dry_run=False) submits compute. Cloud commands use argument
arrays, and all JSON and embedded Python are generated without shell evaluation.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import shutil
import uuid
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from matlab_cloud import Context, Project

SHARED = "/work/shared"
WORKSPACE = SHARED + "/workspace"
TRANSFER_MARKER = "_TRANSFER_COMPLETE.json"
DEFAULTS = {"machine_type": "e2-standard-8", "cpu_milli": 8000,
            "memory_mib": 30000, "boot_disk_gb": 100,
            "max_run_seconds": 259200}


def _positive_int(value: Any, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= maximum:
        raise ValueError(f"{name} must be an integer between 1 and {maximum}.")
    return value


def _entry_points(project: Project) -> list[str]:
    entries = project.config.get("entry_points")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{project.name}: set entry_points in matlab-cloud.json to the intended main script(s).")
    root = Path(project.directory).resolve()
    checked: list[str] = []
    for value in entries:
        if not isinstance(value, str) or not value or "\\" in value:
            raise ValueError("Each entry point must be a relative .m file using forward slashes.")
        path = PurePosixPath(value)
        if path.is_absolute() or any(part in ("", ".", "..") for part in value.split("/")) or path.suffix != ".m":
            raise ValueError(f"Invalid entry point: {value!r}; use an exact relative .m filename.")
        current = root
        for part in path.parts:
            if part not in {child.name for child in current.iterdir()}:
                raise ValueError(f"Entry point does not exist with exact Linux filename case: {value}")
            current = current / part
            if current.is_symlink() or bool(getattr(current, "is_junction", lambda: False)()):
                raise ValueError(f"Entry point cannot traverse a symbolic link: {value}")
        if not current.is_file() or not current.resolve().is_relative_to(root):
            raise ValueError(f"Entry point is not a file inside this project: {value}")
        checked.append(path.as_posix())
    return checked


def _license(ctx: Context, project: Project, dry_run: bool) -> tuple[str, dict[str, Any]]:
    config = project.config.get("license", ctx.settings.get("license", {}))
    if not isinstance(config, dict):
        raise ValueError("license must be a JSON object.")
    mode = config.get("mode", "unconfigured")
    if mode == "online":
        if config.get("image_prepared") is not True:
            if not dry_run:
                raise ValueError("Campus-Wide online licensing needs an authenticated, saved image first. Complete matlab-cloud-license-login.cmd, verify the saved image, then set license.image_prepared=true.")
            ctx.log("PREVIEW: online licensing image is not prepared; complete the MathWorks container sign-in before submitting compute.")
        return "/usr/local/bin/matlab", {}
    if mode in ("server", "network"):
        server = config.get("server", "")
        if not isinstance(server, str) or not re.fullmatch(r"[0-9]+@[A-Za-z0-9_.-]+(?:[:;,][0-9]+@[A-Za-z0-9_.-]+)*", server):
            raise ValueError("Network license server must use port@hostname, for example 27000@license.example.edu.")
        return "/usr/local/bin/matlab", {"variables": {"MLM_LICENSE_FILE": server}}
    if mode == "secret_version":
        secret = config.get("secret_version", "")
        binary = config.get("matlab_batch_executable", "")
        if not isinstance(secret, str) or not re.fullmatch(r"projects/[A-Za-z0-9_-]+/secrets/[A-Za-z0-9_-]+/versions/(?:[0-9]+|latest)", secret):
            raise ValueError("Batch-token license needs a Secret Manager version resource in secret_version.")
        if not isinstance(binary, str) or not binary.startswith("/") or PurePosixPath(binary).name != "matlab-batch" or any(p in binary for p in ("..", "\n", "\r", "\x00")):
            raise ValueError("This shared image has no verified matlab-batch executable. Supply an existing absolute matlab_batch_executable path before token-mode launch; the workflow never installs or changes images automatically.")
        return binary, {"secretVariables": {"MLM_LICENSE_TOKEN": secret}}
    if mode == "unconfigured" and dry_run:
        ctx.log("PREVIEW: MATLAB licensing is UNCONFIGURED. This plan cannot be submitted until license settings are supplied.")
        return "/usr/local/bin/matlab", {}
    if mode == "unconfigured":
        raise ValueError("MATLAB cloud licensing is unconfigured. Configure a license server or prepare Campus-Wide online licensing as described in README.md before submitting compute.")
    raise ValueError(f"Unsupported license mode: {mode!r}")


def _python_container(image: str, program: str, volume: str) -> dict[str, Any]:
    return {"imageUri": image, "entrypoint": "/usr/lib/google-cloud-sdk/platform/bundledpythonunix/bin/python3", "commands": ["-c", program],
            "volumes": [volume], "options": "--user 0:0"}


def _task_root(distributed: bool) -> list[str]:
    if not distributed:
        return [f"root = pathlib.Path({SHARED!r})"]
    return ["task_index = int(os.environ['BATCH_TASK_INDEX'])",
            "task_count = int(os.environ['BATCH_TASK_COUNT'])",
            "if not 0 <= task_index < task_count: raise RuntimeError('Invalid Batch task identity')",
            f"root = pathlib.Path({SHARED!r}) / 'tasks' / f'{{task_index:05d}}'",
            "root.mkdir(parents=True, exist_ok=True)"]


def _prepare_program(source_uri: str, distributed: bool = False) -> str:
    # repr supplies Python literals; callers never concatenate shell commands.
    return "\n".join([
        "import json, os, pathlib, shutil, subprocess, sys",
        "os.environ['CLOUDSDK_PYTHON'] = sys.executable",
        *_task_root(distributed),
        "storage = shutil.disk_usage(root)",
        "inodes = os.statvfs(root)",
        "mount_record, mount_depth = None, -1",
        "for record in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():",
        "    mount_path = pathlib.Path(record.split()[4].replace(r'\\040', ' ').replace(r'\\011', '\\t').replace(r'\\134', '\\\\'))",
        "    if root.resolve().is_relative_to(mount_path) and len(mount_path.parts) > mount_depth:",
        "        mount_record, mount_depth = record, len(mount_path.parts)",
        "if mount_record is None: raise RuntimeError('Cannot identify the workspace backing filesystem')",
        "filesystem = mount_record.split(' - ', 1)[1].split()[0]",
        "print(json.dumps({'event':'workspace-storage','path':str(root),'total_bytes':storage.total,'free_bytes':storage.free,'total_inodes':inodes.f_files,'available_inodes':inodes.f_favail,'filesystem':filesystem,'mountinfo':mount_record}),flush=True)",
        "if filesystem == 'tmpfs': raise RuntimeError('Workspace is backed by tmpfs, not the boot disk; bind /var/lib/google/matlab-cloud or mount a real disk before source transfer')",
        "workspace = root / 'workspace'",
        "if workspace.exists() and any(workspace.iterdir()): raise RuntimeError('Refusing nonempty run workspace')",
        "workspace.mkdir(parents=True, exist_ok=True)",
        "(root / 'logs').mkdir(exist_ok=True)",
        "(root / 'results').mkdir(exist_ok=True)",
        "(root / 'live').mkdir(exist_ok=True)",
        f"subprocess.run(['gcloud','storage','rsync',{source_uri!r},str(workspace),'--recursive','--checksums-only'],check=True)",
        "if not any(workspace.rglob('*')): raise RuntimeError('Downloaded source is empty')",
        "for path in [root, *root.rglob('*')]:",
        "    if path.is_symlink(): raise RuntimeError('Unexpected source symlink')",
        "    os.chown(path,1001,1001)",
        "    os.chmod(path,0o775 if path.is_dir() else 0o664)",
        "(root / '_PREPARED.json').write_text(json.dumps({'prepared':True}),encoding='utf-8')",
    ])


def _live_program(output_uri: str, job_id: str, workers: int, interval: int) -> str:
    return "\n".join([
        "import os, pathlib, runpy, sys",
        *_task_root(True),
        f"sys.argv = [str(root/'workspace/cloud/live_reporter.py'), '--root', str(root/'live'), '--output-uri', {output_uri!r}, '--job-id', {job_id!r}, '--workers', {str(workers)!r}, '--interval', {str(interval)!r}]",
        "runpy.run_path(sys.argv[0], run_name='__main__')",
    ])


def _collect_program(output_uri: str, job_id: str, distributed: bool = False,
                     workers: int = 0, live: bool = False) -> str:
    published_count = "flush['completed_trials']" if live else "None"
    if distributed:
        return "\n".join([
            "import datetime, hashlib, json, os, pathlib, subprocess, sys",
            "os.environ['CLOUDSDK_PYTHON'] = sys.executable",
            *_task_root(True),
            "if not (root / '_PREPARED.json').is_file(): raise RuntimeError('Source preparation did not finish')",
            "if any(path.is_symlink() for path in root.rglob('*')): raise RuntimeError('Unexpected output symlink')",
            f"output_uri = {output_uri!r}",
            "task_uri = output_uri + f'/tasks/{task_index:05d}'",
            "subprocess.run(['gcloud','storage','rsync',str(root/'logs'),task_uri+'/logs','--recursive','--checksums-only'],check=True)",
            *([
                f"subprocess.run([sys.executable,str(root/'workspace/cloud/live_reporter.py'),'--root',str(root/'live'),'--output-uri',output_uri,'--job-id',{job_id!r},'--workers',{str(workers)!r},'--final'],check=True)",
                "flush = json.loads((root/'live/_FLUSHED.json').read_text())",
                "if flush['status'] != 'completed': raise RuntimeError('Partial live results recovered; MATLAB did not complete every assigned trial')",
            ] if live else []),
            "if task_index == 0:",
            "    subprocess.run(['gcloud','storage','rsync',str(root/'workspace'),output_uri+'/workspace','--recursive','--checksums-only'],check=True)",
            "shard = root / 'results' / f'trial_shard_{task_index:05d}.mat'",
            "if not shard.is_file(): raise RuntimeError('No completed trial shard; partial logs recovered')",
            "subprocess.run(['gcloud','storage','cp',str(shard),output_uri+'/results/'+shard.name,'--if-generation-match=0'],check=True)",
            f"marker = root / {TRANSFER_MARKER!r}",
            f"marker.write_text(json.dumps({{'schema_version':2,'job_id':{job_id!r},'task_index':task_index,'task_count':task_count,'workers_per_task':{workers!r},'live_reporting':{live!r},'live_published_trials':{published_count},'shard_sha256':hashlib.sha256(shard.read_bytes()).hexdigest(),'collected_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}},indent=2),encoding='utf-8')",
            "subprocess.run(['gcloud','storage','cp',str(marker),task_uri+'/'+marker.name,'--if-generation-match=0'],check=True)",
            "print(f'Task {task_index} shard and transfer marker uploaded.',flush=True)",
        ])
    return "\n".join([
        "import datetime, json, os, pathlib, subprocess, sys",
        "os.environ['CLOUDSDK_PYTHON'] = sys.executable",
        f"root = pathlib.Path({SHARED!r})",
        "if not (root / '_PREPARED.json').is_file(): raise RuntimeError('Source preparation did not finish; no complete run workspace to collect')",
        "if any(path.is_symlink() for path in root.rglob('*')): raise RuntimeError('Run outputs contain a symbolic link; refusing to follow it during collection')",
        "for name in ('workspace','logs','results'):",
        "    local = root / name",
        "    if local.exists():",
        f"        subprocess.run(['gcloud','storage','rsync',str(local),{output_uri!r}+'/'+name,'--recursive','--checksums-only'],check=True)",
        f"marker = root / {TRANSFER_MARKER!r}",
        f"marker.write_text(json.dumps({{'schema_version':1,'job_id':{job_id!r},'collected_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'workspace_included':True,'scientific_completion_verified':False}},indent=2),encoding='utf-8')",
        f"subprocess.run(['gcloud','storage','cp',str(marker),{output_uri + '/' + TRANSFER_MARKER!r},'--if-generation-match=0'],check=True)",
        "print('Output collection completed. Scientific success is determined separately by the Batch job status and the project results.')",
    ])


def build_job(ctx: Context, project: Project, job_id: str, source_uri: str,
              dry_run: bool) -> dict[str, Any]:
    """Build a validated, reviewable Batch request without side effects."""
    entries = _entry_points(project)
    distributed = project.config.get("batch_mode") == "trial_shards"
    live = project.config.get("live_reporting", False)
    if not isinstance(live, bool) or (live and not distributed):
        raise ValueError("live_reporting requires trial_shards mode and a boolean value.")
    interval = _positive_int(project.config.get("live_publish_seconds", 15), "live_publish_seconds", 300)
    task_count = _positive_int(project.config.get("task_count", 1), "task_count", 4000)
    parallelism = _positive_int(project.config.get("parallelism", task_count), "parallelism", 5000)
    tasks_per_node = _positive_int(project.config.get("task_count_per_node", 1), "task_count_per_node", 100000)
    workers = _positive_int(project.config.get("workers_per_task", 1), "workers_per_task", 512)
    if parallelism != task_count or tasks_per_node != 1:
        raise ValueError("Submit only concurrently runnable tasks, with one task per VM.")
    if task_count > 1 and not distributed:
        raise ValueError("Multiple tasks require batch_mode=trial_shards and a sharding-aware entry point.")
    if distributed and entries != ["main.m"]:
        raise ValueError("trial_shards supports this project's single main.m entry point.")
    from matlab_cloud import source_files
    eligible = {path.relative_to(project.directory).as_posix() for path in source_files(project)}
    if any(entry not in eligible for entry in entries):
        raise ValueError("An entry point is excluded from source upload. Choose a script outside excluded output/metadata/credential directories.")
    if live and "cloud/live_reporter.py" not in eligible:
        raise ValueError("Live reporting requires cloud/live_reporter.py in the source snapshot.")
    executable, licensing = _license(ctx, project, dry_run)
    values = {name: project.config.get(name, default) for name, default in DEFAULTS.items()}
    machine = values["machine_type"]
    if not isinstance(machine, str) or not re.fullmatch(r"[a-z][a-z0-9-]+", machine):
        raise ValueError("machine_type must be a valid Google Cloud machine type name.")
    cpu = _positive_int(values["cpu_milli"], "cpu_milli", 512000)
    if distributed and cpu != workers * 1000:
        raise ValueError("Allocate exactly one vCPU per MATLAB worker.")
    memory = _positive_int(values["memory_mib"], "memory_mib", 4194304)
    disk = _positive_int(values["boot_disk_gb"], "boot_disk_gb", 65536)
    seconds = _positive_int(values["max_run_seconds"], "max_run_seconds", 1200000)
    transfer = _positive_int(ctx.settings.get("transfer_timeout_seconds", 3600), "transfer_timeout_seconds", 86400)
    account = ctx.settings.get("service_account", "")
    if not isinstance(account, str) or not re.fullmatch(r"[A-Za-z0-9._-]+@[A-Za-z0-9.-]+\.gserviceaccount\.com", account):
        raise ValueError("Set service_account in cloud-settings.json before generating a cloud run.")
    helper = ctx.settings.get("transfer_image", "")
    if not isinstance(helper, str) or not re.fullmatch(r"(?:gcr\.io/google\.com/cloudsdktool|[a-z0-9-]+-docker\.pkg\.dev/google-cloud-sdk-release/gcloud)/google-cloud-cli(?::[0-9]+\.[0-9]+\.[0-9]+-stable|@sha256:[0-9a-f]{64})", helper):
        raise ValueError("transfer_image must pin the official Google Cloud CLI image by numeric -stable version or SHA-256 digest.")
    digest = ctx.env_digest
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise ValueError("Reusable MATLAB environment digest is not verified.")
    image_name = ctx.env_image.split("@")[0]
    if ":" in image_name.rsplit("/", 1)[-1]:
        image_name = image_name.rsplit(":", 1)[0]
    image = image_name + "@" + digest
    # COS /mnt/disks is tmpfs unless a disk is explicitly mounted there.
    volume = f"/var/lib/google/matlab-cloud:{SHARED}:rw"
    output_uri = f"gs://{project.bucket}/outputs/{job_id}"
    runnables: list[dict[str, Any]] = [{
        "displayName": "prepare-source", "timeout": f"{transfer}s",
        "container": _python_container(helper, _prepare_program(source_uri, distributed), volume)}]
    if live:
        runnables.append({"displayName": "publish-live-trials", "background": True,
                          "timeout": f"{seconds + transfer + 300}s",
                          "container": _python_container(helper, _live_program(output_uri, job_id, workers, interval), volume)})
    # The limit applies to each script; the task gets explicit transfer headroom.
    for index, entry in enumerate(entries, 1):
        absolute = PurePosixPath(WORKSPACE) / entry
        escape = lambda value: str(value).replace("'", "''")
        statement = f"cd('{escape(absolute.parent)}'); run('{escape(absolute)}');"
        arguments = ["-logfile", f"{SHARED}/logs/matlab-{index:02d}.log"]
        if distributed:
            # MATLAB expands the task identity itself; no shell/Docker variable expansion.
            statement = (f"taskRoot=fullfile('{SHARED}','tasks',sprintf('%05d',str2double(getenv('BATCH_TASK_INDEX')))); "
                         "setenv('FPF_OUTPUT_DIR',fullfile(taskRoot,'results')); "
                         "setenv('MATLAB_CLOUD_OUTPUT_DIR',fullfile(taskRoot,'results')); "
                         "setenv('MATLAB_CLOUD_PROJECT_DIR',fullfile(taskRoot,'workspace')); "
                         + ("setenv('FPF_LIVE_DIR',fullfile(taskRoot,'live')); " if live else "") +
                         f"diary(fullfile(taskRoot,'logs','matlab-{index:02d}.log')); "
                         "cd(fullfile(taskRoot,'workspace')); run('main.m'); diary off;")
            arguments = ["-singleCompThread", "-noFigureWindows"]
        license_config = project.config.get("license", ctx.settings.get("license", {}))
        if license_config.get("mode") == "online":
            arguments.extend(["-licmode", "onlinelicensing"])
        if executable == "/usr/local/bin/matlab":
            arguments.append("-batch")
        arguments.append(statement)
        environment: dict[str, Any] = {"variables": {
            "MATLAB_CLOUD_OUTPUT_DIR": SHARED + "/results",
            "MATLAB_CLOUD_PROJECT_DIR": WORKSPACE}}
        if distributed:
            environment["variables"].update(FPF_WORKERS_PER_TASK=str(workers),
                                             OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
        for kind, mapping in licensing.items():
            environment.setdefault(kind, {}).update(mapping)
        runnables.append({"displayName": f"matlab-entry-{index}", "timeout": f"{seconds}s",
                          "environment": environment,
                          "container": {"imageUri": image, "entrypoint": executable,
                                        "commands": arguments, "volumes": [volume]}})
    runnables.append({"displayName": "preserve-outputs", "alwaysRun": True,
                      "timeout": f"{transfer}s",
                      "container": _python_container(helper, _collect_program(output_uri, job_id, distributed, workers, live), volume)})
    max_duration = seconds * len(entries) + transfer * 2 + 300
    if max_duration > 1209600:
        raise ValueError("Combined entry point and transfer timeouts exceed the 14-day Batch task limit; reduce max_run_seconds or split the work.")
    return {"taskGroups": [{"taskCount": str(task_count), "parallelism": str(parallelism), "taskCountPerNode": str(tasks_per_node),
                             "taskSpec": {"runnables": runnables,
                                          "computeResource": {"cpuMilli": str(cpu), "memoryMib": str(memory)},
                                          "maxRetryCount": 0, "maxRunDuration": f"{max_duration}s"}}],
            "allocationPolicy": {"instances": [{"policy": {"machineType": machine,
                                   "provisioningModel": "STANDARD", "bootDisk": {"type": "pd-balanced", "sizeGb": str(disk)}}}],
                                 "serviceAccount": {"email": account},
                                 "location": {"allowedLocations": ["regions/" + ctx.region]}},
            "labels": {"matlab_project": project.key, "matlab_cloud_managed": "true",
                       **({"matlab_cloud_live": "true"} if live else {}),
                       **({"matlab_cloud_mode": "trial_shards", "matlab_cloud_tasks": str(task_count),
                           "matlab_cloud_workers": str(workers)} if distributed else {})},
            "logsPolicy": {"destination": "CLOUD_LOGGING"}}


def _snapshot(project: Project, destination: Path) -> None:
    from matlab_cloud import source_files
    source_root = Path(project.directory).resolve()
    files = source_files(project)
    if not files:
        raise ValueError(f"{project.name}: no eligible source files to upload.")
    initial = {path: (path.stat().st_size, path.stat().st_mtime_ns) for path in files}
    destination.mkdir(parents=True, exist_ok=False)
    for path in files:
        relative = path.resolve().relative_to(source_root)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    if set(source_files(project)) != set(files):
        raise ValueError("Desktop file inventory changed during run snapshot creation; retry when edits finish.")
    for path, expected in initial.items():
        if (path.stat().st_size, path.stat().st_mtime_ns) != expected:
            raise ValueError(f"Desktop source changed during snapshot creation: {path}")
        target = destination / path.resolve().relative_to(source_root)
        def digest(file: Path) -> bytes:
            result = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
                    result.update(chunk)
            return result.digest()
        if digest(path) != digest(target):
            raise ValueError(f"Desktop source changed or copy verification failed during snapshot creation: {path}")
    # The local source tree is never edited or executed by this module.


def run_project(ctx: Context, project: Project, dry_run: bool) -> str:
    """Snapshot, verify, and submit the selected project; preview never uploads."""
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
    key = re.sub(r"[^a-z0-9-]", "-", project.key.lower()).strip("-")[:28]
    job_id = f"matlab-{key}-{now}-{uuid.uuid4().hex[:6]}"
    source_uri = f"gs://{project.bucket}/runs/{job_id}/source"
    from matlab_cloud_trials import resolve_layout
    project = resolve_layout(ctx, project)
    job = build_job(ctx, project, job_id, source_uri, dry_run)
    plan_path = Path(ctx.run_dir) / f"{job_id}-batch.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    ctx.log(f"Cloud run plan for {project.name}: {plan_path}")
    ctx.log(f"Entry points: {', '.join(project.config['entry_points'])}")
    ctx.log(f"Results: gs://{project.bucket}/outputs/{job_id}/")
    if project.config.get("live_reporting"):
        ctx.log(f"Live statistics: gs://{project.bucket}/outputs/{job_id}/live/summary.json")
        ctx.log(f'Inspect live worker activity and latest results with: progress "{project.name}"')
    if dry_run:
        ctx.log("PREVIEW ONLY: no source snapshot uploaded and no cloud compute submitted.")
        return job_id
    snapshot = Path(ctx.run_dir) / f"{job_id}-source"
    _snapshot(project, snapshot)
    from matlab_cloud import list_objects, verify_source
    if list_objects(ctx, source_uri):
        raise RuntimeError(f"Run snapshot prefix already contains data; refusing to replace it: {source_uri}")
    ctx.gcloud("storage", "rsync", str(snapshot), source_uri,
               "--recursive", "--checksums-only", "--project=" + ctx.project)
    verify_source(ctx, project, source_directory=snapshot, source_uri=source_uri)
    prefix = source_uri.split("/", 3)[3].rstrip("/") + "/"
    expected_names = {prefix + path.relative_to(snapshot).as_posix() for path in snapshot.rglob("*") if path.is_file()}
    actual_names = {record.get("name") for record in list_objects(ctx, source_uri)}
    if expected_names != actual_names:
        raise RuntimeError("Run snapshot object inventory does not exactly match the current desktop files; no compute submitted.")
    # Existence of a generated JSON file is not proof of job submission.
    ctx.log(f"Submitting exact job ID {job_id}. If interrupted, inspect this ID before requesting another run.")
    submission_error = None
    try:
        ctx.gcloud("batch", "jobs", "submit", job_id, "--location=" + ctx.region,
                   "--project=" + ctx.project, "--config=" + str(plan_path))
    except Exception as error:
        # A lost response does not prove that the server rejected the job.
        submission_error = error
    try:
        created = ctx.gcloud("batch", "jobs", "describe", job_id,
                             "--location=" + ctx.region, "--project=" + ctx.project,
                             json_output=True)
    except Exception as error:
        raise RuntimeError(f"Could not verify submission of job {job_id}. No retry was made. Audit this exact ID before submitting again. Submission/verification error: {submission_error or error}") from error
    if not isinstance(created, dict) or not created.get("uid"):
        raise RuntimeError(f"Job {job_id} was submitted, but its UID could not be verified. Audit it before retrying; do not submit a duplicate.")
    if submission_error is not None:
        ctx.log(f"The submit response reported an error, but {job_id} exists and its UID was verified; continuing without a duplicate submission.")
    (Path(ctx.run_dir) / f"{job_id}-submitted.json").write_text(json.dumps(created, indent=2) + "\n", encoding="utf-8")
    ctx.log(f"Submitted {job_id}; UID {created['uid']}. Waiting and collection continue in the common workflow.")
    return job_id
