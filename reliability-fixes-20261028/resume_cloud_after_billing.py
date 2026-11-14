"""Submit one continuation using verified checkpoints and the unchanged frozen job."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'cloud/replication-20261028/plans/matlab-glop-cmp-20261028-fixes'
BACKUP = ROOT / 'cloud-results/matlab-glop-cmp-20261028-fixes/recovery-backup-20261103'
spec = importlib.util.spec_from_file_location('existing_replication_manager', ROOT / 'cloud/replication-20261026/manage_replication.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class HiddenManager(module.Manager):
    def cloud(self, *args, optional=False):
        result = subprocess.run([str(module.GCLOUD), *map(str,args), '--quiet'],
                                capture_output=True, text=True, encoding='utf-8', errors='replace',
                                timeout=120, creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            if optional and any(text in result.stderr for text in ('404','NOT_FOUND','was not found','No URLs matched','matched no objects')):
                return None
            raise RuntimeError(f'gcloud {args[:2]} failed: {result.stderr[-4000:]}')
        return result.stdout

def main():
    verification = json.loads((BACKUP / 'verification.json').read_text())
    if verification.get('all_checks_passed') is not True or verification.get('verified_committed_trials',0) < 27905:
        raise RuntimeError('Complete verified checkpoint backup is required before submission')
    manager = HiddenManager(PLAN)
    for key in ('run_id','source_sha256','config_sha256'):
        if verification[key] != manager.launch[key]:
            raise RuntimeError('Backup identity differs from frozen run')
    if hashlib.sha256((PLAN / 'batch.json').read_bytes()).hexdigest() != '8a3c6323d3fa5735f1a141cd91984a401ab51257118b970c84489d13dd226101':
        raise RuntimeError('Frozen Batch configuration changed')
    manifest = json.loads((PLAN / 'source/manifest.json').read_text())
    for name, digest in manifest['files'].items():
        if hashlib.sha256((PLAN / 'source' / name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Frozen source changed: ' + name)
    billing = json.loads(manager.cloud('billing','projects','describe',manager.launch['project'],'--format=json'))
    if billing.get('billingEnabled') is not True:
        raise RuntimeError('Billing is not enabled')
    remote_manifest = json.loads(manager.read_current_object('manifest.json'))
    if remote_manifest != manifest:
        raise RuntimeError('Cloud output manifest differs from frozen experiment')
    jobs = json.loads(manager.cloud('batch','jobs','list','--location',manager.launch['region'],
                                   '--project',manager.launch['project'],'--format=json'))
    active = [job for job in jobs if job['name'].split('/')[-1].startswith(manager.launch['run_id'])
              and job.get('status',{}).get('state') not in ('FAILED','SUCCEEDED','CANCELLED','DELETION_IN_PROGRESS')]
    if active:
        raise RuntimeError('A matching nonterminal job already exists; inspect before creating a duplicate: '
                           + ', '.join(job['name'] for job in active))
    if not (PLAN / 'STOP_MONITOR').exists():
        raise RuntimeError('Expected local monitor stop marker is missing')
    old_job, old_summary = manager.status()
    if old_job['status']['state'] not in ('FAILED','SUCCEEDED','CANCELLED'):
        raise RuntimeError('Previous job is not terminal')
    if old_job['status']['state'] == 'SUCCEEDED':
        raise RuntimeError('Previous job succeeded; check completion instead of resubmitting')
    job = manager.submit()
    record = {'submitted_at_utc': module.now(), 'job_name': job['name'], 'uid': job.get('uid'),
              'batch_state': job.get('status',{}).get('state'),
              'resumed_run_id': manager.launch['run_id'],
              'verified_checkpoint_trials': verification['verified_committed_trials'],
              'remaining_trials_at_submission': verification['remaining_trials'],
              'source_sha256': manager.launch['source_sha256'], 'config_sha256': manager.launch['config_sha256'],
              'frozen_batch_configuration_unchanged': True, 'local_monitor_enabled': False,
              'task_count':4, 'workers_per_task':8,
              'job_url':'https://console.cloud.google.com/batch/jobsDetail/regions/' + manager.launch['region']
                        + '/jobs/' + job['name'].split('/')[-1] + '?project=' + manager.launch['project']}
    (Path(__file__).parent / 'resume-submission-20261103.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2),flush=True)

if __name__ == '__main__':
    main()
