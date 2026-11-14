"""Prepare the authorized replacement; never submit a job or import old results."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil

ROOT = Path(__file__).resolve().parent.parent
EVIDENCE = Path(__file__).resolve().parent
OLD = ROOT / 'cloud/replication-20261026'
OLD_SOURCE = OLD / 'plans/matlab-glop-cmp-20261026-1405/source'
NEW = ROOT / 'cloud/replication-20261028'
RUN_ID = 'matlab-glop-cmp-20261028-fixes'
ANALYSIS = Path(r'C:\Users\Dell\Documents\analysis_pkg')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare():
    old_manifest = json.loads((OLD_SOURCE / 'manifest.json').read_text())
    stage = EVIDENCE / 'replacement-source'
    stage.mkdir(exist_ok=False)
    replacements = {'+fpf/TrialReporter.m', '+fpf/writeLiveJson.m', '+fpf/complexHarmonicExtrema.m'}
    for name, expected in old_manifest['files'].items():
        source = OLD_SOURCE / name
        assert sha(source) == expected, name
        destination = stage / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name if name in replacements else source, destination)
    shutil.copy2(ROOT / 'tests/telemetryRobustnessTest.m', stage / 'tests/telemetryRobustnessTest.m')
    uploader = stage / 'cloud/durable_uploader.py'
    raw = uploader.read_bytes()
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = raw.decode().replace('\r\n', '\n')
    before = ('                    worker_json = path.suffix.lower() == ".json" and path.parent.name == "workers"\n'
              '                    if path.is_file() and (worker_json or path.suffix.lower() in {".mat", ".csv", ".log", ".txt", ".out", ".err"}):')
    after = ('                    live_json = path.suffix.lower() == ".json" and path.parent.name in {"workers", "trials"}\n'
             '                    if path.is_file() and (live_json or path.suffix.lower() in {".mat", ".csv", ".log", ".txt", ".out", ".err"}):')
    assert text.count(before) == 1
    uploader.write_bytes(text.replace(before, after, 1).replace('\n', newline).encode())
    spec = importlib.util.spec_from_file_location('original_builder', OLD / 'build_replication.py')
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    builder.HERE = NEW
    builder.PARENT_JOB = 'matlab-glop-cmp-20261026-1405'
    builder.source_files = lambda: ((p.relative_to(stage).as_posix(), p) for p in sorted(stage.rglob('*')) if p.is_file() and p.suffix in {'.m', '.py'})
    plan = builder.build(RUN_ID, 'production', 4)
    job_file = plan / 'batch.json'
    job = json.loads(job_file.read_text())
    job['labels']['matlab_replication'] = '20261028'
    job['labels']['matlab_reliability_fixes'] = 'true'
    job_file.write_text(json.dumps(job, indent=2) + '\n', encoding='utf-8')
    analysis = plan / 'analysis'
    analysis.mkdir()
    for name in ('fpf_analysis.py', 'README_analysis.md', 'analysis_plan.json'):
        shutil.copy2(ANALYSIS / name, analysis / name)
    manifest = json.loads((plan / 'source/manifest.json').read_text())
    changed = sorted(name for name in old_manifest['files'] if manifest['files'].get(name) != old_manifest['files'][name])
    added = sorted(set(manifest['files']) - set(old_manifest['files']))
    assert changed == sorted([*replacements, 'cloud/durable_uploader.py']), changed
    assert added == ['tests/telemetryRobustnessTest.m'], added
    assert manifest['config_sha256'] == old_manifest['config_sha256']
    original_job = json.loads((OLD / 'plans/matlab-glop-cmp-20261026-1405/batch.json').read_text())
    assert job['allocationPolicy'] == original_job['allocationPolicy']
    assert job['taskGroups'][0]['taskSpec']['computeResource'] == original_job['taskGroups'][0]['taskSpec']['computeResource']
    task = job['taskGroups'][0]['taskSpec']
    assert task['maxRetryCount'] == 10
    assert 'maxRunDuration' not in task
    assert all('timeout' not in r for r in task['runnables'])
    record = dict(run_id=RUN_ID, plan=str(plan), source_sha256=manifest['source_sha256'],
                  config_sha256=manifest['config_sha256'], changed_source_files=changed,
                  added_source_files=added, task_count=4, workers_per_task=8, total_trials=77760,
                  analysis_sha256={p.name: sha(p) for p in analysis.iterdir()},
                  old_results_imported=False, custom_computation_timeout=False,
                  original_resources_unchanged=True)
    (EVIDENCE / 'replacement-preparation.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    prepare()
