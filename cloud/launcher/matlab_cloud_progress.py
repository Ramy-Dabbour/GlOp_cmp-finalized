"""Read live progress; no submissions, synchronization, or bucket mutations."""
from __future__ import annotations

import datetime as dt
import json


def read_json_object(ctx, uri):
    from matlab_cloud import CloudError
    # cat writes object bytes itself; --format=json appends a printer footer.
    body = ctx.gcloud("storage", "cat", uri, "--format=none", _raw_output=True)
    try:
        snapshot = json.loads(body)
    except (TypeError, ValueError) as error:
        raise CloudError(f"Invalid live JSON object at {uri}") from error
    if not isinstance(snapshot, dict):
        raise CloudError(f"Expected a live JSON object at {uri}")
    return snapshot


def read_progress(ctx, project, job):
    from matlab_cloud import CommandError, CloudError, job_id
    ident = job_id(job)
    if job.get("labels", {}).get("matlab_cloud_live") != "true":
        raise CloudError(f"{ident} was submitted without live reporting. Existing jobs retain their source and configuration; use Batch logs for this job.")
    uri = f"gs://{project.bucket}/outputs/{ident}/live/summary.json"
    try:
        snapshot = read_json_object(ctx, uri)
    except CommandError as error:
        message = (error.stdout + error.stderr).lower()
        if any(text in message for text in ("matched no objects", "no urls matched", "404")) and not any(text in message for text in ("401", "403", "denied")):
            if job.get("uid"):
                failures = ctx.gcloud("logging", "read", f'labels.job_uid={json.dumps(job["uid"])} AND jsonPayload.event="live-publish-error"', "--limit=1", json_output=True)
                if failures:
                    event = failures[0]
                    ctx.log(f"{ident}: live uploader error at {event.get('timestamp','unknown time')}: {event['jsonPayload'].get('error','unknown error')}. Check publish-live-trials logs; uploads retry automatically.")
                    return None
            ctx.log(f"{ident}: no live report yet. Batch state: {job.get('status', {}).get('state', 'UNKNOWN')}; the VM or source preparation may still be starting.")
            return None
        raise
    if snapshot.get("job_id") != ident:
        raise CloudError("Live summary belongs to a different job.")
    return snapshot


def print_progress(ctx, project, job, snapshot, detailed=True):
    from matlab_cloud import job_id, job_state
    ident = job_id(job)
    total = snapshot["total_trials"]
    percent = snapshot["percent_complete"]
    percentage = f" ({percent:.2f}%)" if percent is not None else ""
    age = max(0, (dt.datetime.now(dt.timezone.utc)-dt.datetime.fromisoformat(snapshot["updated_at"].replace("Z", "+00:00"))).total_seconds())
    ctx.log(f"{project.name} | {ident} | Batch {job_state(job)} | {snapshot['status']} | completed {snapshot['completed_trials']}/{total if total is not None else '?'}{percentage} | succeeded {snapshot['succeeded_trials']}, nonconverged {snapshot['nonconverged_trials']}, failed {snapshot['failed_trials']} | active workers {snapshot['active_workers']}, stale {snapshot['stale_workers']} | report age {age:.0f}s")
    if detailed:
        for task in snapshot["tasks"]:
            ctx.log(f"  Task {task['task_index']:05d}: {task['status']}, {task['completed_trials']}/{task['assigned_trials']} complete, {task['active_workers']} active workers, {task['stale_workers']} stale; last completion {task['latest_completion_at'] or 'none yet'}")
        latest = snapshot.get("latest_trial")
        if latest:
            ctx.log(f"  Latest trial {latest['global_trial_id']}: {latest['status']}; parameters [FIR order, passband, seed, reference solver, MZI solver, sample] = {latest['parameters']}; elapsed {latest['elapsed_seconds']:.2f}s; end-to-end error {latest['end_to_end_error']}")
        ctx.log(f"  Live files: gs://{project.bucket}/outputs/{ident}/live/")
        if age > 120 and job_state(job) not in {"SUCCEEDED", "FAILED", "DELETION_IN_PROGRESS"}:
            ctx.log("  The live report is stale. Check the publish-live-trials runnable in Batch logs for upload or VM errors.")


def show_progress(workflow, target):
    from matlab_cloud import CloudError, job_id, list_jobs, resolve_project
    with workflow.operation_lock:
        jobs = list_jobs(workflow.ctx)
        matching = [job for job in jobs if job_id(job) == target]
        if matching:
            job = matching[0]
            project = next((p for p in workflow.projects if p.key == job.get("labels", {}).get("matlab_project")), None)
            if project is None:
                raise CloudError("Job does not belong to a configured desktop project.")
        else:
            project = resolve_project(workflow.projects, target)
            matching = [job for job in jobs if job.get("labels", {}).get("matlab_project") == project.key]
            if not matching:
                raise CloudError(f"No Batch jobs found for {project.name}.")
            job = max(matching, key=lambda item: item.get("createTime", ""))
        snapshot = read_progress(workflow.ctx, project, job)
        if snapshot:
            print_progress(workflow.ctx, project, job, snapshot)
            from concurrent.futures import ThreadPoolExecutor
            prefix = f"gs://{project.bucket}/outputs/{job_id(job)}/live/tasks"
            def read_task(task):
                return read_json_object(workflow.ctx, prefix+f"/{task['task_index']:05d}/latest.json")
            with ThreadPoolExecutor(max_workers=min(4, len(snapshot["tasks"]) or 1)) as executor:
                details = list(executor.map(read_task, snapshot["tasks"]))
            for task in details:
                for worker in task["workers"]:
                    if worker["active"]:
                        workflow.ctx.log(f"  Task {task['task_index']:05d} worker {worker['worker_pid']}: trial {worker['global_trial_id']}, {worker['stage']} stage, {worker['objective_evaluations']} objective calls; last activity {worker['activity_age_seconds']:.0f}s ago" + (" [STALE]" if worker["stale"] else ""))
        return snapshot
