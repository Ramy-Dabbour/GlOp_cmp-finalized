"""Quota sizing and verified collection for one MATLAB pool per Batch VM."""
from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path
import re
import subprocess
import uuid


def resolve_layout(ctx, project):
    """Return a run-specific configuration; keep the user's auto settings intact."""
    if project.config.get("batch_mode") != "trial_shards":
        return project
    from matlab_cloud import CloudError, write_json
    from matlab_cloud_run import _positive_int
    config = dict(project.config)
    if config.get("task_count_per_node", 1) != 1:
        raise CloudError("trial_shards requires one task per VM.")
    workers = _positive_int(config.get("workers_per_task"), "workers_per_task", 512)
    if config.get("cpu_milli") != workers * 1000:
        raise CloudError("cpu_milli must allocate one vCPU per MATLAB worker.")
    region = ctx.gcloud("compute", "regions", "describe", ctx.region, json_output=True)
    global_info = ctx.gcloud("compute", "project-info", "describe", json_output=True)
    zones = ctx.gcloud("compute", "zones", "list", "--filter=region:" + ctx.region,
                       json_output=True)
    matching = sorted(zone["name"] for zone in zones
                      if zone.get("region", "").rsplit("/", 1)[-1] == ctx.region
                      and zone.get("status") == "UP")
    if not matching:
        raise CloudError("No available zone found in the configured Batch region.")
    machine = ctx.gcloud("compute", "machine-types", "describe", config["machine_type"],
                         "--zone=" + matching[0], json_output=True)
    if machine.get("guestCpus") != workers:
        raise CloudError("workers_per_task must equal the selected VM's vCPU count.")
    if config.get("memory_mib", 30000) > machine.get("memoryMb", 0):
        raise CloudError("Task memory exceeds the selected VM's memory.")
    regional = {q["metric"]: q for q in region.get("quotas", [])}
    worldwide = {q["metric"]: q for q in global_info.get("quotas", [])}
    limits = []

    def capacity(quotas, metric, per_vm, required=True):
        quota = quotas.get(metric)
        if quota is None:
            if required:
                raise CloudError("Cannot size concurrency: quota " + metric + " is missing.")
            return
        free = max(0, float(quota["limit"]) - float(quota["usage"]))
        limits.append({"metric": metric, "limit": quota["limit"],
                       "usage": quota["usage"], "per_vm": per_vm,
                       "available_vms": math.floor(free / per_vm)})

    family = config["machine_type"].split("-", 1)[0].upper()
    if family not in {"E2", "N1", "N2", "N2D", "C2", "C2D", "N2A", "T2D", "T2A", "C3"}:
        raise CloudError("Quota sizing for this VM family is not implemented.")
    if family in {"E2", "N1"}:
        # E2 and N1 consume CPUS, per Google's machine-series quota table.
        capacity(regional, "CPUS", workers)
    else:
        capacity(regional, family + "_CPUS", workers)
    capacity(worldwide, "CPUS_ALL_REGIONS", workers)
    capacity(regional, "INSTANCES", 1)
    capacity(regional, "SSD_TOTAL_GB", config.get("boot_disk_gb", 100))
    # The default Batch network gives each VM an external IP.
    capacity(regional, "IN_USE_ADDRESSES", 1)
    available = min(4000, *(item["available_vms"] for item in limits))
    requested = config.get("task_count", "auto")
    if requested == "auto":
        count = available
    else:
        count = _positive_int(requested, "task_count", 4000)
        if count > available:
            raise CloudError(f"Requested {count} concurrent VMs; quotas permit {available}. "
                             "Use task_count=auto or release/increase the limiting quota.")
    if count < 1:
        raise CloudError("No quota remains for a complete MATLAB VM. "
                         "Release resources or increase quota before submitting.")
    parallelism = config.get("parallelism", "auto")
    if parallelism != "auto" and parallelism != count:
        raise CloudError("parallelism must equal task_count; this project does not queue extra tasks.")
    config.update(task_count=count, parallelism=count, task_count_per_node=1)
    write_json(ctx.run_dir / (project.key + "-quota-plan.json"),
               {"task_count": count, "parallelism": count, "workers_per_task": workers,
                "total_workers": count * workers, "quotas": limits})
    ctx.log(f"Quota-sized run: {count} tasks on {count} VMs, {workers} MATLAB workers per VM "
            f"({count * workers} workers total). No extra queued tasks.")
    for item in limits:
        ctx.log(f"  {item['metric']}: {item['usage']}/{item['limit']} used; "
                f"room for {item['available_vms']} VMs.")
    return replace(project, config=config)


