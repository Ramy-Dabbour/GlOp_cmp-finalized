"""Read-only integrity checks for one committed trial from each cloud task."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import io
import json
import ssl
import subprocess
import urllib.parse
import urllib.request
import scipy.io
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PLAN = ROOT / 'cloud/replication-20261028/plans/matlab-glop-cmp-20261028-fixes'
GCLOUD = Path(r'C:\Users\Dell\AppData\Local\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd')
LAUNCH = json.loads((PLAN / 'launch.json').read_text())
URI = urllib.parse.urlsplit(LAUNCH['run_uri'])
PREFIX = URI.path.strip('/')
BUCKET = URI.netloc
TOKEN = subprocess.run([str(GCLOUD), 'auth', 'print-access-token', '--quiet'],
                       capture_output=True, text=True, check=True, timeout=120).stdout.strip()
CA = GCLOUD.parent.parent / 'lib/third_party/certifi/cacert.pem'
CONTEXT = ssl.create_default_context(cafile=str(CA))
API = 'https://storage.googleapis.com/storage/v1/b/' + urllib.parse.quote(BUCKET, safe='') + '/o'


def request(url):
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + TOKEN})
    with urllib.request.urlopen(req, context=CONTEXT, timeout=60) as response:
        return response.read()


def get(name):
    return request(API + '/' + urllib.parse.quote(name, safe='') + '?alt=media')


def first_trial_json(index):
    prefix = PREFIX + f'/artifacts/tasks/{index:05d}/results/live/'
    params = dict(prefix=prefix, maxResults=100, fields='items(name),nextPageToken')
    while True:
        page = json.loads(request(API + '?' + urllib.parse.urlencode(params)))
        for item in page.get('items', []):
            name = item['name']
            if '/trials/trial_' in name and name.endswith('.json'):
                return name
        if not page.get('nextPageToken'):
            raise AssertionError(f'No exported trial JSON for task {index}')
        params['pageToken'] = page['nextPageToken']


def verify_task(index):
    name = first_trial_json(index)
    live_bytes = get(name)
    live = json.loads(live_bytes)
    gid = int(live['global_trial_id'])
    assert (gid - 1) % 4 == index
    base = PREFIX + f'/checkpoints/tasks/{index:05d}/'
    commit_name = base + f'trial_{gid:012d}.commit.json'
    commit_bytes = get(commit_name)
    commit = json.loads(commit_bytes)
    for key in ('run_id', 'source_sha256', 'config_sha256'):
        assert commit[key] == LAUNCH[key], (index, key)
    assert commit['trial_id'] == gid and commit['task_index'] == index and commit['task_count'] == 4
    mat_name = base + f'objects/trial_{gid:012d}.{commit["sha256"]}.mat'
    sidecar_name = base + f'objects/trial_{gid:012d}.{commit["sidecar_sha256"]}.json'
    mat_bytes = get(mat_name)
    sidecar_bytes = get(sidecar_name)
    assert hashlib.sha256(mat_bytes).hexdigest() == commit['sha256']
    assert hashlib.sha256(sidecar_bytes).hexdigest() == commit['sidecar_sha256']
    sidecar = json.loads(sidecar_bytes)
    assert sidecar['completed'] and sidecar['trial_id'] == gid
    checkpoint = scipy.io.loadmat(io.BytesIO(mat_bytes), struct_as_record=False, squeeze_me=True)['checkpoint']
    assert int(checkpoint.globalId) == gid
    assert np.array_equal(np.asarray(checkpoint.parameters).ravel(), np.asarray(live['parameters']).ravel())
    assert bool(checkpoint.success) == bool(live['result']['success'])
    assert hasattr(checkpoint.result, 'referenceResult') and hasattr(checkpoint.result, 'mziResult')
    output = HERE / 'remote-checkpoint-samples' / f'{index:05d}'
    output.mkdir(parents=True, exist_ok=True)
    (output / 'checkpoint.mat').write_bytes(mat_bytes)
    (output / 'commit.json').write_bytes(commit_bytes)
    (output / 'sidecar.json').write_bytes(sidecar_bytes)
    (output / 'trial.json').write_bytes(live_bytes)
    return dict(task_index=index, trial_id=gid, mat_bytes=len(mat_bytes), json_bytes=len(live_bytes),
                commit_uri='gs://' + BUCKET + '/' + commit_name,
                exported_json_uri='gs://' + BUCKET + '/' + name,
                hashes_match=True, mat_readable=True, full_result_present=True,
                json_parameters_and_outcome_match=True)


source_prefix = urllib.parse.urlsplit(LAUNCH['source_uri']).path.strip('/')
manifest = get(source_prefix + '/manifest.json')
assert manifest == (PLAN / 'source/manifest.json').read_bytes()
analysis = get('runs/' + LAUNCH['run_id'] + '/analysis/analysis_plan.json')
assert analysis == (PLAN / 'analysis/analysis_plan.json').read_bytes()
with ThreadPoolExecutor(max_workers=4) as pool:
    tasks = list(pool.map(verify_task, range(4)))
record = dict(verified_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(), run_id=LAUNCH['run_id'],
              remote_source_manifest_matches=True, remote_approved_analysis_plan_matches=True,
              tasks=tasks, all_checks_passed=True)
(HERE / 'remote-storage-verification.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
print(json.dumps(record, indent=2))
