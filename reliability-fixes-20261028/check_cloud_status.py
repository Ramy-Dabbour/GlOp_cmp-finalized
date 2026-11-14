"""One-shot, read-only cloud status check. Does not start a monitor or job."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import datetime as dt
import json
import os
from pathlib import Path
import ssl
import subprocess
import urllib.parse
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'cloud/replication-20261028/plans/matlab-glop-cmp-20261028-fixes'
launch = json.loads((PLAN / 'launch.json').read_text())
state = json.loads((PLAN / 'controller-state.json').read_text())
stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
out = Path(__file__).parent / ('cloud-status-' + stamp)
out.mkdir()
gcloud = Path(os.environ['LOCALAPPDATA']) / 'Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd'
auth = subprocess.run([str(gcloud), 'auth', 'print-access-token', '--quiet'],
                      capture_output=True, text=True, timeout=90,
                      creationflags=subprocess.CREATE_NO_WINDOW)
if auth.returncode:
    raise RuntimeError(auth.stderr[-2000:])
token = auth.stdout.strip()
context = ssl.create_default_context(cafile=str(gcloud.parent.parent / 'lib/third_party/certifi/cacert.pem'))

def read_json(url, body=None):
    headers = {'Authorization': 'Bearer ' + token}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode()
    request = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(request, context=context, timeout=60) as response:
        return json.load(response)

def object_url(name):
    uri = urllib.parse.urlsplit(launch['run_uri'])
    key = uri.path.strip('/') + '/' + name
    return ('https://storage.googleapis.com/storage/v1/b/' + uri.netloc + '/o/'
            + urllib.parse.quote(key, safe='') + '?alt=media')

resource = ('projects/' + launch['project'] + '/locations/' + launch['region']
            + '/jobs/' + state['current_job'])
job_url = 'https://batch.googleapis.com/v1/' + resource
uid = state['jobs'][-1]['uid']
log_base = 'labels.job_uid="' + uid + '" AND timestamp>="2026-10-28T20:32:00Z"'
checks = {
    'job': (job_url, None),
    'summary': (object_url('live/summary.json'), None),
    'tasks': (job_url + '/taskGroups/group0/tasks?pageSize=100', None),
    'billing_info': ('https://cloudbilling.googleapis.com/v1/projects/' + launch['project'] + '/billingInfo', None),
    'project_info': ('https://cloudresourcemanager.googleapis.com/v3/projects/' + launch['project'], None),
    'compute_instances': ('https://compute.googleapis.com/compute/v1/projects/' + launch['project'] + '/aggregated/instances', None),
    'managed_groups': ('https://compute.googleapis.com/compute/v1/projects/' + launch['project'] + '/regions/' + launch['region'] + '/instanceGroupManagers', None),
    'recent_logs': ('https://logging.googleapis.com/v2/entries:list', {
        'resourceNames': ['projects/' + launch['project']],
        'filter': log_base + ' AND NOT textPayload:"report agent state:" AND NOT textPayload:"Server response for instance"',
        'orderBy': 'timestamp desc', 'pageSize': 20}),
    'error_logs': ('https://logging.googleapis.com/v2/entries:list', {
        'resourceNames': ['projects/' + launch['project']],
        'filter': log_base + ' AND severity>=ERROR',
        'orderBy': 'timestamp desc', 'pageSize': 40}),
    'restore_logs': ('https://logging.googleapis.com/v2/entries:list', {
        'resourceNames': ['projects/' + launch['project']],
        'filter': log_base + ' AND (jsonPayload.event="checkpoint-restored" OR textPayload:"RESUME task" OR textPayload:"Connected to parallel pool")',
        'orderBy': 'timestamp desc', 'pageSize': 50}),
}
for index in range(4):
    checks['last_checkpoint_task_' + str(index)] = ('https://logging.googleapis.com/v2/entries:list', {
        'resourceNames': ['projects/' + launch['project']],
        'filter': log_base + ' AND jsonPayload.event="checkpoint-progress" AND jsonPayload.task_index=' + str(index),
        'orderBy': 'timestamp desc', 'pageSize': 1})
results = {}
with ThreadPoolExecutor(max_workers=5) as pool:
    futures = {pool.submit(read_json, *args): name for name, args in checks.items()}
    for future in as_completed(futures):
        name = futures[future]
        try:
            results[name] = future.result()
        except urllib.error.HTTPError as exc:
            results[name] = {'check_error': str(exc), 'response_body': exc.read().decode('utf-8', errors='replace')[:12000]}
        except Exception as exc:
            results[name] = {'check_error': str(exc)}
        (out / (name + '.json')).write_text(json.dumps(results[name], indent=2) + '\n')

summary = results['summary']
identity_matches = (None if 'check_error' in summary else
                    all(summary.get(k) == launch[k] for k in ('run_id','source_sha256','config_sha256')))
def after_submission(timestamp):
    submitted = results['job'].get('createTime')
    if not timestamp or not submitted:
        return None
    return dt.datetime.fromisoformat(timestamp.replace('Z', '+00:00')) >= dt.datetime.fromisoformat(submitted.replace('Z', '+00:00'))

compact = {
    'checked_utc': dt.datetime.now(dt.timezone.utc).isoformat(),
    'current_job': state['current_job'],
    'summary_updated_after_submission': after_submission(summary.get('updated_at')),
    'evidence_directory': str(out),
    'batch_status': results['job'].get('status', results['job']),
    'identity_matches': identity_matches,
    'summary': {k:v for k,v in summary.items() if k not in ('tasks','latest_trial')},
    'latest_trial': summary.get('latest_trial'),
    'tasks': [{k:v for k,v in task.items() if k not in ('workers','latest_trial','active_ids')}
              for task in summary.get('tasks', [])],
    'batch_tasks': results['tasks'],
    'billing_info': results['billing_info'],
    'project_info': results['project_info'],
    'compute_instances': [{k: instance.get(k) for k in ('name', 'status', 'creationTimestamp', 'labels')}
                          for zone in results['compute_instances'].get('items', {}).values()
                          for instance in zone.get('instances', [])],
    'managed_groups': [{k: group.get(k) for k in ('name', 'targetSize', 'currentActions', 'status')}
                       for group in results['managed_groups'].get('items', [])],
    'check_errors': {name: value for name, value in results.items() if 'check_error' in value},
    'checkpoint_progress': {k: v for k, v in results.items() if k.startswith('last_checkpoint_task_')},
    'restore_logs': results['restore_logs'],
    'error_logs': [{'timestamp': e.get('timestamp'), 'message': e.get('textPayload', e.get('jsonPayload'))}
                   for e in results['error_logs'].get('entries', [])[:8]],
    'recent_logs': [{'timestamp': e.get('timestamp'), 'message': str(e.get('textPayload', e.get('jsonPayload')))[:1200]}
                    for e in results['recent_logs'].get('entries', [])[:8]],
}
(out / 'verification.json').write_text(json.dumps(compact, indent=2) + '\n')
print(json.dumps(compact, indent=2))
