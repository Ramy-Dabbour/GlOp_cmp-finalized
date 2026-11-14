"""Durable per-trial MATLAB checkpoints for a retriable GCP Batch shard.

Only the Python standard library is required. The JSON sidecar is the local
ready marker. GCS commit JSON is the remote ready marker. The local ack is
written last, after the immutable MAT, sidecar and remote commit are durable.
No service-account credentials are written to disk or diagnostic output.
"""
from __future__ import annotations

import argparse
import contextlib
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request


IDENTITY_FIELDS = ("run_id", "source_sha256", "config_sha256")
TRIAL_NAME = re.compile(r"trial_(\d{12})\.json\Z")
COMMIT_NAME = re.compile(r"trial_(\d{12})\.commit\.json\Z")
OUTCOMES = ("succeeded", "nonconverged", "failed")


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(",", ":")).encode("utf-8")


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_bytes())
    except FileNotFoundError:
        return default


def atomic_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def atomic_json(path, value):
    atomic_bytes(path, encoded(value))


class Conflict(Exception):
    """GCS rejected an object-generation precondition."""


class IntegrityError(RuntimeError):
    """A run identity, immutable object or checkpoint checksum disagrees."""


class GcsStore:
    """JSON API client authenticated by the VM's attached service account."""

    def __init__(self, bucket):
        self.bucket = urllib.parse.quote(bucket, safe="")
        self.token = ""
        self.expires = 0
        self.token_lock = threading.Lock()
        bundles = (Path("/etc/ssl/certs/ca-certificates.crt"),
                   Path("/usr/lib/google-cloud-sdk/lib/third_party/certifi/cacert.pem"))
        bundle = next((path for path in bundles if path.is_file()), None)
        self.ssl_context = ssl.create_default_context(cafile=str(bundle) if bundle else None)

    def _request(self, url, data=None, headers=None):
        with self.token_lock:
            if time.monotonic() >= self.expires:
                request = urllib.request.Request(
                    "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                    headers={"Metadata-Flavor": "Google"})
                with urllib.request.urlopen(request, timeout=10) as response:
                    credentials = json.load(response)
                self.token = credentials["access_token"]
                self.expires = time.monotonic() + max(1, credentials["expires_in"] - 60)
        request = urllib.request.Request(url, data=data, headers={
            "Authorization": "Bearer " + self.token, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=30, context=self.ssl_context) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.expires = 0
            if error.code == 412:
                raise Conflict("Object generation changed") from None
            raise

    def _url(self, name):
        return (f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/"
                + urllib.parse.quote(name, safe=""))

    def get(self, name):
        try:
            return self._request(self._url(name) + "?alt=media")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def generation(self, name):
        try:
            return int(json.loads(self._request(self._url(name) + "?fields=generation"))["generation"])
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return 0
            raise

    def put(self, name, data, content_type="application/json", generation=None):
        parameters = {"uploadType": "media", "name": name}
        if generation is not None:
            parameters["ifGenerationMatch"] = str(generation)
        url = (f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?"
               + urllib.parse.urlencode(parameters))
        self._request(url, data, {"Content-Type": content_type})

    def list_names(self, prefix):
        token = None
        while True:
            parameters = {"prefix": prefix, "fields": "items/name,nextPageToken", "maxResults": 1000}
            if token:
                parameters["pageToken"] = token
            url = (f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o?"
                   + urllib.parse.urlencode(parameters))
            page = json.loads(self._request(url))
            for item in page.get("items", []):
                yield item["name"]
            token = page.get("nextPageToken")
            if not token:
                return


def immutable_put(store, name, data, content_type="application/json", attempts=3, sleep=time.sleep):
    """Create only; resolve an ambiguous HTTP result by comparing actual bytes."""
    last_error = None
    for attempt in range(attempts):
        try:
            store.put(name, data, content_type, generation=0)
            return
        except (OSError, Conflict) as error:
            last_error = error
            try:
                existing = store.get(name)
            except OSError as read_error:
                last_error = read_error
                existing = None
            if existing is not None:
                if existing != data:
                    raise IntegrityError("Immutable remote object has different bytes") from None
                return
            if attempt + 1 < attempts:
                sleep(min(2 ** attempt, 5))
    raise last_error


@contextlib.contextmanager
def exclusive_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


class Publisher:
    def __init__(self, task_root, store, prefix, manifest, task_index, task_count, sleep=time.sleep, upload_workers=8):
        self.root = Path(task_root)
        self.results = self.root / "results"
        self.results.mkdir(parents=True, exist_ok=True)
        self.store, self.prefix = store, prefix.rstrip("/")
        self.manifest = manifest
        self.identity = {field: manifest[field] for field in IDENTITY_FIELDS}
        if not all(isinstance(value, str) and value for value in self.identity.values()):
            raise IntegrityError("Manifest identity fields must be nonempty strings")
        if not all(re.fullmatch(r"[0-9a-f]{64}", self.identity[field])
                   for field in ("source_sha256", "config_sha256")):
            raise IntegrityError("Manifest hashes must be lowercase SHA-256")
        if not 0 <= task_index < task_count:
            raise IntegrityError("Invalid shard identity")
        self.index, self.count, self.sleep = task_index, task_count, sleep
        if upload_workers < 1:
            raise IntegrityError("Upload worker count must be positive")
        self.upload_workers = upload_workers
        self.checkpoint_prefix = self.prefix + f"/checkpoints/tasks/{task_index:05d}/"
        self.live_prefix = self.prefix + f"/live/tasks/{task_index:05d}"
        self.records = {}
        self.artifact_hashes = {}
        self.manifest_ready = False

    def ensure_manifest(self):
        if not self.manifest_ready:
            immutable_put(self.store, self.prefix + "/manifest.json", encoded(self.manifest), sleep=self.sleep)
            self.manifest_ready = True

    def _check_identity(self, value):
        if not isinstance(value, dict) or any(value.get(field) != expected for field, expected in self.identity.items()):
            raise IntegrityError("Checkpoint belongs to a different run, source or configuration")

    def _check_record(self, record, trial_id, mat_data):
        self._check_identity(record)
        if record.get("trial_id") != trial_id or trial_id < 1 or (trial_id - 1) % self.count != self.index:
            raise IntegrityError("Checkpoint trial is invalid or assigned to another shard")
        if record.get("status") not in OUTCOMES or record.get("completed") is not True:
            raise IntegrityError("Checkpoint outcome is invalid or incomplete")
        if record.get("sha256") != sha256(mat_data):
            raise IntegrityError("Checkpoint MAT checksum disagrees with its sidecar")

    def _commit(self, trial_id, mat_data, json_data):
        return dict(schema_version=1, trial_id=trial_id, task_index=self.index,
                    task_count=self.count, sha256=sha256(mat_data),
                    sidecar_sha256=sha256(json_data), **self.identity)

    def _ack(self, commit):
        ack = {key: commit[key] for key in (*IDENTITY_FIELDS, "trial_id", "sha256")}
        atomic_json(self.results / "acks" / f"trial_{commit['trial_id']:012d}.json", ack)

    def _object_names(self, commit):
        if any(not isinstance(commit.get(field), str) or not re.fullmatch(r"[0-9a-f]{64}", commit[field])
               for field in ("sha256", "sidecar_sha256")):
            raise IntegrityError("Commit contains invalid checkpoint hashes")
        base = self.checkpoint_prefix + f"objects/trial_{commit['trial_id']:012d}."
        return base + commit["sha256"] + ".mat", base + commit["sidecar_sha256"] + ".json"

    def publish_trial(self, path):
        match = TRIAL_NAME.fullmatch(path.name)
        if not match:
            raise IntegrityError("Invalid checkpoint filename")
        trial_id = int(match[1])
        if trial_id in self.records:
            return
        json_data = path.read_bytes()
        mat_data = path.with_suffix(".mat").read_bytes()
        record = json.loads(json_data)
        self._check_record(record, trial_id, mat_data)
        commit = self._commit(trial_id, mat_data, json_data)
        remote_base = self.checkpoint_prefix + path.stem
        previous = self.store.get(remote_base + ".commit.json")
        if previous is not None:
            if previous != encoded(commit):
                raise IntegrityError("Committed trial disagrees with the local checkpoint")
        else:
            # A VM can die after only one upload. Content-addressed data objects
            # allow the retry to recompute a trial without colliding with an
            # orphan whose MAT header or observation time differs. Only the
            # fixed per-trial commit decides which complete result is durable.
            mat_name, json_name = self._object_names(commit)
            immutable_put(self.store, mat_name, mat_data, "application/octet-stream", sleep=self.sleep)
            immutable_put(self.store, json_name, json_data, sleep=self.sleep)
            immutable_put(self.store, remote_base + ".commit.json", encoded(commit), sleep=self.sleep)
        # There is deliberately no local/remote completion increment before this.
        self._ack(commit)
        self.records[trial_id] = record

    def restore(self):
        self.ensure_manifest()
        restored = 0
        for name in sorted(self.store.list_names(self.checkpoint_prefix)):
            filename = name.removeprefix(self.checkpoint_prefix)
            match = COMMIT_NAME.fullmatch(filename)
            if not match:
                continue
            trial_id = int(match[1])
            commit_data = self.store.get(name)
            if commit_data is None:
                raise IntegrityError("Listed commit is missing")
            commit = json.loads(commit_data)
            self._check_identity(commit)
            if (commit.get("trial_id"), commit.get("task_index"), commit.get("task_count")) != (trial_id, self.index, self.count):
                raise IntegrityError("Remote checkpoint shard identity disagrees")
            mat_name, json_name = self._object_names(commit)
            mat_data, json_data = self.store.get(mat_name), self.store.get(json_name)
            if mat_data is None or json_data is None:
                raise IntegrityError("Committed checkpoint data is missing")
            if commit != self._commit(trial_id, mat_data, json_data):
                raise IntegrityError("Remote checkpoint checksums disagree")
            record = json.loads(json_data)
            self._check_record(record, trial_id, mat_data)
            local_base = self.results / "checkpoints" / f"trial_{trial_id:012d}"
            atomic_bytes(local_base.with_suffix(".mat"), mat_data)
            atomic_bytes(local_base.with_suffix(".json"), json_data)
            self._ack(commit)
            self.records[trial_id] = record
            restored += 1
        (self.results / "_uploader.stop").unlink(missing_ok=True)
        (self.results / "UPLOAD_FAILED.json").unlink(missing_ok=True)
        return restored

    def upload_artifacts(self):
        candidates = set()
        for directory in (self.results, self.root / "logs"):
            if directory.is_dir():
                for path in directory.rglob("*"):
                    worker_json = path.suffix.lower() == ".json" and path.parent.name == "workers"
                    if path.is_file() and (worker_json or path.suffix.lower() in {".mat", ".csv", ".log", ".txt", ".out", ".err"}):
                        relative = path.relative_to(self.root)
                        if any(part in {"checkpoints", "acks"} for part in relative.parts):
                            continue
                        candidates.add(path)
        candidates.update(self.root.glob("*.log"))
        errors = []
        root_resolved = self.root.resolve()
        for path in sorted(candidates):
            try:
                if not path.resolve().is_relative_to(root_resolved):
                    continue
                data = path.read_bytes()
                digest = sha256(data)
                relative = path.relative_to(self.root).as_posix()
                if self.artifact_hashes.get(relative) == digest:
                    continue
                self.store.put(self.prefix + f"/artifacts/tasks/{self.index:05d}/" + relative,
                               data, "application/octet-stream")
                self.artifact_hashes[relative] = digest
            except OSError as error:
                errors.append(error)
        return errors

    def worker_snapshots(self, final=False):
        attempts = []
        current = dt.datetime.now(dt.timezone.utc)
        for directory in (self.results / "live").glob("*/workers"):
            workers = []
            for path in directory.glob("worker_*.json"):
                try:
                    worker = read_json(path)
                    if not isinstance(worker, dict) or not isinstance(worker.get("updated_at"), str):
                        continue
                    age = max(0, (current - dt.datetime.fromisoformat(worker["updated_at"].replace("Z", "+00:00"))).total_seconds())
                    worker["activity_age_seconds"] = age
                    worker["stale"] = bool(worker.get("active")) and age > 120
                    worker["attempt_id"] = directory.parent.name
                    if final:
                        worker["interrupted"] = bool(worker.get("active"))
                        worker["active"] = False
                        worker["stale"] = False
                    workers.append(worker)
                except (OSError, ValueError, TypeError):
                    # Objective-call telemetry is advisory and must never block
                    # acknowledgment of an already durable scientific result.
                    continue
            if workers:
                attempts.append(workers)
        return max(attempts, key=lambda workers: max(w["updated_at"] for w in workers), default=[])

    def snapshot(self, final=False, errors=(), include_workers=True):
        state = read_json(self.results / "state.json", {})
        if state:
            self._check_identity(state)
            if (state.get("task_index"), state.get("task_count")) != (self.index, self.count):
                raise IntegrityError("MATLAB and uploader shard identities disagree")
        # MATLAB's total_trials is this shard's assigned total.
        assigned = state.get("total_trials")
        status = state.get("status", "waiting_for_matlab")
        if final and status not in {"completed", "failed", "stopped"}:
            status = "incomplete"
        if status == "completed" and (assigned is None or len(self.records) != assigned):
            status = "incomplete"
        if errors and status == "completed":
            status = "incomplete"
        latest = max(self.records.values(), key=lambda record: (record.get("completed_at", ""), record["trial_id"]), default=None)
        counts = {outcome: sum(record["status"] == outcome for record in self.records.values()) for outcome in OUTCOMES}
        workers = self.worker_snapshots(final) if include_workers else []
        return dict(schema_version=1, **self.identity, task_index=self.index,
                    task_count=self.count, updated_at=now(), status=status,
                    finalized=final and not errors, assigned_trials=assigned,
                    global_total_trials=state.get("global_total_trials"),
                    completed_trials=len(self.records), published_trials=len(self.records),
                    succeeded_trials=counts["succeeded"], nonconverged_trials=counts["nonconverged"],
                    failed_trials=counts["failed"], pending_upload_errors=len(errors),
                    latest_trial=latest, checkpoint_prefix=self.checkpoint_prefix,
                    workers_per_task=state.get("workers", 0), active_ids=state.get("active_ids", []) if not final else [],
                    active_workers=sum(bool(worker.get("active")) for worker in workers),
                    stale_workers=sum(worker["stale"] for worker in workers), workers=workers,
                    failure_identifier=state.get("failure_identifier"),
                    failure_message=state.get("failure_message"))

    def aggregate(self):
        name = self.prefix + "/live/summary.json"
        for unused in range(3):
            generation = self.store.generation(name)
            snapshots = []
            for index in range(self.count):
                data = self.store.get(self.prefix + f"/live/tasks/{index:05d}/latest.json")
                if data is None:
                    continue
                snapshot = json.loads(data)
                self._check_identity(snapshot)
                if (snapshot.get("task_index"), snapshot.get("task_count")) != (index, self.count):
                    raise IntegrityError("Remote task metrics identity disagrees")
                snapshots.append(snapshot)
            complete_set = len(snapshots) == self.count
            totals_known = complete_set and all(s.get("assigned_trials") is not None for s in snapshots)
            total = sum(s["assigned_trials"] for s in snapshots) if totals_known else None
            global_totals = {s["global_total_trials"] for s in snapshots if s.get("global_total_trials") is not None}
            if len(global_totals) > 1:
                raise IntegrityError("Remote task metrics disagree on global sweep size")
            if global_totals:
                global_total = next(iter(global_totals))
                if total is not None and global_total != total:
                    raise IntegrityError("Assigned task totals disagree with global sweep size")
                total = global_total
            completed = sum(s["completed_trials"] for s in snapshots)
            all_done = complete_set and all(s["status"] == "completed" for s in snapshots)
            all_final = complete_set and all(s.get("finalized") for s in snapshots)
            latest = [s["latest_trial"] for s in snapshots if s.get("latest_trial")]
            summary = dict(schema_version=1, **self.identity, updated_at=now(),
                           task_count=self.count, reporting_tasks=len(snapshots),
                           status="completed" if all_done and completed == total else "incomplete" if all_final else "running",
                           completed_trials=completed, published_trials=completed,
                           total_trials=total, percent_complete=100 * completed / total if total else None,
                           succeeded_trials=sum(s["succeeded_trials"] for s in snapshots),
                           nonconverged_trials=sum(s["nonconverged_trials"] for s in snapshots),
                           failed_trials=sum(s["failed_trials"] for s in snapshots),
                           active_workers=sum(s.get("active_workers", 0) for s in snapshots),
                           stale_workers=sum(s.get("stale_workers", 0) for s in snapshots),
                           latest_trial=max(latest, key=lambda r: (r.get("completed_at", ""), r["trial_id"]), default=None),
                           tasks=snapshots)
            try:
                self.store.put(name, encoded(summary), generation=generation)
                return True
            except Conflict:
                continue
        # Each task already published its truthful counts. Another shard's CAS
        # won; a future cycle recomputes the advisory aggregate from all shards.
        return False

    def publish(self, final=False, report=True):
        self.ensure_manifest()
        errors = []
        paths = []
        for path in (self.results / "checkpoints").glob("trial_*.json"):
            match = TRIAL_NAME.fullmatch(path.name)
            if not match or int(match[1]) not in self.records:
                paths.append(path)
        if paths:
            with ThreadPoolExecutor(max_workers=self.upload_workers) as executor:
                futures = [executor.submit(self.publish_trial, path) for path in paths]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except (OSError, ValueError, IntegrityError, Conflict) as error:
                        errors.append(error)
        # Missing final full-run files never prevent partial exports or logs.
        if report or final or errors:
            errors.extend(self.upload_artifacts())
        fatal = next((error for error in errors if isinstance(error, IntegrityError)), None)
        if fatal:
            atomic_json(self.results / "UPLOAD_FAILED.json", dict(
                **self.identity, error=str(fatal), updated_at=now()))
        snapshot = self.snapshot(final, errors, include_workers=report or final or bool(errors))
        if report or final or errors:
            self.store.put(self.live_prefix + "/latest.json", encoded(snapshot))
            self.aggregate()
            atomic_json(self.results / "_uploader.published.json", snapshot)
        return snapshot, errors


def safe_error(error):
    if isinstance(error, IntegrityError):
        return str(error)
    if isinstance(error, urllib.error.HTTPError):
        return "HTTP " + str(error.code)
    return type(error).__name__


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("restore", "daemon", "finalize"))
    parser.add_argument("--task-root", required=True)
    parser.add_argument("--run-uri", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--task-index", type=int, required=True)
    parser.add_argument("--task-count", type=int, required=True)
    parser.add_argument("--interval", type=float, default=0.25)
    parser.add_argument("--report-interval", type=float, default=15)
    parser.add_argument("--upload-workers", type=int, default=8)
    parser.add_argument("--retry-seconds", type=float, default=180)
    args = parser.parse_args(argv)
    uri = urllib.parse.urlsplit(args.run_uri)
    if uri.scheme != "gs" or not uri.netloc or not uri.path.strip("/") or uri.query or uri.fragment:
        parser.error("Use a run-specific gs://bucket/prefix URI")
    if args.interval <= 0 or args.report_interval <= 0 or args.retry_seconds <= 0 or args.upload_workers < 1:
        parser.error("Intervals must be positive")
    try:
        publisher = Publisher(args.task_root, GcsStore(uri.netloc), uri.path.strip("/"),
                              read_json(args.manifest), args.task_index, args.task_count,
                              upload_workers=args.upload_workers)
    except (OSError, ValueError, TypeError, KeyError, IntegrityError) as error:
        print(json.dumps(dict(event="checkpoint-configuration-error", error=safe_error(error))), flush=True)
        return 2
    stop = publisher.results / "_uploader.stop"
    if args.command == "finalize":
        stop.touch()
    interrupted = False

    def request_stop(signum, frame):
        nonlocal interrupted
        interrupted = True

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    deadline = time.monotonic() + args.retry_seconds
    next_report = 0
    while True:
        if args.command == "daemon" and (stop.exists() or interrupted):
            return 0
        try:
            with exclusive_lock(publisher.results / "_uploader.lock"):
                if args.command == "daemon" and stop.exists():
                    return 0
                if args.command == "restore":
                    count = publisher.restore()
                    print(json.dumps(dict(event="checkpoint-restored", task_index=args.task_index, completed=count)), flush=True)
                    return 0
                report = time.monotonic() >= next_report
                snapshot, errors = publisher.publish(final=args.command == "finalize", report=report)
                if report:
                    next_report = time.monotonic() + args.report_interval
            if report or errors or args.command == "finalize":
                print(json.dumps(dict(event="checkpoint-progress", task_index=args.task_index,
                                      status=snapshot["status"], completed=snapshot["completed_trials"],
                                      pending_upload_errors=len(errors))), flush=True)
            if errors:
                for error in errors[:3]:
                    print(json.dumps(dict(event="checkpoint-upload-error", error=safe_error(error))), flush=True)
                fatal = next((error for error in errors if isinstance(error, IntegrityError)), None)
                if fatal and args.command != "daemon":
                    return 2
            elif args.command == "finalize":
                atomic_json(publisher.results / "_uploader.finalized.json", snapshot)
                return 0
        except IntegrityError as error:
            print(json.dumps(dict(event="checkpoint-integrity-error", error=safe_error(error))), flush=True)
            return 2
        except (OSError, ValueError, Conflict) as error:
            print(json.dumps(dict(event="checkpoint-retry", error=safe_error(error))), flush=True)
        if interrupted:
            return 1
        if args.command != "daemon" and time.monotonic() >= deadline:
            print(json.dumps(dict(event="checkpoint-retry-deadline", command=args.command)), flush=True)
            return 1
        # Short sleeps permit timely SIGTERM handling; a killed VM can lose only
        # its unacknowledged in-flight trials, which the next attempt reruns.
        end = time.monotonic() + args.interval
        while time.monotonic() < end and not interrupted:
            time.sleep(min(0.2, max(0, end - time.monotonic())))


if __name__ == "__main__":
    raise SystemExit(main())
