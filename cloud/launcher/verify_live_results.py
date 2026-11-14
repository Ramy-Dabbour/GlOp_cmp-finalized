"""Verify downloaded trial history and publication during cloud computation."""
import argparse
from collections import Counter
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def instant(value):
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def verify(snapshot, evidence):
    summary = read(snapshot/"live/summary.json")
    records = []
    chunks = list((snapshot/"live/tasks").glob("*/trials/*.jsonl.gz"))
    for path in chunks:
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != path.name.removesuffix(".jsonl.gz"):
            raise RuntimeError("Trial chunk content hash mismatch")
        records.extend(json.loads(line) for line in gzip.decompress(data).splitlines())
    total = summary["total_trials"]
    if sorted(record["global_trial_id"] for record in records) != list(range(1,total+1)):
        raise RuntimeError("Missing or duplicated live trial IDs")
    outcomes = Counter(record["status"] for record in records)
    for status,key in (("succeeded","succeeded_trials"),("nonconverged","nonconverged_trials"),("failed","failed_trials")):
        if outcomes[status] != summary[key]:
            raise RuntimeError("Outcome counts disagree with trial history")
    if summary["status"] != "completed" or summary["published_trials"] != total:
        raise RuntimeError("Final live summary is incomplete")
    for task in summary["tasks"]:
        marker = read(snapshot/"tasks"/f"{task['task_index']:05d}"/"_TRANSFER_COMPLETE.json")
        if marker.get("live_published_trials") != task["completed_trials"] or not marker.get("live_reporting"):
            raise RuntimeError("Transfer marker does not confirm the live result drain")
    events = read(evidence/"cloud-progress-events.json")
    partial = [event for event in events if 0 < event["jsonPayload"]["completed"] < total and event["jsonPayload"]["active_workers"] > 0]
    last_completed = max(instant(record["completed_at"]) for record in records)
    if not partial or not any(instant(event["timestamp"]) < last_completed for event in partial):
        raise RuntimeError("No verified publication while a MATLAB trial was still active")
    result = dict(job_id=summary["job_id"],total_trials=total,unique_trial_ids=len(records),
                  immutable_chunks=len(chunks),outcomes=dict(outcomes),
                  published_while_running=min(partial,key=lambda event:event["timestamp"]),
                  last_trial_completed_at=last_completed.isoformat(),snapshot=str(snapshot))
    (evidence/"live-history-verified.json").write_text(json.dumps(result,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("snapshot",type=Path)
    parser.add_argument("evidence",type=Path)
    arguments = parser.parse_args()
    verify(arguments.snapshot,arguments.evidence)
