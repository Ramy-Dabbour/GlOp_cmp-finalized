"""Inspect a production plan, or run a bounded two-VM integration fixture."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import time

import matlab_cloud as workflow
import matlab_cloud_run as runner
import matlab_cloud_trials as trials


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("preview", "smoke", "collect", "live-smoke", "live-collect"))
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[2]
    toolkit = Path("C:/Users/Dell/Documents/matlab-cloud-toolkit")
    settings = workflow.read_json(toolkit / "cloud-settings.json")
    live_mode = args.mode.startswith("live-")
    evidence = project_root / "cloud" / "diagnostics" / ("live-reporting" if live_mode else "pool-per-vcpu")
    ctx = workflow.Context("C:/Users/Dell/AppData/Local/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd",
                           evidence, settings, dry_run=args.mode == "preview")
    ctx.verify_environment()
    config = workflow.read_json(project_root / "matlab-cloud.json")
    project = workflow.Project(project_root,"GlOp_cmp",config["project_key"],config["bucket"],config)
    if args.mode == "preview":
        runner.run_project(ctx,project,True)
        return
    if args.mode in {"collect", "live-collect"}:
        submitted = workflow.read_json(evidence / "smoke-submitted.json")
        ident = submitted["job_id"]
        project = workflow.Project(project_root,"live-smoke" if live_mode else "pool-smoke",
                                   "glop-live-smoke" if live_mode else "glop-pool-smoke",project.bucket,config)
        job = ctx.gcloud("batch","jobs","describe",ident,"--location="+ctx.region,json_output=True)
        active, failures = workflow.collect_outputs(ctx,[project],[job],include_historical=False)
        if failures or active:
            raise workflow.CloudError("; ".join(failures) or "Smoke job remained active.")
        workflow.write_json(evidence / "smoke-verified.json",dict(job_id=ident,state=workflow.job_state(job),run_dir=str(ctx.run_dir)))
        ctx.log("One-VM live-reporting fixture collected and merged." if live_mode else "Two-VM execution, eight workers per VM, shard transfer and automatic merge verified.")
        return
    fixture = ctx.run_dir / "fixture"
    fixture.mkdir()
    shutil.copytree(project_root / "+fpf",fixture / "+fpf")
    shutil.copy2(project_root / "tests" / "parallelSweepTest.m",fixture / "parallelSweepTest.m")
    (fixture/"cloud").mkdir()
    shutil.copy2(project_root/"cloud/live_reporter.py",fixture/"cloud/live_reporter.py")
    script = (project_root / "main.m").read_text(encoding="utf-8-sig")
    script = script.replace("config = fpf.benchmarkConfig();", """config = fpf.benchmarkConfig();
config.firOrders = 4;
config.passbandRatios = 0.2;
config.randomSeeds = 0;
config.referenceSolvers = 4;
config.mziSolvers = 4;
config.N_tr = 16;
config.N_s = 101;""")
    trial = "liveSmokeTrial" if live_mode else "parallelSweepTest.seededTrial"
    script = script.replace("fpf.runSweep(config,workIndices,workerCount,LiveDirectory=liveDirectory);",
                            f"fpf.runSweep(config,workIndices,workerCount,RunTrial=@{trial},LiveDirectory=liveDirectory);")
    if live_mode:
        (fixture/"liveSmokeTrial.m").write_text('''function result = liveSmokeTrial(varargin)
    parser = inputParser;
    parser.KeepUnmatched = true;
    addParameter(parser,'TrialIndex',1);
    parse(parser,varargin{7:end});
    reporter = fpf.currentReporter();
    reporter.stage("fixture");
    seconds = 2;
    if parser.Results.TrialIndex == 16
        seconds = 60;
    end
    for index = 1:seconds
        pause(1);
        reporter.evaluated(1/index);
    end
    result = parallelSweepTest.seededTrial(varargin{:});
end
''',encoding="utf-8")
    (fixture / "main.m").write_text(script,encoding="utf-8")
    config.update(task_count=1 if live_mode else 2,parallelism=1 if live_mode else 2,max_run_seconds=600)
    # Reuse the already-authorized bucket and prepared image, with a unique run.
    project = workflow.Project(fixture,"live-smoke" if live_mode else "pool-smoke",
                               "glop-live-smoke" if live_mode else "glop-pool-smoke",project.bucket,config)
    ident = runner.run_project(ctx,project,False)
    workflow.write_json(evidence / "smoke-submitted.json",dict(job_id=ident,run_dir=str(ctx.run_dir)))
    observed_live = False
    deadline = time.monotonic()+1200
    while True:
        job = ctx.gcloud("batch","jobs","describe",ident,"--location="+ctx.region,json_output=True)
        state = workflow.job_state(job)
        ctx.log(f"Smoke job {ident}: {state}")
        if live_mode and state == "RUNNING":
            from matlab_cloud_progress import read_progress, print_progress
            snapshot = read_progress(ctx,project,job)
            if snapshot:
                print_progress(ctx,project,job,snapshot,detailed=False)
                if 0 < snapshot["completed_trials"] < 16:
                    # Prove the full record is already in an uploaded chunk.
                    import gzip
                    records = workflow.list_objects(ctx,f"gs://{project.bucket}/outputs/{ident}/live/tasks/00000/trials")
                    if not records:
                        raise workflow.CloudError("Counts appeared before trial chunks")
                    downloaded = ctx.run_dir/"live-chunk.jsonl.gz"
                    uri=f"gs://{project.bucket}/{records[0]['name']}#{records[0]['generation']}"
                    ctx.gcloud("storage","cp",uri,str(downloaded))
                    trials_in_chunk=[json.loads(line) for line in gzip.decompress(downloaded.read_bytes()).splitlines()]
                    if not trials_in_chunk or "result" not in trials_in_chunk[0]:
                        raise workflow.CloudError("No complete live trial record")
                    observed_live = True
                    workflow.write_json(evidence/"live-observed-while-running.json",dict(job_id=ident,
                        batch_state=state,completed_trials=snapshot["completed_trials"],record=trials_in_chunk[0]))
        if state in workflow.TERMINAL:
            break
        if time.monotonic()>deadline:
            raise workflow.CloudError(f"Smoke wait exceeded 20 minutes; inspect {ident}; no duplicate or stop was issued.")
        time.sleep(10 if live_mode else 30)
    if live_mode and not observed_live:
        raise workflow.CloudError("No uploaded partial progress was observed while MATLAB was still running")
    active, failures = workflow.collect_outputs(ctx,[project],[job],include_historical=False)
    if failures or active:
        raise workflow.CloudError("; ".join(failures) or "Smoke job remained active.")
    workflow.write_json(evidence / "smoke-verified.json",dict(job_id=ident,state=state,run_dir=str(ctx.run_dir)))
    ctx.log("Two-VM execution, eight workers per VM, shard transfer and automatic merge verified.")


if __name__ == "__main__":
    main()
