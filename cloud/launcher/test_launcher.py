"""Offline tests of quota selection, task isolation, and completion checks."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import matlab_cloud as workflow
import matlab_cloud_run as runner
import matlab_cloud_trials as trials
import matlab_cloud_progress as progress


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "main.m").write_text("disp('fixture');")
        self.config = dict(entry_points=["main.m"], batch_mode="trial_shards",
                           task_count="auto", parallelism="auto", task_count_per_node=1,
                           machine_type="e2-standard-8", cpu_milli=8000, memory_mib=30000,
                           workers_per_task=8, boot_disk_gb=100)
        self.project = workflow.Project(self.root, "fixture", "fixture", "unit-only", self.config)
        quota = lambda metric, limit, usage: dict(metric=metric, limit=limit, usage=usage)
        self.region = {"quotas": [quota("CPUS",200,8), quota("E2_CPUS",24,0),
                                    quota("INSTANCES",24,1), quota("SSD_TOTAL_GB",500,100),
                                    quota("IN_USE_ADDRESSES",8,1)]}
        self.global_info = {"quotas": [quota("CPUS_ALL_REGIONS",32,8)]}
        self.ctx = SimpleNamespace(region="us-central1", project="unit-only", run_dir=self.root,
                                   log=mock.Mock(), dry_run=False,
                                   settings={"license":{"mode":"online","image_prepared":True},
                                             "service_account":"batch@example.iam.gserviceaccount.com",
                                             "transfer_image":"gcr.io/google.com/cloudsdktool/google-cloud-cli:548.0.0-stable"},
                                   env_image="us-central1-docker.pkg.dev/example/images/matlab:r2026a",
                                   env_digest="sha256:" + "a"*64)
        self.ctx.gcloud = mock.Mock(side_effect=self.gcloud)

    def gcloud(self, *args, **kwargs):
        if args[:2] == ("compute", "regions"):
            return self.region
        if args[:2] == ("compute", "project-info"):
            return self.global_info
        if args[:2] == ("compute", "zones"):
            return [dict(name="us-central1-a", region="regions/us-central1", status="UP")]
        if args[:2] == ("compute", "machine-types"):
            return dict(guestCpus=8, memoryMb=32768)
        raise AssertionError("Unexpected cloud mutation: " + repr(args))

    def resolve(self):
        return trials.resolve_layout(self.ctx, self.project)

    def test_auto_submits_only_concurrent_tasks(self):
        resolved = self.resolve()
        self.assertEqual(resolved.config["task_count"],3)
        self.assertEqual(resolved.config["parallelism"],3)
        self.assertEqual(self.project.config["task_count"],"auto")
        plan = json.loads((self.root/"fixture-quota-plan.json").read_text())
        self.assertEqual(plan["total_workers"],24)

    def test_disk_can_limit_concurrency(self):
        self.region["quotas"][3]["usage"] = 400
        self.assertEqual(self.resolve().config["task_count"],1)

    def test_e2_uses_shared_cpu_pool_and_capacity_grows_when_resources_release(self):
        for quota in self.region["quotas"]:
            quota["usage"]=0
        self.region["quotas"][1]["limit"]=0 # E2_CPUS is not the E2 quota pool.
        self.global_info["quotas"][0]["usage"]=0
        self.assertEqual(self.resolve().config["task_count"],4)

    def test_global_cpu_can_limit_concurrency(self):
        self.global_info["quotas"][0]["usage"] = 24
        self.assertEqual(self.resolve().config["task_count"],1)

    def test_zero_capacity_blocks_submission(self):
        self.global_info["quotas"][0]["usage"] = 32
        with self.assertRaisesRegex(workflow.CloudError,"No quota remains"):
            self.resolve()

    def test_missing_quota_blocks_instead_of_guessing(self):
        self.global_info["quotas"] = []
        with self.assertRaisesRegex(workflow.CloudError,"quota CPUS_ALL_REGIONS is missing"):
            self.resolve()

    def test_cannot_queue_more_tasks_than_available(self):
        self.config["task_count"] = 24
        with self.assertRaisesRegex(workflow.CloudError,"quotas permit 3"):
            self.resolve()

    def test_pool_size_must_match_vm_and_allocation(self):
        self.config["workers_per_task"] = 4
        with self.assertRaisesRegex(workflow.CloudError,"one vCPU per MATLAB worker"):
            self.resolve()
        self.config["cpu_milli"] = 4000
        with self.assertRaisesRegex(workflow.CloudError,"VM's vCPU count"):
            self.resolve()

    def test_job_contains_exact_counts_and_pool_contract(self):
        job = runner.build_job(self.ctx,self.resolve(),"fixture-job","gs://unit-only/source",False)
        group = job["taskGroups"][0]
        self.assertEqual((group["taskCount"],group["parallelism"],group["taskCountPerNode"]),("3","3","1"))
        self.assertEqual(group["taskSpec"]["computeResource"]["cpuMilli"],"8000")
        runnables = group["taskSpec"]["runnables"]
        matlab = runnables[1]
        self.assertEqual(matlab["environment"]["variables"]["FPF_WORKERS_PER_TASK"],"8")
        self.assertIn("-singleCompThread",matlab["container"]["commands"])
        self.assertIn("BATCH_TASK_INDEX",matlab["container"]["commands"][-1])
        for item in runnables:
            self.assertEqual(item["container"]["volumes"],["/var/lib/google/matlab-cloud:/work/shared:rw"])
        self.assertEqual(job["labels"]["matlab_cloud_tasks"],"3")
        for item in (runnables[0],runnables[-1]):
            compile(item["container"]["commands"][-1],"helper","exec")

    @contextlib.contextmanager
    def helpers(self, index, transfer):
        original_read = Path.read_text
        escaped = self.root.as_posix().replace("\\",r"\134").replace(" ",r"\040")
        mount = f"100 20 8:1 / {escaped} rw - ext4 /dev/sda1 rw"
        def read(path,*args,**kwargs):
            return mount if path==Path("/proc/self/mountinfo") else original_read(path,*args,**kwargs)
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner,"SHARED",str(self.root)))
            stack.enter_context(mock.patch.object(Path,"read_text",read))
            stack.enter_context(mock.patch.object(shutil,"disk_usage",return_value=SimpleNamespace(total=1000000,free=900000)))
            stack.enter_context(mock.patch.object(os,"statvfs",create=True,return_value=SimpleNamespace(f_files=100,f_favail=90)))
            stack.enter_context(mock.patch.object(os,"chown",create=True))
            stack.enter_context(mock.patch.object(os,"chmod"))
            stack.enter_context(mock.patch.dict(os.environ,BATCH_TASK_INDEX=str(index),BATCH_TASK_COUNT="2"))
            stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            run = stack.enter_context(mock.patch.object(subprocess,"run",side_effect=transfer))
            yield run

    def transfer(self, args, **kwargs):
        self.assertTrue(kwargs["check"])
        if args[2]=="rsync" and args[3]=="gs://unit-only/source":
            (Path(args[4])/"main.m").write_text("fixture")
        return subprocess.CompletedProcess(args,0)

    def test_tasks_isolate_workspaces_and_upload_unique_shards(self):
        destinations=[]
        for index in range(2):
            with self.helpers(index,self.transfer) as run:
                exec(runner._prepare_program("gs://unit-only/source",True),{})
                root=self.root/"tasks"/f"{index:05d}"
                shard=root/"results"/f"trial_shard_{index:05d}.mat"
                shard.write_bytes(f"task {index}".encode())
                run.reset_mock()
                exec(runner._collect_program("gs://unit-only/output","fixture-job",True,8),{})
                commands=[call.args[0] for call in run.call_args_list]
                destinations.extend(command[4] for command in commands if command[2]=="cp")
                workspace_transfers=[command for command in commands if command[2]=="rsync" and command[4].endswith("/workspace")]
                self.assertEqual(len(workspace_transfers),1 if index==0 else 0)
                marker=json.loads((root/"_TRANSFER_COMPLETE.json").read_text())
                self.assertEqual(marker["task_index"],index)
                self.assertEqual(marker["workers_per_task"],8)
                self.assertEqual(marker["shard_sha256"],hashlib.sha256(shard.read_bytes()).hexdigest())
        self.assertEqual(len(destinations),len(set(destinations)))
        self.assertNotEqual((self.root/"tasks/00000/workspace"),(self.root/"tasks/00001/workspace"))

    def test_missing_shard_does_not_write_completion_marker(self):
        with self.helpers(1,self.transfer):
            exec(runner._prepare_program("gs://unit-only/source",True),{})
            with self.assertRaisesRegex(RuntimeError,"No completed trial shard"):
                exec(runner._collect_program("gs://unit-only/output","fixture-job",True,8),{})
            self.assertFalse((self.root/"tasks/00001/_TRANSFER_COMPLETE.json").exists())

    def test_collector_rejects_failed_job_and_missing_shards(self):
        job=dict(name="projects/unit/locations/region/jobs/fixture-job",
                 labels=dict(matlab_cloud_tasks="2",matlab_cloud_workers="8"),status=dict(state="FAILED"))
        with self.assertRaisesRegex(workflow.CloudError,"did not succeed"):
            trials.collect_trial_results(self.ctx,self.project,job,self.root)
        job["status"]["state"]="SUCCEEDED"
        with self.assertRaisesRegex(workflow.CloudError,"incomplete or unexpected shard set"):
            trials.collect_trial_results(self.ctx,self.project,job,self.root)

    def test_legacy_projects_remain_one_task(self):
        self.project.config={"entry_points":["main.m"]}
        self.assertIs(trials.resolve_layout(self.ctx,self.project),self.project)
        self.ctx.gcloud.assert_not_called()
        job=runner.build_job(self.ctx,self.project,"fixture-job","gs://unit-only/source",False)
        self.assertEqual(job["taskGroups"][0]["taskCount"],"1")
        self.assertNotIn("matlab_cloud_mode",job["labels"])

    def test_live_launcher_starts_background_uploader_and_drains_before_final_shard(self):
        self.config["live_reporting"] = True
        path = self.root/"cloud/live_reporter.py"
        path.parent.mkdir()
        path.write_text("fixture")
        job = runner.build_job(self.ctx,self.resolve(),"fixture-job","gs://unit-only/source",False)
        runnables = job["taskGroups"][0]["taskSpec"]["runnables"]
        self.assertEqual([r["displayName"] for r in runnables],
                         ["prepare-source","publish-live-trials","matlab-entry-1","preserve-outputs"])
        self.assertTrue(runnables[1]["background"])
        self.assertIn("FPF_LIVE_DIR",runnables[2]["container"]["commands"][-1])
        collector = runnables[-1]["container"]["commands"][-1]
        self.assertLess(collector.index("--final"),collector.index("shard ="))
        self.assertIn("_FLUSHED.json",collector)
        self.assertEqual(job["labels"]["matlab_cloud_live"],"true")
        for runnable in (runnables[0],runnables[1],runnables[-1]):
            compile(runnable["container"]["commands"][-1],"helper","exec")

    def test_final_shard_is_not_uploaded_when_live_flush_fails(self):
        def transfer(args,**kwargs):
            if "--final" in args:
                raise subprocess.CalledProcessError(1,args)
            return self.transfer(args,**kwargs)
        with self.helpers(0,transfer) as run:
            exec(runner._prepare_program("gs://unit-only/source",True),{})
            root=self.root/"tasks/00000"
            (root/"results/trial_shard_00000.mat").write_bytes(b"fixture")
            run.reset_mock()
            with self.assertRaises(subprocess.CalledProcessError):
                exec(runner._collect_program("gs://unit-only/output","fixture-job",True,8,True),{})
            self.assertFalse((root/"_TRANSFER_COMPLETE.json").exists())
            self.assertFalse(any(c.args[0][:3]==["gcloud","storage","cp"] for c in run.call_args_list))

    def test_successful_flush_acknowledgement_precedes_final_upload(self):
        def transfer(args,**kwargs):
            if "--final" in args:
                root=self.root/"tasks/00000"
                workflow.write_json(root/"live/_FLUSHED.json",dict(status="completed",completed_trials=8))
                return subprocess.CompletedProcess(args,0)
            return self.transfer(args,**kwargs)
        with self.helpers(0,transfer) as run:
            exec(runner._prepare_program("gs://unit-only/source",True),{})
            root=self.root/"tasks/00000"
            (root/"results/trial_shard_00000.mat").write_bytes(b"fixture")
            run.reset_mock()
            exec(runner._collect_program("gs://unit-only/output","fixture-job",True,8,True),{})
            commands=[call.args[0] for call in run.call_args_list]
            flush_index=next(i for i,command in enumerate(commands) if "--final" in command)
            upload_index=next(i for i,command in enumerate(commands) if command[:3]==["gcloud","storage","cp"])
            self.assertLess(flush_index,upload_index)
            marker=workflow.read_json(root/"_TRANSFER_COMPLETE.json")
            self.assertEqual(marker["live_published_trials"],8)

    def test_progress_command_only_reads_cloud_state(self):
        self.ctx.gcloud = mock.Mock(return_value=json.dumps(dict(job_id="fixture-job",total_trials=10,completed_trials=2,
            percent_complete=20,updated_at="2026-10-07T00:00:00+00:00",status="running",
            succeeded_trials=1,nonconverged_trials=1,failed_trials=0,active_workers=8,stale_workers=0,tasks=[])))
        job=dict(name="projects/unit/locations/region/jobs/fixture-job",labels=dict(matlab_project="fixture",matlab_cloud_live="true"),status=dict(state="RUNNING"))
        instance=workflow.Workflow(self.ctx,[self.project])
        with mock.patch.object(workflow,"list_jobs",return_value=[job]):
            snapshot=progress.show_progress(instance,"fixture-job")
        self.assertEqual(snapshot["completed_trials"],2)
        self.assertTrue(all(call.args[:2]==("storage","cat") for call in self.ctx.gcloud.call_args_list))

    def test_old_jobs_cannot_claim_live_reporting(self):
        job=dict(name="projects/unit/locations/region/jobs/fixture-job",labels={})
        with self.assertRaisesRegex(workflow.CloudError,"submitted without live reporting"):
            progress.read_progress(self.ctx,self.project,job)

    def test_missing_live_report_surfaces_the_actual_uploader_error(self):
        self.ctx.gcloud = mock.Mock(side_effect=[
            workflow.CommandError(["storage","cat"],1,"","HTTPError 404: not found"),
            [dict(timestamp="2026-10-07T09:00:00Z",jsonPayload=dict(error="certificate verification failed"))]])
        job=dict(name="projects/unit/locations/region/jobs/fixture-job",uid="unit-uid",
                 labels=dict(matlab_cloud_live="true"),status=dict(state="RUNNING"))
        self.assertIsNone(progress.read_progress(self.ctx,self.project,job))
        self.assertIn("certificate verification failed",self.ctx.log.call_args.args[0])
        self.assertEqual(self.ctx.gcloud.call_args.args[:2],("logging","read"))

    def test_cat_uses_raw_bytes_without_a_json_printer_footer(self):
        self.ctx.gcloud=mock.Mock(return_value='{"job_id":"fixture-job","completed_trials":2}')
        snapshot=progress.read_json_object(self.ctx,"gs://unit-only/summary.json")
        self.assertEqual(snapshot["completed_trials"],2)
        self.assertIn("--format=none",self.ctx.gcloud.call_args.args)
        self.assertTrue(self.ctx.gcloud.call_args.kwargs["_raw_output"])
        self.assertNotIn("json_output",self.ctx.gcloud.call_args.kwargs)

    def test_diagnostic_and_launcher_files_are_excluded_from_source(self):
        for name in ("cloud/diagnostics/snapshot/main.m","cloud/launcher/runner.py"):
            path=self.root/name
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text("fixture")
        self.assertEqual(workflow.source_files(self.project),[self.root/"main.m"])

    def test_complete_collection_verifies_checksums_and_merges_once(self):
        snapshot=self.root/"snapshot-fixture"
        (snapshot/"results").mkdir(parents=True)
        (snapshot/"workspace/+fpf").mkdir(parents=True)
        (snapshot/"workspace/+fpf/mergeBatchResults.m").write_text("fixture")
        workflow.write_json(snapshot/".matlab-cloud-download.json",dict(inventory_sha256="fixture"))
        for index in range(2):
            shard=snapshot/"results"/f"trial_shard_{index:05d}.mat"
            shard.write_bytes(str(index).encode())
            workflow.write_json(snapshot/"tasks"/f"{index:05d}"/"_TRANSFER_COMPLETE.json",
                                dict(schema_version=2,job_id="fixture-job",task_index=index,
                                     task_count=2,workers_per_task=8,
                                     shard_sha256=hashlib.sha256(shard.read_bytes()).hexdigest()))
        job=dict(name="projects/unit/locations/region/jobs/fixture-job",
                 labels=dict(matlab_cloud_tasks="2",matlab_cloud_workers="8"),status=dict(state="SUCCEEDED"))
        self.config["local_matlab_executable"]=str(self.root/"main.m")
        def merge(arguments,**kwargs):
            self.assertFalse(kwargs["shell"])
            self.assertIn(str((snapshot/"workspace").resolve()).replace("\\","/"),arguments[-1])
            for name in ("benchmark_results.mat","benchmark_results.csv"):
                (self.root/"aggregate-fixture"/name).write_bytes(name.encode())
            return subprocess.CompletedProcess(arguments,0)
        with mock.patch.object(subprocess,"run",side_effect=merge) as run:
            actual=trials.collect_trial_results(self.ctx,self.project,job,snapshot)
            self.assertTrue((actual/"_MERGE_COMPLETE.json").is_file())
            self.assertEqual(trials.collect_trial_results(self.ctx,self.project,job,snapshot),actual)
            run.assert_called_once()
        (snapshot/"results/trial_shard_00001.mat").write_bytes(b"changed")
        with self.assertRaisesRegex(workflow.CloudError,"checksum disagrees"):
            trials.collect_trial_results(self.ctx,self.project,job,snapshot)

    def test_batched_download_keeps_generations_and_directory_structure(self):
        records=[]
        relatives=["results/a.mat","results/b.mat","tasks/00000/_TRANSFER_COMPLETE.json",
                   "tasks/00001/_TRANSFER_COMPLETE.json","workspace/+fpf/a.m"]
        for relative in relatives:
            records.append(dict(name="outputs/fixture-job/"+relative,generation="42",size=1,md5_hash="fixture"))
        calls=[]
        def copy(*arguments,**kwargs):
            self.assertEqual(arguments[:2],("storage","cp"))
            self.assertIn("--no-clobber",arguments)
            parent=Path(arguments[-3])
            uris=arguments[2:-3]
            calls.append((parent,uris))
            for uri in uris:
                self.assertTrue(uri.endswith("#42"))
                name=uri.rsplit("/",1)[-1].split("#",1)[0]
                (parent/name).write_bytes(b"x")
        self.ctx.root=self.root
        self.ctx.gcloud=copy
        with mock.patch.object(workflow,"list_objects",return_value=records), mock.patch.object(workflow,"verify_file") as verify:
            actual=workflow.download_snapshot(self.ctx,self.project,"fixture-job",records,required=True)
        self.assertEqual(len(calls),4)
        self.assertEqual(verify.call_count,5)
        self.assertTrue(all((actual/relative).is_file() for relative in relatives))
        self.assertEqual(len(workflow.read_json(actual/".matlab-cloud-download.json")["local_sha256"]),5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