def collect_trial_results(ctx, project, job, snapshot):
    """Validate every transfer and merge with the exact source from the run."""
    from matlab_cloud import CloudError, hash_file, read_json, write_json
    ident = job["name"].rsplit("/", 1)[-1]
    count_text = job.get("labels", {}).get("matlab_cloud_tasks", "")
    if not re.fullmatch(r"[1-9][0-9]*", count_text) or int(count_text) > 4000:
        raise CloudError("Distributed job is missing its validated task-count label.")
    count = int(count_text)
    if ctx.dry_run:
        ctx.log(f"[Preview] Would verify {count} task transfers and merge {ident}.")
        return None
    snapshot = Path(snapshot)
    if job.get("status", {}).get("state") != "SUCCEEDED":
        raise CloudError(f"{ident} did not succeed; recovered shards are partial and will not be merged.")
    shards = sorted((snapshot / "results").glob("trial_shard_*.mat"))
    expected = {f"trial_shard_{index:05d}.mat" for index in range(count)}
    if {path.name for path in shards} != expected:
        raise CloudError(f"{ident}: incomplete or unexpected shard set; expected {count} files.")
    workers = job.get("labels", {}).get("matlab_cloud_workers")
    for index in range(count):
        marker = read_json(snapshot / "tasks" / f"{index:05d}" / "_TRANSFER_COMPLETE.json")
        if (marker.get("schema_version") != 2 or marker.get("job_id") != ident
                or marker.get("task_index") != index or marker.get("task_count") != count
                or marker.get("workers_per_task") != int(workers or 0)):
            raise CloudError(f"{ident}: incompatible transfer marker for task {index}.")
        shard = snapshot / "results" / f"trial_shard_{index:05d}.mat"
        if marker.get("shard_sha256") != hash_file(shard).hex():
            raise CloudError(f"{ident}: task {index} shard checksum disagrees with its marker.")
    source = snapshot / "workspace"
    if not (source / "+fpf" / "mergeBatchResults.m").is_file():
        raise CloudError("The run's merge implementation was not preserved by task zero.")
    download_record = read_json(snapshot / ".matlab-cloud-download.json")
    digest = download_record["inventory_sha256"]
    aggregate = snapshot.parent / ("aggregate-" + snapshot.name.removeprefix("snapshot-"))
    manifest_path = aggregate / "_MERGE_COMPLETE.json"
    if manifest_path.exists():
        manifest = read_json(manifest_path)
        if (manifest.get("inventory_sha256") == digest
                and all((aggregate / name).is_file()
                        and hash_file(aggregate / name).hex() == manifest.get("sha256", {}).get(name)
                        for name in ("benchmark_results.mat", "benchmark_results.csv"))):
            ctx.log(f"{ident}: aggregate already merged and checksums verified: {aggregate}")
            return aggregate
        ctx.log("Previous aggregate changed; preserving it and creating a fresh merge.")
    if aggregate.exists():
        aggregate = aggregate.with_name(aggregate.name + "-retry-" + uuid.uuid4().hex[:8])
        manifest_path = aggregate / "_MERGE_COMPLETE.json"
    aggregate.mkdir(parents=True, exist_ok=False)
    executable = project.config.get("local_matlab_executable", ctx.settings.get("local_matlab_executable", ""))
    if not executable or not Path(executable).is_file():
        raise CloudError("Set local_matlab_executable to merge the downloaded shards automatically.")
    literal = lambda path: str(path.resolve()).replace("\\", "/").replace("'", "''")
    statement = (f"cd('{literal(source)}'); "
                 f"fpf.mergeBatchResults('{literal(snapshot / 'results')}',"
                 f"'{literal(aggregate / 'benchmark_results.mat')}');")
    ctx.log(f"{ident}: merging {count} shards with MATLAB; results: {aggregate}")
    with (aggregate / "merge-console.log").open("w", encoding="utf-8") as log:
        result = subprocess.run([str(executable), "-wait", "-noFigureWindows", "-batch", statement],
                                stdout=log, stderr=subprocess.STDOUT, shell=False)
    outputs = ("benchmark_results.mat", "benchmark_results.csv")
    if result.returncode or not all((aggregate / name).is_file() for name in outputs):
        raise CloudError(f"MATLAB shard merge failed. See {aggregate / 'merge-console.log'}.")
    write_json(manifest_path, {"job_id": ident, "task_count": count,
                              "inventory_sha256": digest,
                              "sha256": {name: hash_file(aggregate / name).hex() for name in outputs}})
    ctx.log(f"{ident}: complete benchmark MAT/CSV verified in {aggregate}.")
    return aggregate
