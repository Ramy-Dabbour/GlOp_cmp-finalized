"""Publish completed MATLAB trials while Batch is running (stdlib only).

MATLAB atomically creates one JSON record per completed global trial ID. This
separate process batches those records into immutable gzip JSONL objects, then
publishes counts, worker activity, and the latest complete result. A local ledger
and a pending chunk survive uploader restarts and ambiguous upload responses.
The final collector takes the same flock and drains the spool before final MAT
files or transfer markers are published. VM credentials stay in memory.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def read_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(encoded(value))
    os.replace(temporary, path)


class Conflict(Exception):
    pass


class GcsStore:
    """Small-object JSON API client using the VM's attached service account."""
    def __init__(self, bucket):
        self.bucket = urllib.parse.quote(bucket, safe="")
        self.token = ""
        self.expires = 0

    def _request(self, url, data=None, headers=None):
        if time.monotonic() >= self.expires:
            request = urllib.request.Request(
                "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
                headers={"Metadata-Flavor": "Google"})
            with urllib.request.urlopen(request, timeout=10) as response:
                credentials = json.load(response)
            self.token = credentials["access_token"]
            self.expires = time.monotonic() + max(1, credentials["expires_in"]-60)
        request = urllib.request.Request(url, data=data, headers={
            "Authorization": "Bearer " + self.token, **(headers or {})})
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code == 401:
                self.expires = 0
            if error.code == 412:
                raise Conflict("Object generation changed") from None
            raise

    def get(self, name):
        url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/" + urllib.parse.quote(name, safe="")
        try:
            return self._request(url + "?alt=media")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return None
            raise

    def generation(self, name):
        url = f"https://storage.googleapis.com/storage/v1/b/{self.bucket}/o/" + urllib.parse.quote(name, safe="")
        try:
            return int(json.loads(self._request(url + "?fields=generation"))["generation"])
        except urllib.error.HTTPError as error:
            if error.code == 404:
                return 0
            raise

    def put(self, name, data, content_type="application/json", generation=None):
        parameters = {"uploadType": "media", "name": name}
        if generation is not None:
            parameters["ifGenerationMatch"] = str(generation)
        url = f"https://storage.googleapis.com/upload/storage/v1/b/{self.bucket}/o?" + urllib.parse.urlencode(parameters)
        self._request(url, data, {"Content-Type": content_type})


@contextlib.contextmanager
def exclusive_lock(path):
    # Runtime is Linux. Import here so offline Windows tests use a fake lock.
    import fcntl
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
        fcntl.flock(handle, fcntl.LOCK_UN)


def aggregate(snapshots, job_id, task_count):
    known = [snapshot for snapshot in snapshots if snapshot is not None]
    totals = {snapshot["total_trials"] for snapshot in known if snapshot.get("total_trials") is not None}
    if len(totals) > 1:
        raise RuntimeError("Tasks disagree on the sweep size")
    total = next(iter(totals), None)
    completed = sum(snapshot["completed_trials"] for snapshot in known)
    terminal = len(known) == task_count and all(snapshot["status"] in {"completed", "failed", "incomplete"} for snapshot in known)
    status = "running"
    if terminal:
        status = "completed" if all(snapshot["status"] == "completed" for snapshot in known) and completed == total else "incomplete"
    latest = [snapshot["latest_trial"] for snapshot in known if snapshot.get("latest_trial")]
    rate = sum(snapshot["trials_per_second"] for snapshot in known)
    return dict(schema_version=1, job_id=job_id, updated_at=now(), status=status,
                task_count=task_count, reporting_tasks=len(known), total_trials=total,
                completed_trials=completed, published_trials=sum(s["published_trials"] for s in known),
                percent_complete=100*completed/total if total else None,
                succeeded_trials=sum(s["succeeded_trials"] for s in known),
                nonconverged_trials=sum(s["nonconverged_trials"] for s in known),
                failed_trials=sum(s["failed_trials"] for s in known),
                active_workers=sum(s["active_workers"] for s in known),
                stale_workers=sum(s["stale_workers"] for s in known),
                trials_per_second=rate,
                estimated_remaining_seconds=max(0,total-completed)/rate if rate and total is not None else None,
                latest_trial=max(latest, key=lambda r: r["completed_at"], default=None),
                tasks=[dict(task_index=s["task_index"],status=s["status"],
                            completed_trials=s["completed_trials"],assigned_trials=s["assigned_trials"],
                            updated_at=s["updated_at"],active_workers=s["active_workers"],
                            stale_workers=s["stale_workers"],latest_completion_at=s["latest_completion_at"])
                       for s in known])


