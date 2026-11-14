"""Create and verify a read-only archive of the stopped desktop benchmark."""
from pathlib import Path
import base64
import csv
import datetime as dt
import hashlib
import json
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
state = json.loads((ROOT/'local-results/state.json').read_text())
assert state['status'] == 'stopped' and (ROOT/'local-results/STOP').exists()
checkpoints = sorted((ROOT/'local-results/checkpoints').glob('trial_*.mat'))
local_ids = {int(p.stem.split('_')[1]) for p in checkpoints}
assert len(local_ids) == state['completed_trials'] == 5182
cloud_csv = ROOT/'cloud-results/matlab-glop-cmp-20261026-1405/trial_results.csv'
with cloud_csv.open(encoding='utf-8-sig', newline='') as handle:
    cloud_rows = list(csv.DictReader(handle))
cloud_complete = {int(r['trial_id']) for r in cloud_rows
                  if r['completed'].lower() in ('1','true')}
assert local_ids <= cloud_complete

files = [p for p in (ROOT/'local-results').rglob('*') if p.is_file()
         and p.suffix.lower() not in ('.lock','.tmp')]
files += [ROOT/'benchmark_results.mat',ROOT/'benchmark_results.csv',ROOT/'main.m']
files += sorted((ROOT/'+fpf').glob('*.m'))
files += [ROOT/'scripts/LOCAL-BENCHMARK.md',ROOT/'scripts/local-benchmark.ps1',
          ROOT/'scripts/local-benchmark.cmd',
          ROOT/'review/peer-feedback-20261027/PAPER-MODEL-CLARIFICATION.md']
files = sorted(set(files))
inventory = []
for path in files:
    data = path.read_bytes()
    inventory.append(dict(path=path.relative_to(ROOT).as_posix(), bytes=len(data),
                          sha256=hashlib.sha256(data).hexdigest()))
manifest = dict(schema_version=1, created_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
    desktop_manifest_id=state['manifest_id'], desktop_state=state,
    completed_trials=len(local_ids), total_uncompressed_bytes=sum(r['bytes'] for r in inventory),
    excluded='Transient .lock and .tmp files only; source and preserved result/history files included.',
    cloud_overlap=dict(run_id='matlab-glop-cmp-20261026-1405',
        source_csv=str(cloud_csv.relative_to(ROOT)),
        source_csv_sha256=hashlib.sha256(cloud_csv.read_bytes()).hexdigest(),
        snapshot_modified_at_utc=dt.datetime.fromtimestamp(cloud_csv.stat().st_mtime,dt.timezone.utc).isoformat(),
        completed_in_snapshot=len(cloud_complete),desktop_ids_already_complete=len(local_ids&cloud_complete),
        desktop_ids_missing=sorted(local_ids-cloud_complete)),
    purpose='Preserve original desktop results and provenance as a separate backup. Not a checkpoint import or replacement of cloud records.',
    files=inventory)
archive = HERE/'glop-desktop-5182-trials-20261028.zip'
assert not archive.exists(), 'Archive already exists; do not replace a prepared upload.'
with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
    for item,path in zip(inventory,files):
        data=path.read_bytes()
        assert hashlib.sha256(data).hexdigest()==item['sha256'],f'File changed: {path}'
        z.writestr(item['path'],data)
    z.writestr('BACKUP-MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for item in inventory:
        assert hashlib.sha256(z.read(item['path'])).hexdigest()==item['sha256']
data=archive.read_bytes()
evidence=dict(archive=str(archive),archive_bytes=len(data),
    archive_sha256=hashlib.sha256(data).hexdigest(),
    archive_md5_base64=base64.b64encode(hashlib.md5(data).digest()).decode(),
    archive_md5_hex=hashlib.md5(data).hexdigest(),
    archived_files=len(inventory)+1,completed_trials=len(local_ids),
    every_archived_file_sha256_verified=True,cloud_overlap=manifest['cloud_overlap'])
(HERE/'backup-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(HERE/'backup-verification.json').write_text(json.dumps(evidence,indent=2)+'\n')
(HERE/(archive.name+'.sha256.txt')).write_text(evidence['archive_sha256']+'  '+archive.name+'\n')
print(json.dumps(evidence,indent=2))
