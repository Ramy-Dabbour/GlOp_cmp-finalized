"""Freeze a reviewed source snapshot and build a resumable Google Batch job.

This command prepares files only. Submission is a separate explicit command.
No scientific options are changed by this builder.
"""
from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PROJECT = "strange-reducer-509621-e8"
REGION = "us-central1"
BUCKET = PROJECT + "-matlab-glop-cmp"
PARENT_JOB = "matlab-glop-cmp-20261007-135934-b1f7cc"
CONFIG = dict(firOrders=list(range(4, 13)), passbandRatios=[.2, .3, .4, .5],
              randomSeeds=[0, 1, 2], N_tr=20, N_s=10001,
              referenceSolvers=list(range(6)), mziSolvers=list(range(6)),
              solverNames=["ga", "particleswarm", "surrogateopt", "simulannealbnd", "patternsearch", "paretosearch"])


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def source_files():
    for path in sorted((HERE / "source").rglob("*")):
        relative = path.relative_to(HERE / "source")
        if (path.is_file() and path.suffix in {".m", ".py"}
                and "output" not in relative.parts and "__pycache__" not in relative.parts):
            if path.is_symlink():
                raise ValueError("Refusing source symlink")
            yield relative.as_posix(), path


def uploader_program(command, run_uri):
    return "\n".join([
        "import os,pathlib,runpy,sys",
        "index=int(os.environ['BATCH_TASK_INDEX']); count=int(os.environ['BATCH_TASK_COUNT'])",
        "root=pathlib.Path('/work/shared/tasks')/f'{index:05d}'",
        "script=root/'workspace/cloud/durable_uploader.py'",
        f"sys.argv=[str(script),{command!r},'--task-root',str(root),'--run-uri',{run_uri!r},'--manifest',str(root/'workspace/manifest.json'),'--task-index',str(index),'--task-count',str(count),'--interval','0.25']",
        "runpy.run_path(str(script),run_name='__main__')",
    ])


def prepare_program(source_uri, run_uri, manifest_hash):
    return "\n".join([
        "import hashlib,json,os,pathlib,shutil,subprocess,sys",
        "os.environ['CLOUDSDK_PYTHON']=sys.executable",
        "index=int(os.environ['BATCH_TASK_INDEX']); count=int(os.environ['BATCH_TASK_COUNT'])",
        "if not 0<=index<count: raise RuntimeError('Invalid shard identity')",
        "root=pathlib.Path('/work/shared/tasks')/f'{index:05d}'",
        "root.mkdir(parents=True,exist_ok=True)",
        "mounts=[]",
        "for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():",
        "    mount=pathlib.Path(line.split()[4].replace(r'\\040',' '))",
        "    if root.resolve().is_relative_to(mount): mounts.append((len(mount.parts),line))",
        "filesystem=max(mounts)[1].split(' - ',1)[1].split()[0]",
        "if filesystem=='tmpfs': raise RuntimeError('Workspace must be backed by persistent boot disk, not tmpfs')",
        "print(json.dumps(dict(event='workspace-storage',filesystem=filesystem,free_bytes=shutil.disk_usage(root).free)),flush=True)",
        "workspace=root/'workspace'",
        "for name in ('workspace','results','logs'): (root/name).mkdir(exist_ok=True)",
        f"subprocess.run(['gcloud','storage','rsync',{source_uri!r},str(workspace),'--recursive','--checksums-only'],check=True)",
        "manifest_bytes=(workspace/'manifest.json').read_bytes()",
        f"if hashlib.sha256(manifest_bytes).hexdigest()!={manifest_hash!r}: raise RuntimeError('Frozen manifest checksum mismatch')",
        "manifest=json.loads(manifest_bytes)",
        "for name,expected in manifest['files'].items():",
        "    path=workspace/name",
        "    if path.is_symlink() or not path.resolve().is_relative_to(workspace.resolve()): raise RuntimeError('Unsafe source path')",
        "    if hashlib.sha256(path.read_bytes()).hexdigest()!=expected: raise RuntimeError('Frozen source checksum mismatch: '+name)",
        f"subprocess.run([sys.executable,str(workspace/'cloud/durable_uploader.py'),'restore','--task-root',str(root),'--run-uri',{run_uri!r},'--manifest',str(workspace/'manifest.json'),'--task-index',str(index),'--task-count',str(count)],check=True)",
        "for name in ('_uploader.stop','UPLOAD_FAILED.json'): (root/'results'/name).unlink(missing_ok=True)",
        "for path in [root,*root.rglob('*')]:",
        "    if path.is_symlink(): raise RuntimeError('Unexpected workspace symlink')",
        "    os.chown(path,1001,1001); os.chmod(path,0o775 if path.is_dir() else 0o664)",
        "print(json.dumps(dict(event='source-verified-and-restored',run_id=manifest['run_id'],task_index=index)),flush=True)",
    ])


