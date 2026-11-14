"""Generate one bounded Batch diagnostic; this script never submits it."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PATCHED_RUNNER = ROOT / "storage-fix" / "matlab_cloud_run.py"
spec = importlib.util.spec_from_file_location("storage_smoke_runner", PATCHED_RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

project = "strange-reducer-509621-e8"
bucket = project + "-matlab-glop-cmp"
job_id = "matlab-storage-smoke-" + dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d-%H%M%S")
source_uri = f"gs://{bucket}/runs/matlab-glop-cmp-20261005-201941-8ae913/source"
output_uri = f"gs://{bucket}/diagnostics/{job_id}"
helper = "gcr.io/google.com/cloudsdktool/google-cloud-cli@sha256:1d0be2098e132a30d023809835b7bf7ce94b68e2ac88d39feab1db6bb3677ecc"
matlab = f"us-central1-docker.pkg.dev/{project}/matlab-images/matlab-full@sha256:676bd795c0807bc1c337bbcd1f88406aea0b1122fdd54f1993c1f483d0e875b0"
volume = "/var/lib/google/matlab-cloud:/work/shared:rw"

probe = "\n".join([
    "import errno, json, pathlib, shutil",
    "old = pathlib.Path('/diagnostics/old')",
    "print('OLD_STORAGE ' + json.dumps(shutil.disk_usage(old)._asdict()), flush=True)",
    "probe = old / 'storage-smoke-probe.bin'",
    "try:",
    "    with probe.open('xb') as stream: stream.write(b'x' * 1048576)",
    "    print('OLD_1MIB_WRITE_SUCCEEDED', flush=True)",
    "except OSError as error:",
    "    if error.errno != errno.ENOSPC: raise",
    "    print('OLD_1MIB_WRITE_ENOSPC', flush=True)",
    "finally:",
    "    probe.unlink(missing_ok=True)",
])
prepare = runner._python_container(helper, probe + "\n" + runner._prepare_program(source_uri), volume)
prepare["volumes"].append("/mnt/disks/matlab-cloud-probe:/diagnostics/old:rw")

# Exercise the real project on two samples, without calling its full main sweep.
statement = " ".join([
    "cd('/work/shared/workspace');",
    "fprintf('STORAGE_SMOKE_MATLAB_STARTED %s\\n', version);",
    "config=fpf.benchmarkConfig(); config.firOrders=1; config.passbandRatios=0.3;",
    "config.randomSeeds=0; config.referenceSolvers=4; config.mziSolvers=4;",
    "config.N_tr=2; config.N_s=101;",
    "serial=fpf.runSweep(config,[1;2],0);",
    "parallel=fpf.runSweep(config,[1;2],2);",
    "pool=gcp('nocreate'); assert(~isempty(pool) && pool.NumWorkers==2);",
    "assert(isequaln(serial,parallel));",
    "probeRun=fpf.run(1,0.3,4,4,101,0,SaveArtifacts=false,Display='off',Verbose=false,CollectDiagnostics=false,ThrowOnFailure=false);",
    "assert(probeRun.completed && probeRun.failureIdentifier==\"\");",
    "smokePassed=true;",
    "save('/work/shared/results/storage_smoke.mat','smokePassed','config','serial','parallel','probeRun');",
    "fprintf('STORAGE_SMOKE_PASSED\\n');",
    "pool=gcp('nocreate'); if ~isempty(pool), delete(pool); end;",
])

job = {
    "taskGroups": [{
        "taskCount": "1", "parallelism": "1", "taskCountPerNode": "1",
        "taskSpec": {
            "runnables": [
                {"displayName": "prepare-source-and-probe", "timeout": "300s", "container": prepare},
                {"displayName": "matlab-two-trial-smoke", "timeout": "600s", "container": {
                    "imageUri": matlab, "entrypoint": "/usr/local/bin/matlab",
                    "commands": ["-singleCompThread", "-logfile", "/work/shared/logs/matlab-smoke.log",
                                 "-licmode", "onlinelicensing", "-batch", statement],
                    "volumes": [volume]}},
                {"displayName": "preserve-diagnostic-outputs", "alwaysRun": True, "timeout": "300s",
                 "container": runner._python_container(helper, runner._collect_program(output_uri,job_id),volume)},
            ],
            "computeResource": {"cpuMilli": "8000", "memoryMib": "30000"},
            "maxRetryCount": 0, "maxRunDuration": "1500s",
        },
    }],
    "allocationPolicy": {
        "instances": [{"policy": {
            "machineType": "e2-standard-8", "provisioningModel": "STANDARD",
            "bootDisk": {"type": "pd-balanced", "sizeGb": "100",
                         "image": "projects/batch-custom-image/global/images/batch-cos-stable-official-20260924-00-p01"},
        }}],
        "serviceAccount": {"email": "1064328294968-compute@developer.gserviceaccount.com"},
        "location": {"allowedLocations": ["regions/us-central1"]},
    },
    "labels": {"matlab_project": "glop-cmp", "purpose": "storage-diagnostic"},
    "logsPolicy": {"destination": "CLOUD_LOGGING"},
}
path = ROOT / f"{job_id}.json"
path.write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
(ROOT / "smoke-run.json").write_text(json.dumps({
    "job_id": job_id, "config": str(path), "output_uri": output_uri,
    "source_uri": source_uri, "project": project, "region": "us-central1",
}, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"job_id": job_id, "config": str(path), "output_uri": output_uri}))