class Publisher:
    def __init__(self, root, store, prefix, job_id, task_index, task_count, workers):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.store, self.prefix, self.job_id = store, prefix.rstrip("/"), job_id
        self.task_index, self.task_count, self.workers = task_index, task_count, workers
        self.task_prefix = self.prefix + f"/live/tasks/{task_index:05d}"
        self.ledger_path = self.root / "_publisher.json"
        self.ledger = read_json(self.ledger_path, dict(ids=[], succeeded=0, nonconverged=0,
                                                    failed=0, elapsed_sum=0, latest_trial=None))
        self.ids = set(self.ledger["ids"])

    def _commit(self, records):
        for record in records:
            index = record["global_trial_id"]
            if index in self.ids:
                continue
            self.ids.add(index)
            self.ledger[record["status"]] += 1
            self.ledger["elapsed_sum"] += record["elapsed_seconds"]
            previous = self.ledger["latest_trial"]
            if previous is None or record["completed_at"] > previous["completed_at"]:
                self.ledger["latest_trial"] = record
        self.ledger["ids"] = sorted(self.ids)
        atomic_json(self.ledger_path, self.ledger)

    def _pending(self):
        pending = self.root / "_pending.jsonl.gz"
        if not pending.exists():
            return
        data = pending.read_bytes()
        records = [json.loads(line) for line in gzip.decompress(data).splitlines()]
        name = self.task_prefix + "/trials/" + hashlib.sha256(data).hexdigest() + ".jsonl.gz"
        try:
            self.store.put(name, data, "application/gzip", generation=0)
        except Conflict:
            # An upload may have succeeded before its response was lost.
            if self.store.get(name) != data:
                raise RuntimeError("Immutable trial chunk disagrees with its SHA-256")
        self._commit(records)
        pending.unlink()

    def publish(self, final=False):
        state = read_json(self.root / "state.json", {})
        if state and (state["task_index"],state["task_count"]) != (self.task_index,self.task_count):
            raise RuntimeError("MATLAB and publisher disagree on task identity")
        self._pending()
        batch = []
        for path in sorted((self.root / "trials").glob("trial_*.json")):
            index = int(path.stem.removeprefix("trial_"))
            if index in self.ids:
                continue
            record = read_json(path)
            if record["global_trial_id"] != index or (index-1) % self.task_count != self.task_index or index < 1 or index > state.get("total_trials", 0):
                raise RuntimeError("Invalid or misassigned live trial ID")
            if record["status"] not in {"succeeded", "nonconverged", "failed"}:
                raise RuntimeError("Invalid trial outcome")
            batch.append(record)
            if len(batch) == 100:
                self._chunk(batch)
                batch = []
        if batch:
            self._chunk(batch)
        snapshot = self._snapshot(state, final)
        self.store.put(self.task_prefix + "/latest.json", encoded(snapshot))
        if snapshot["latest_trial"]:
            self.store.put(self.task_prefix + "/latest_trial.json", encoded(snapshot["latest_trial"]))
        self._aggregate()
        atomic_json(self.root / "_published.json", snapshot)
        return snapshot

    def _chunk(self, records):
        # mtime=0 gives deterministic bytes for retries after process restarts.
        data = gzip.compress(b"\n".join(encoded(record) for record in records)+b"\n", mtime=0)
        pending = self.root / "_pending.jsonl.gz"
        temporary = pending.with_suffix(".tmp")
        temporary.write_bytes(data)
        os.replace(temporary, pending)
        self._pending()

    def _snapshot(self, state, final):
        current = dt.datetime.now(dt.timezone.utc)
        status = state.get("status", "waiting_for_matlab")
        if final and status not in {"completed", "failed"}:
            status = "incomplete"
        assigned = state.get("assigned_trials")
        if status == "completed" and len(self.ids) != assigned:
            status = "incomplete"
        workers = [read_json(path) for path in (self.root / "workers").glob("worker_*.json")]
        for worker in workers:
            age = (current-dt.datetime.fromisoformat(worker["updated_at"].replace("Z", "+00:00"))).total_seconds()
            worker["activity_age_seconds"] = max(0, age)
            worker["stale"] = worker["active"] and age > 120
            if final:
                worker["interrupted"] = bool(worker["active"])
                worker["active"] = False
                worker["stale"] = False
        active = sum(worker["active"] for worker in workers) if not final else 0
        started = state.get("started_at")
        finished = state.get("finished_at")
        end = dt.datetime.fromisoformat(finished.replace("Z", "+00:00")) if finished else current
        elapsed = max(0, (end-dt.datetime.fromisoformat(started.replace("Z", "+00:00"))).total_seconds()) if started else 0
        rate = len(self.ids)/elapsed if elapsed else 0
        remaining = max(0, assigned-len(self.ids)) if assigned is not None else None
        return dict(schema_version=1, job_id=self.job_id, task_index=self.task_index,
                    task_count=self.task_count, workers_per_task=self.workers,
                    updated_at=now(), status=status, started_at=started,
                    assigned_trials=assigned, total_trials=state.get("total_trials"),
                    completed_trials=len(self.ids), published_trials=len(self.ids),
                    percent_complete=100*len(self.ids)/assigned if assigned else None,
                    succeeded_trials=self.ledger["succeeded"], nonconverged_trials=self.ledger["nonconverged"],
                    failed_trials=self.ledger["failed"], active_workers=active,
                    stale_workers=sum(worker["stale"] for worker in workers) if not final else 0,
                    workers=workers, elapsed_seconds=elapsed,
                    trials_per_second=rate, estimated_remaining_seconds=remaining/rate if rate and remaining is not None else None,
                    mean_trial_seconds=self.ledger["elapsed_sum"]/len(self.ids) if self.ids else None,
                    latest_completion_at=self.ledger["latest_trial"]["completed_at"] if self.ids else None,
                    latest_trial=self.ledger["latest_trial"],
                    failure_identifier=state.get("failure_identifier"), failure_message=state.get("failure_message"))

    def _aggregate(self):
        name = self.prefix + "/live/summary.json"
        for attempt in range(3):
            generation = self.store.generation(name)
            snapshots = []
            for index in range(self.task_count):
                data = self.store.get(self.prefix + f"/live/tasks/{index:05d}/latest.json")
                snapshot = json.loads(data) if data is not None else None
                if snapshot is not None and (snapshot["job_id"] != self.job_id or snapshot["task_index"] != index or snapshot["task_count"] != self.task_count):
                    raise RuntimeError("Invalid live task snapshot identity")
                snapshots.append(snapshot)
            try:
                self.store.put(name, encoded(aggregate(snapshots, self.job_id, self.task_count)), generation=generation)
                return
            except Conflict:
                continue
        raise RuntimeError("Concurrent summary updates; will retry")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--output-uri", required=True)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--workers", required=True, type=int)
    parser.add_argument("--interval", type=int, default=15)
    parser.add_argument("--final", action="store_true")
    arguments = parser.parse_args(argv)
    uri = urllib.parse.urlsplit(arguments.output_uri)
    if uri.scheme != "gs" or not uri.netloc or not uri.path.strip("/"):
        parser.error("Use a run-specific gs://bucket/outputs/job URI")
    index, count = int(os.environ["BATCH_TASK_INDEX"]), int(os.environ["BATCH_TASK_COUNT"])
    if not 0 <= index < count or arguments.interval < 1:
        parser.error("Invalid Batch identity or interval")
    root = Path(arguments.root)
    root.mkdir(parents=True, exist_ok=True)
    stop = root / "_STOP"
    if arguments.final:
        stop.touch()
    deadline = time.monotonic() + 180
    while True:
        try:
            with exclusive_lock(root / "_publisher.lock"):
                if stop.exists() and not arguments.final:
                    return
                publisher = Publisher(root, GcsStore(uri.netloc), uri.path.strip("/"), arguments.job_id, index, count, arguments.workers)
                snapshot = publisher.publish(final=arguments.final)
            print(json.dumps(dict(event="live-progress",task_index=index,
                                  status=snapshot["status"],completed=snapshot["completed_trials"],
                                  assigned=snapshot["assigned_trials"],active_workers=snapshot["active_workers"])), flush=True)
            if arguments.final:
                atomic_json(root / "_FLUSHED.json", dict(status=snapshot["status"],
                    completed_trials=snapshot["completed_trials"],published_at=now()))
                return
        except (OSError, ValueError, RuntimeError, Conflict) as error:
            print(json.dumps(dict(event="live-publish-error",task_index=index,error=str(error))), flush=True)
            if arguments.final and time.monotonic() >= deadline:
                raise
        # No credential material or objective-call records are printed.
        time.sleep(min(arguments.interval, 5) if arguments.final else arguments.interval)


if __name__ == "__main__":
    main()
