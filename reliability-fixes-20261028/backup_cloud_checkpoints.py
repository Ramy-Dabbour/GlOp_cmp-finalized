"""Download and validate committed cloud trials without changing cloud resources."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import base64
import csv
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
import urllib.parse

import numpy as np
import requests
from scipy.io import loadmat, savemat

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'cloud/replication-20261028/plans/matlab-glop-cmp-20261028-fixes'
LAUNCH = json.loads((PLAN / 'launch.json').read_text())
MANIFEST = json.loads((PLAN / 'source/manifest.json').read_text())
BACKUP = ROOT / 'cloud-results' / LAUNCH['run_id'] / 'recovery-backup-20261103'
BACKUP.mkdir(parents=True, exist_ok=True)
GCLOUD = Path(os.environ['LOCALAPPDATA']) / 'Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd'
CA = str(GCLOUD.parent.parent / 'lib/third_party/certifi/cacert.pem')
URI = urllib.parse.urlsplit(LAUNCH['run_uri'])
PREFIX = URI.path.strip('/')
API = 'https://storage.googleapis.com/storage/v1/b/' + URI.netloc + '/o'
IDENTITY = {k: LAUNCH[k] for k in ('run_id', 'source_sha256', 'config_sha256')}
LOCAL = threading.local()
AUTH_LOCK = threading.Lock()
TOKEN = ''
TOKEN_TIME = 0.0

def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def log(message):
    line = '[' + now() + '] ' + message
    print(line, flush=True)
    with (BACKUP / 'backup.log').open('a', encoding='utf-8') as handle:
        handle.write(line + '\n')

def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.download.tmp')
    temporary.write_bytes(data)
    os.replace(temporary, path)

def save_json(name, value):
    atomic(BACKUP / name, (json.dumps(value, indent=2) + '\n').encode())

def token():
    global TOKEN, TOKEN_TIME
    with AUTH_LOCK:
        if not TOKEN or time.monotonic() - TOKEN_TIME > 2400:
            result = subprocess.run([str(GCLOUD), 'auth', 'print-access-token', '--quiet'],
                                    capture_output=True, text=True, timeout=90,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            if result.returncode:
                raise RuntimeError('Google authentication failed: ' + result.stderr[-1500:])
            TOKEN = result.stdout.strip()
            TOKEN_TIME = time.monotonic()
        return TOKEN

def session():
    if not hasattr(LOCAL, 'session'):
        LOCAL.session = requests.Session()
        LOCAL.session.verify = CA
    return LOCAL.session

def get(url, params=None):
    for attempt in range(5):
        try:
            response = session().get(url, params=params, headers={'Authorization': 'Bearer ' + token()}, timeout=(15, 60))
            if response.status_code in (429, 500, 502, 503, 504):
                response.raise_for_status()
            elif not response.ok:
                raise RuntimeError(f'Cloud read failed ({response.status_code}): {response.text[:700]}')
            return response.content
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError):
            if attempt == 4:
                raise
            time.sleep(min(2 ** attempt, 8))

def list_objects(prefix):
    items = []
    params = {'prefix': prefix, 'maxResults': 1000, 'fields': 'items(name,size,generation,md5Hash),nextPageToken'}
    while True:
        page = json.loads(get(API, params))
        items.extend(page.get('items', []))
        if not page.get('nextPageToken'):
            return items
        params['pageToken'] = page['nextPageToken']

def download(item, persist=True):
    name = item['name']
    relative = name.removeprefix(PREFIX + '/')
    target = (BACKUP / relative).resolve()
    if not target.is_relative_to(BACKUP.resolve()):
        raise RuntimeError('Unsafe storage object name')
    def valid(data):
        return (len(data) == int(item['size']) and
                base64.b64encode(hashlib.md5(data).digest()).decode() == item['md5Hash'])
    if target.is_file():
        data = target.read_bytes()
        if not valid(data):
            raise RuntimeError('Existing backup checksum mismatch: ' + relative)
        return data
    data = get(API + '/' + urllib.parse.quote(name, safe=''), {'alt': 'media', 'generation': item['generation']})
    if not valid(data):
        raise RuntimeError('Downloaded object checksum mismatch: ' + relative)
    if persist:
        atomic(target, data)
    return data

def expected_parameters(gid):
    config = MANIFEST['config']
    quotient, repetition = divmod(gid - 1, config['N_tr'])
    values = {}
    for key in ('mziSolvers', 'referenceSolvers', 'firOrders', 'passbandRatios', 'randomSeeds'):
        quotient, index = divmod(quotient, len(config[key]))
        values[key] = config[key][index]
    if quotient:
        raise RuntimeError('Trial ID exceeds frozen experiment')
    return [values[k] for k in ('firOrders','passbandRatios','randomSeeds','referenceSolvers','mziSolvers')] + [repetition + 1]

def verify_trial(commit_item, objects):
    # This marker is written locally only after the full MAT validation below.
    # Re-check the original cloud checksums on retries, while reusing that MAT check.
    already_verified = (BACKUP / commit_item['name'].removeprefix(PREFIX + '/')).is_file()
    commit_bytes = download(commit_item, persist=False)
    commit = json.loads(commit_bytes)
    gid = commit['trial_id']
    index = (gid - 1) % LAUNCH['task_count']
    for key, value in IDENTITY.items():
        if commit.get(key) != value:
            raise RuntimeError(f'Trial {gid}: commit identity mismatch')
    if commit.get('task_index') != index or commit.get('task_count') != LAUNCH['task_count']:
        raise RuntimeError(f'Trial {gid}: incorrect shard')
    base = PREFIX + f'/checkpoints/tasks/{index:05d}/'
    if commit_item['name'] != base + f'trial_{gid:012d}.commit.json':
        raise RuntimeError(f'Trial {gid}: commit path mismatch')
    mat_name = base + f'objects/trial_{gid:012d}.{commit["sha256"]}.mat'
    side_name = base + f'objects/trial_{gid:012d}.{commit["sidecar_sha256"]}.json'
    mat_data, side_data = download(objects[mat_name]), download(objects[side_name])
    if hashlib.sha256(mat_data).hexdigest() != commit['sha256'] or hashlib.sha256(side_data).hexdigest() != commit['sidecar_sha256']:
        raise RuntimeError(f'Trial {gid}: SHA-256 mismatch')
    sidecar = json.loads(side_data)
    if any(sidecar.get(k) != v for k,v in IDENTITY.items()) or sidecar.get('trial_id') != gid or sidecar.get('completed') is not True:
        raise RuntimeError(f'Trial {gid}: sidecar identity/completion mismatch')
    if sidecar.get('status') not in ('succeeded', 'nonconverged', 'failed'):
        raise RuntimeError(f'Trial {gid}: invalid outcome')
    expected = np.asarray(expected_parameters(gid))
    if not np.array_equal(np.asarray(sidecar['parameters']).ravel(), expected):
        raise RuntimeError(f'Trial {gid}: JSON parameter mismatch')
    if not already_verified:
        checkpoint = loadmat(io.BytesIO(mat_data), struct_as_record=False, squeeze_me=True)['checkpoint']
        if int(checkpoint.globalId) != gid or not np.array_equal(np.asarray(checkpoint.parameters).ravel(), expected):
            raise RuntimeError(f'Trial {gid}: MAT trial/parameter mismatch')
        if bool(checkpoint.success) != sidecar['success'] or str(checkpoint.status) != sidecar['status']:
            raise RuntimeError(f'Trial {gid}: MAT/JSON outcome mismatch')
        if sidecar['status'] != 'failed' and not (hasattr(checkpoint.result, 'referenceResult') and hasattr(checkpoint.result, 'mziResult')):
            raise RuntimeError(f'Trial {gid}: full optimization result missing')
        atomic(BACKUP / commit_item['name'].removeprefix(PREFIX + '/'), commit_bytes)
    return sidecar

def main():
    start = time.monotonic()
    log('Starting read-only backup and integrity validation; cloud computation is not started by this script.')
    source_prefix = urllib.parse.urlsplit(LAUNCH['source_uri']).path.strip('/')
    remote_manifest = get(API + '/' + urllib.parse.quote(source_prefix + '/manifest.json', safe=''), {'alt': 'media'})
    if remote_manifest != (PLAN / 'source/manifest.json').read_bytes():
        raise RuntimeError('Remote source manifest differs from approved frozen source')
    atomic(BACKUP / 'source-manifest.json', remote_manifest)
    for name, digest in MANIFEST['files'].items():
        path = PLAN / 'source' / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise RuntimeError('Local frozen source changed: ' + name)
    with ThreadPoolExecutor(max_workers=4) as pool:
        groups = list(pool.map(list_objects, [PREFIX + f'/checkpoints/tasks/{i:05d}/' for i in range(4)]))
    items = [item for group in groups for item in group]
    save_json('remote-object-index.json', items)
    objects = {item['name']: item for item in items}
    commits = [item for item in items if re.search(r'/trial_\d{12}\.commit\.json$', item['name'])]
    log(f'Found {len(commits)} committed trials and {len(items)} checkpoint objects.')
    save_json('progress.json', {'status': 'downloading', 'total_commits': len(commits), 'verified_trials': 0, 'updated_at': now()})
    records, errors = [], []
    last_report = time.monotonic()
    with ThreadPoolExecutor(max_workers=48) as pool:
        futures = {pool.submit(verify_trial, item, objects): item['name'] for item in commits}
        for future in as_completed(futures):
            try:
                records.append(future.result())
            except Exception as exc:
                errors.append({'object': futures[future], 'error': str(exc)})
                if len(errors) <= 5:
                    log('CHECK FAILED: ' + str(exc))
            if time.monotonic() - last_report >= 25:
                log(f'Validated {len(records)}/{len(commits)} complete trials; errors={len(errors)}; elapsed={time.monotonic()-start:.0f}s.')
                save_json('progress.json', {'status': 'downloading', 'total_commits': len(commits), 'verified_trials': len(records), 'errors': len(errors), 'updated_at': now()})
                last_report = time.monotonic()
    for retry_pass in range(2):
        if not errors:
            break
        log(f'Retrying {len(errors)} incomplete downloads, pass {retry_pass + 1}.')
        retry_items = [objects[error['object']] for error in errors]
        errors = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = {pool.submit(verify_trial, item, objects): item['name'] for item in retry_items}
            for future in as_completed(futures):
                try:
                    records.append(future.result())
                except Exception as exc:
                    errors.append({'object': futures[future], 'error': str(exc)})
    if errors:
        save_json('verification-errors.json', errors)
        raise RuntimeError(f'{len(errors)} checkpoint integrity/download errors; do not resume until resolved.')
    records.sort(key=lambda row: row['trial_id'])
    if len({r['trial_id'] for r in records}) != len(records):
        raise RuntimeError('Duplicate trial IDs')
    fields = [k for k in records[0] if k != 'parameters'] + ['fir_order','passband_ratio','seed','reference_solver','mzi_solver','repetition']
    csv_path = BACKUP / 'completed_trials.csv'
    with csv_path.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            row = {k:v for k,v in record.items() if k != 'parameters'}
            row.update(zip(fields[-6:], record['parameters']))
            writer.writerow(row)
    arrays = {}
    for key in records[0]:
        values = [r.get(key) for r in records]
        if key == 'parameters':
            arrays[key] = np.asarray(values, dtype=float)
        elif all(v is None or isinstance(v, (int, float, bool)) for v in values):
            arrays[key] = np.asarray([np.nan if v is None else v for v in values]).reshape(-1,1)
        else:
            arrays[key] = np.asarray(['' if v is None else v for v in values], dtype=object).reshape(-1,1)
    savemat(BACKUP / 'completed_trials.mat', {'trialResults': arrays, 'config': MANIFEST['config'], 'runIdentity': IDENTITY}, do_compression=True)
    log('Retrieving existing MAT/CSV/log exports.')
    artifacts = list_objects(PREFIX + '/artifacts/')
    exports = [item for item in artifacts if Path(item['name']).suffix.lower() in ('.mat','.csv','.log','.txt','.out','.err')]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(download, exports))
    save_json('artifact-object-index.json', exports)
    summary = {'verified_at_utc': now(), **IDENTITY, 'all_checks_passed': True,
               'verified_committed_trials': len(records), 'total_trials': 77760,
               'remaining_trials': 77760-len(records),
               'by_task': dict(sorted(Counter((r['trial_id']-1)%4 for r in records).items())),
               'outcomes': dict(Counter(r['status'] for r in records)),
               'checkpoint_objects_listed': len(items), 'downloaded_export_files': len(exports),
               'source_manifest_matches': True, 'full_mat_results_verified': True,
               'checks': ['GCS object MD5 and size', 'MAT and sidecar SHA-256', 'run/source/config identities',
                          'shard assignment and unique trial IDs', 'frozen-grid parameters', 'MAT readability',
                          'MAT/JSON outcomes and complete optimization results'],
               'elapsed_seconds': time.monotonic()-start, 'backup_directory': str(BACKUP)}
    save_json('verification.json', summary)
    save_json('progress.json', {'status':'completed', **summary})
    log('BACKUP COMPLETE: ' + json.dumps(summary))

if __name__ == '__main__':
    main()