def build(run_id, mode, parallelism):
    if not run_id.startswith("matlab-glop-") or not all(c.islower() or c.isdigit() or c=='-' for c in run_id):
        raise ValueError("Use a lowercase matlab-glop- run ID")
    directory = HERE / "plans" / run_id
    directory.mkdir(parents=True, exist_ok=False)
    frozen = directory / "source"
    frozen.mkdir()
    files = {}
    for name, path in source_files():
        target = frozen / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        files[name] = digest(target.read_bytes())
    config = copy.deepcopy(CONFIG)
    if mode == "smoke":
        config = dict(CONFIG, firOrders=4, passbandRatios=.2, randomSeeds=0,
                      N_tr=24, N_s=21, referenceSolvers=0, mziSolvers=1, fixture="synthetic-recovery-v1")
    tasks = 1 if mode == "smoke" else 4
    manifest = dict(schema_version=1, run_id=run_id, mode=mode, parent_job=PARENT_JOB,
                    created_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
                    source_sha256=digest(canonical(files)), config_sha256=digest(canonical(config)),
                    config=config, files=files, task_count=tasks, workers_per_task=8,
                    assignment="global_id = task_index + 1 : task_count : total_trials")
    write_json(frozen / "manifest.json", manifest)
    source_uri=f"gs://{BUCKET}/runs/{run_id}/source"
    run_uri=f"gs://{BUCKET}/outputs/{run_id}"
    old=json.loads((HERE.parent / "diagnostics/job-failure-20261007/submitted-batch.json").read_text(encoding="utf-8-sig"))
    job=copy.deepcopy(old)
    group=job['taskGroups'][0]
    group['taskCount']=str(tasks)
    group['parallelism']=str(min(parallelism,tasks))
    spec=group['taskSpec']
    transfer=copy.deepcopy(spec['runnables'][0]['container'])
    matlab=copy.deepcopy(spec['runnables'][2])
    matlab.pop('timeout',None)
    matlab['displayName']='matlab-checkpoint-shard'
    entry='fpf.runCloudRecoverySmoke' if mode=='smoke' else 'fpf.runCloudCheckpointShard'
    code=("index=str2double(getenv('BATCH_TASK_INDEX')); count=str2double(getenv('BATCH_TASK_COUNT')); "
          "taskRoot=fullfile('/work/shared','tasks',sprintf('%05d',index)); "
          "cd(fullfile(taskRoot,'workspace')); "
          "diary(fullfile(taskRoot,'logs',sprintf('matlab-attempt-%s.log',getenv('BATCH_TASK_RETRY_ATTEMPT')))); "
          "manifest=jsondecode(fileread('manifest.json')); "
          "identity=struct('run_id',manifest.run_id,'source_sha256',manifest.source_sha256,'config_sha256',manifest.config_sha256); "
          f"{entry}(taskRoot,index,count,identity); diary off;")
    matlab['container']['commands'][-1]=code
    def helper(name,program,**flags):
        container=copy.deepcopy(transfer)
        container['commands']=['-c',program]
        return dict(displayName=name,container=container,**flags)
    spec['runnables']=[
        helper('prepare-and-restore',prepare_program(source_uri,run_uri,digest((frozen/'manifest.json').read_bytes()))),
        helper('durable-publisher',uploader_program('daemon',run_uri),background=True),
        matlab,
        helper('preserve-completed-and-partial-results',uploader_program('finalize',run_uri),alwaysRun=True)]
    spec['maxRetryCount']=10
    spec.pop('maxRunDuration',None)
    job['labels'].update(matlab_cloud_mode='durable_trial_shards',matlab_cloud_tasks=str(tasks),
                         matlab_replication='20261026',matlab_smoke=str(mode=='smoke').lower())
    write_json(directory/'batch.json',job)
    write_json(directory/'launch.json',dict(project=PROJECT,region=REGION,run_id=run_id,
        source_uri=source_uri,run_uri=run_uri,mode=mode,task_count=tasks,parallelism=min(parallelism,tasks),
        source_sha256=manifest['source_sha256'],config_sha256=manifest['config_sha256'],
        original_resources_unchanged=job['allocationPolicy']==old['allocationPolicy'] and spec['computeResource']==old['taskGroups'][0]['taskSpec']['computeResource']))
    return directory


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id',required=True)
    parser.add_argument('--mode',choices=['production','smoke'],required=True)
    parser.add_argument('--parallelism',type=int,default=4,choices=[1,2,3,4])
    args=parser.parse_args()
    print(build(args.run_id,args.mode,args.parallelism))
