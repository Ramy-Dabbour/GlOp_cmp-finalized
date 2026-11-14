"""Submit, monitor, collect, and resume a frozen replication without changing science."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import os
from pathlib import Path
import ssl
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.parse
import urllib.request
import urllib.error

GCLOUD = Path(os.environ.get('LOCALAPPDATA','')) / 'Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd'
HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def atomic_json(path, value):
    temp=path.with_suffix('.tmp.json')
    temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    os.replace(temp,path)


class Manager:
    def __init__(self,plan):
        self.plan=Path(plan).resolve()
        self.launch=json.loads((self.plan/'launch.json').read_text())
        self.state_path=self.plan/'controller-state.json'
        self.state=json.loads(self.state_path.read_text()) if self.state_path.exists() else dict(run_id=self.launch['run_id'],jobs=[])
        self.evidence=self.plan/'evidence'
        self.evidence.mkdir(exist_ok=True)
        self.output=PROJECT_ROOT/'cloud-results'/self.launch['run_id']
        self.output.mkdir(parents=True,exist_ok=True)

    def log(self,message):
        line=f'[{now()}] {message}'
        print(line,flush=True)
        with (self.plan/'controller.log').open('a',encoding='utf-8') as handle: handle.write(line+'\n')

    def cloud(self,*args,optional=False):
        # Bound only local control-plane requests, never MATLAB computation.
        # Otherwise an expired login or stalled CLI can freeze the monitor for
        # an hour. Static source transfer retains its longer transfer allowance.
        request_timeout=3600 if args[:2]==('storage','rsync') else 120
        result=subprocess.run([str(GCLOUD),*map(str,args),'--quiet'],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=request_timeout)
        if result.returncode:
            if optional and ('404' in result.stderr or 'NOT_FOUND' in result.stderr or 'was not found' in result.stderr or 'No URLs matched' in result.stderr or 'matched no objects' in result.stderr): return None
            raise RuntimeError(f'gcloud {args[0:2]} failed: {result.stderr[-4000:]}')
        return result.stdout

    def submit(self):
        if not self.state['jobs']:
            # IDs are unique; never overwrite an existing source namespace.
            existing=self.cloud('storage','cat',self.launch['source_uri']+'/manifest.json',optional=True)
            if existing is not None:
                expected=json.loads((self.plan/'source/manifest.json').read_text())
                if json.loads(existing)!=expected: raise RuntimeError('Remote source manifest disagrees; refusing overwrite')
            self.log('Uploading frozen source and checksum manifest.')
            self.cloud('storage','rsync',self.plan/'source',self.launch['source_uri'],'--recursive','--checksums-only')
        number=len(self.state['jobs'])
        job_id=self.launch['run_id'] if number==0 else self.launch['run_id']+f'-r{number:02d}'
        # Recover an accepted submission if a previous client lost its response.
        existing=self.cloud('batch','jobs','describe',job_id,'--location',self.launch['region'],'--project',self.launch['project'],'--format=json',optional=True)
        if existing is None:
            self.log(f'Submitting {job_id}; immutable run namespace {self.launch["run_id"]}.')
            response=self.cloud('batch','jobs','submit',job_id,'--location',self.launch['region'],'--project',self.launch['project'],'--config',self.plan/'batch.json','--format=json')
            job=json.loads(response)
        else: job=json.loads(existing)
        self.state['jobs'].append(dict(job_id=job_id,submitted_at=now(),uid=job.get('uid')))
        self.state['current_job']=job_id
        atomic_json(self.state_path,self.state)
        atomic_json(self.evidence/(job_id+'.json'),job)
        self.log('Job: https://console.cloud.google.com/batch/jobsDetail/regions/'+self.launch['region']+'/jobs/'+job_id+'?project='+self.launch['project'])
        return job

    def status(self):
        if not self.state['jobs']: return None,None
        job_id=self.state['current_job']
        job=json.loads(self.cloud('batch','jobs','describe',job_id,'--location',self.launch['region'],'--project',self.launch['project'],'--format=json'))
        atomic_json(self.evidence/(job_id+'.json'),job)
        raw=self.read_current_object('live/summary.json',optional=True)
        summary=json.loads(raw) if raw is not None else None
        if summary:
            for key in ('run_id','source_sha256','config_sha256'):
                if summary[key]!=self.launch[key]: raise RuntimeError('Remote summary identity mismatch')
            atomic_json(self.output/'live-summary.json',summary)
        self.state['last_checked_at']=now()
        self.state['batch_state']=job['status']['state']
        if summary: self.state['completed_trials']=summary['completed_trials']
        atomic_json(self.state_path,self.state)
        return job,summary

    def read_current_object(self,relative_name,optional=False):
        # Do not pin a generation from a separate metadata read: the live
        # publisher replaces this object while a slow CLI request is starting.
        token=self.cloud('auth','print-access-token').strip()
        uri=urllib.parse.urlsplit(self.launch['run_uri'])
        name=uri.path.strip('/')+'/'+relative_name
        url=('https://storage.googleapis.com/storage/v1/b/'+urllib.parse.quote(uri.netloc,safe='')+
             '/o/'+urllib.parse.quote(name,safe='')+'?alt=media')
        ca=GCLOUD.parent.parent/'lib/third_party/certifi/cacert.pem'
        context=ssl.create_default_context(cafile=str(ca) if ca.is_file() else None)
        request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
        try:
            with urllib.request.urlopen(request,context=context,timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if optional and error.code==404: return None
            raise

    def collect(self):
        artifacts=self.output/'artifacts'
        artifacts.mkdir(exist_ok=True)
        self.download_current_artifacts(artifacts)
        rows=[]
        seen=set()
        for path in sorted(artifacts.glob('tasks/*/results/trial_results.csv')):
            with path.open(newline='',encoding='utf-8-sig') as handle:
                for row in csv.DictReader(handle):
                    trial_id=int(row['trial_id'])
                    if trial_id in seen: raise RuntimeError('Overlapping shard identities in exported CSV')
                    seen.add(trial_id); rows.append(row)
        if rows:
            rows.sort(key=lambda row:int(row['trial_id']))
            config=json.loads((self.plan/'source/manifest.json').read_text())['config']
            vectors={key:value if isinstance(value,list) else [value] for key,value in config.items()
                     if key in ('firOrders','passbandRatios','randomSeeds','referenceSolvers','mziSolvers')}
            for row in rows:
                quotient=int(row['trial_id'])-1
                quotient,trial=divmod(quotient,config['N_tr'])
                row['repetition']=trial+1
                for key,label in [('mziSolvers','mzi_solver'),('referenceSolvers','reference_solver'),
                                  ('firOrders','fir_order'),('passbandRatios','passband_ratio'),('randomSeeds','seed')]:
                    quotient,index=divmod(quotient,len(vectors[key])); row[label]=vectors[key][index]
                if quotient: raise RuntimeError('CSV trial exceeds manifest configuration')
            target=self.output/'trial_results.csv'; temp=target.with_suffix('.tmp.csv')
            with temp.open('w',newline='',encoding='utf-8') as handle:
                writer=csv.DictWriter(handle,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
            os.replace(temp,target)
            self.assemble_mat_summary(rows,config,vectors)
        self.log(f'Collected partial MAT/CSV/log artifacts to {self.output}; {len(rows)} assigned CSV rows (including pending).')

    def download_current_artifacts(self,destination):
        # gsutil/gcloud rsync pins generations from its initial listing. Live
        # summaries are overwritten meanwhile, so old generations can 404.
        # Fetch each named current object atomically instead. Immutable trial
        # records remain authoritative; these files are reconstructible exports.
        token=self.cloud('auth','print-access-token').strip()
        uri=urllib.parse.urlsplit(self.launch['run_uri'])
        prefix=uri.path.strip('/')+'/artifacts/'
        api='https://storage.googleapis.com/storage/v1/b/'+urllib.parse.quote(uri.netloc,safe='')+'/o'
        ca=GCLOUD.parent.parent/'lib/third_party/certifi/cacert.pem'
        context=ssl.create_default_context(cafile=str(ca) if ca.is_file() else None)
        def get(url):
            request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token})
            with urllib.request.urlopen(request,context=context,timeout=60) as response:
                return response.read(),response.headers.get('x-goog-generation')
        names=[]; page_token=None
        while True:
            params=dict(prefix=prefix,fields='items/name,nextPageToken',maxResults=1000)
            if page_token: params['pageToken']=page_token
            page=json.loads(get(api+'?'+urllib.parse.urlencode(params))[0])
            names.extend(item['name'] for item in page.get('items',[]))
            page_token=page.get('nextPageToken')
            if not page_token: break
        def download(name):
            relative=Path(name.removeprefix(prefix))
            if relative.suffix not in {'.mat','.csv','.log','.txt','.out','.err'}: return None
            target=(destination/relative).resolve()
            if not target.is_relative_to(destination.resolve()): raise RuntimeError('Unsafe artifact path')
            data,generation=get(api+'/'+urllib.parse.quote(name,safe='')+'?alt=media')
            target.parent.mkdir(parents=True,exist_ok=True)
            temporary=target.with_name(target.name+'.download.tmp')
            temporary.write_bytes(data); os.replace(temporary,target)
            return dict(path=relative.as_posix(),generation=generation,bytes=len(data))
        with ThreadPoolExecutor(max_workers=8) as pool:
            downloaded=[item for item in pool.map(download,names) if item is not None]
        atomic_json(self.output/'artifact-downloads.json',dict(collected_at=now(),files=downloaded))

    def assemble_mat_summary(self,rows,config,vectors):
        # Original MATLAB table MAT files remain verbatim in artifacts/tasks/.
        # This portable consolidated MAT stores arrays and structs for all rows.
        import numpy as np
        from scipy.io import savemat
        def truth(value): return str(value).lower() in ('1','true')
        summaries=[]
        for reference in vectors['referenceSolvers']:
            for mzi in vectors['mziSolvers']:
                subset=[r for r in rows if r['reference_solver']==reference and r['mzi_solver']==mzi]
                complete=[r for r in subset if truth(r['completed'])]
                success=[r for r in complete if truth(r['success'])]
                error=sum(float(r['legacy_error']) for r in success)/len(success) if success else math.nan
                evaluations=sum(float(r['legacy_evaluations']) for r in success)/len(success) if success else math.nan
                rate=len(success)/len(complete) if complete else math.nan
                favorability=0.0 if complete else math.nan
                if success:
                    if not math.isfinite(error) or error<0 or not math.isfinite(evaluations) or evaluations<=1: favorability=math.nan
                    elif error==0: favorability=math.inf
                    else: favorability=rate/error/math.log(evaluations)
                summaries.append(dict(reference_solver=reference,mzi_solver=mzi,
                    assigned_rows=len(subset),completed_trials=len(complete),successful_trials=len(success),
                    legacy_success_rate=rate,mean_successful_error=error,mean_successful_evaluations=evaluations,
                    legacy_favorability=favorability))
        target=self.output/'benchmark_summary.csv'; temp=target.with_suffix('.tmp.csv')
        with temp.open('w',newline='',encoding='utf-8') as handle:
            writer=csv.DictWriter(handle,fieldnames=list(summaries[0])); writer.writeheader(); writer.writerows(summaries)
        os.replace(temp,target)
        trial_data={}
        for key in rows[0]:
            if key=='status': values=np.array([r[key] for r in rows],dtype=object)
            elif key in ('completed','success'): values=np.array([truth(r[key]) for r in rows],dtype=bool)
            else: values=np.array([float(r[key]) for r in rows])
            trial_data[key]=values.reshape(-1,1)
        summary_data={key:np.array([r[key] for r in summaries]).reshape(-1,1) for key in summaries[0]}
        target=self.output/'benchmark_results.mat'; temp=target.with_suffix('.tmp.mat')
        savemat(temp,dict(trialResults=trial_data,benchmarkSummary=summary_data,config=config,
            runIdentity={key:self.launch[key] for key in ('run_id','source_sha256','config_sha256')},
            collectedAt=now()),do_compression=True)
        os.replace(temp,target)

    def capture_logs(self,job):
        if not job.get('uid'): return []
        raw=self.cloud('logging','read',f'labels.job_uid="{job["uid"]}"','--project',self.launch['project'],'--limit=1000','--order=desc','--format=json')
        logs=json.loads(raw)
        atomic_json(self.evidence/(self.state['current_job']+'-last-logs.json'),logs)
        return logs

    def watch(self):
        # A scheduled logon recovery and an already-open terminal cannot both
        # submit replacements. Lock release is automatic if Windows terminates us.
        import msvcrt
        lock_file=(self.plan/'controller.lock').open('a+b')
        if lock_file.tell()==0: lock_file.write(b'0'); lock_file.flush()
        lock_file.seek(0)
        try:
            msvcrt.locking(lock_file.fileno(),msvcrt.LK_NBLCK,1)
        except OSError:
            lock_file.close()
            self.log('Another replication monitor already owns the controller lock.')
            return
        try:
            return self._watch_owned()
        finally:
            lock_file.seek(0); msvcrt.locking(lock_file.fileno(),msvcrt.LK_UNLCK,1); lock_file.close()

    def _watch_owned(self):
        if not self.state['jobs']: self.submit()
        collector=ThreadPoolExecutor(max_workers=1,thread_name_prefix='mat-csv-collector')
        collection=None
        last_collect=0; last_line=None; retry_delay=60
        while not (self.plan/'STOP_MONITOR').exists():
            try:
                job,summary=self.status()
                state=job['status']['state']
                line=f'{self.state["current_job"]}: {state}'
                if summary:
                    line+=f'; durable trials={summary["completed_trials"]}/{summary.get("total_trials")}; reporting tasks={summary.get("reporting_tasks")}'
                    counts=[str(task.get('workers_per_task','?')) for task in summary.get('tasks',[])]
                    line+='; process workers by task='+','.join(counts)
                    active=[worker for task in summary.get('tasks',[]) for worker in task.get('workers',[]) if worker.get('active')]
                    evaluations=sum(worker.get('objective_evaluations',0) or 0 for worker in active)
                    line+=f'; active={len(active)}; current-trial evaluations={evaluations}'
                if line!=last_line: self.log(line); last_line=line
                if collection is not None and collection.done():
                    finished=collection; collection=None
                    finished.result()
                if state in {'SUCCEEDED','FAILED'}:
                    if collection is not None: collection.result(); collection=None
                    self.collect(); last_collect=time.monotonic()
                elif time.monotonic()-last_collect>=300 and collection is None:
                    # Downloads must not block the visible live progress stream.
                    collection=collector.submit(self.collect)
                    last_collect=time.monotonic()
                if state=='SUCCEEDED':
                    if not summary or summary['status']!='completed': raise RuntimeError('Batch succeeded but durable dataset is incomplete; investigate before new compute')
                    self.capture_logs(job)
                    self.log('All assigned trials are durably committed and final shard MAT/CSV files collected.')
                    return
                if state=='FAILED':
                    logs=self.capture_logs(job)
                    text=json.dumps(logs)
                    fatal_markers=('checkpoint-integrity-error','checkpoint-configuration-error',
                                   'Frozen source checksum mismatch','Frozen manifest checksum mismatch',
                                   'fpf:CorruptCheckpoint','fpf:CheckpointMismatch','fpf:InvalidCloudAcknowledgement',
                                   'fpf:ScientificConfigurationChanged','Committed trial disagrees with the local checkpoint')
                    if any(marker in text for marker in fatal_markers):
                        raise RuntimeError('Integrity/configuration failure requires investigation; automatic resubmission would repeat it')
                    if summary and summary['status']=='completed':
                        self.log('All scientific trials committed despite Batch failure. Saved artifacts and logs; no recomputation required.')
                        return
                    instances=json.loads(self.cloud('compute','instances','list','--project',self.launch['project'],'--format=json'))
                    if any(instance.get('name','').startswith(job['uid']+'-') for instance in instances):
                        self.log('Waiting for Batch to remove the previous job VMs before resubmission; this prevents overlapping writers.')
                        time.sleep(30)
                        continue
                    self.log('Batch retry/lifetime exhausted. Resubmitting the identical four-shard workload against the same durable checkpoint namespace.')
                    self.submit(); retry_delay=60
                retry_delay=60
                time.sleep(15)
            except (OSError,subprocess.TimeoutExpired,RuntimeError) as error:
                self.log(str(error))
                if any(word in str(error).lower() for word in ('integrity','mismatch','disagrees','incomplete; investigate','configuration failure')):
                    atomic_json(self.plan/'NEEDS_ATTENTION.json',dict(at=now(),error=str(error)))
                    raise
                self.log(f'Will retry cloud communication in {retry_delay}s; cloud workers continue independently.')
                time.sleep(retry_delay); retry_delay=min(600,retry_delay*2)
        self.log('Monitor stopped by STOP_MONITOR; this does not cancel a cloud job.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['submit','status','collect','watch'])
    parser.add_argument('--plan',required=True)
    args=parser.parse_args()
    manager=Manager(args.plan)
    result=getattr(manager,args.command)()
    if args.command=='status':
        job,summary=result
        print(json.dumps(dict(batch_state=job['status']['state'] if job else None,summary=summary),indent=2))
