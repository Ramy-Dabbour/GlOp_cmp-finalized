"""Cross-check the completed local GlOp_cmp archive without network access."""
import csv
import hashlib
import io
import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from scipy.io import loadmat

import backup_cloud_checkpoints as backup


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    folder = backup.BACKUP.parent / 'final'
    progress = json.loads((folder / 'transfer-progress.json').read_bytes())
    inventory = json.loads((folder / 'bucket-object-index.json').read_bytes())
    require(progress['status'] == 'transfer_complete' and
            progress['verified_objects'] == len(inventory), 'Transfer verification is incomplete')
    summary = json.loads((folder / 'live/summary.json').read_bytes())
    manifest = json.loads((folder / 'manifest.json').read_bytes())
    require(manifest == backup.MANIFEST, 'Frozen manifest mismatch')
    require(all(summary[k] == v for k, v in backup.IDENTITY.items()), 'Run identity mismatch')
    total = summary['total_trials']
    require(summary['status'] == 'completed' and total == summary['completed_trials'] ==
            summary['published_trials'] == 77760, 'Cloud completion totals mismatch')
    diag_paths = {}
    prefix = backup.PREFIX + '/'
    for obj in inventory:
        name = obj['name']
        found = re.search(r'/trials/trial_(\d{12})\.json$', name)
        if found:
            gid = int(found[1])
            require(gid not in diag_paths, f'Trial {gid} has duplicate diagnostic files')
            diag_paths[gid] = folder / name.removeprefix(prefix)
    grid = set(range(1, total + 1))
    require(set(diag_paths) <= grid, 'Diagnostic trial ID outside the experiment')
    missing_diagnostics = sorted(grid - set(diag_paths))
    with (folder / 'trial_results.csv').open(encoding='utf-8-sig', newline='') as stream:
        rows = list(csv.DictReader(stream))
    require(len(rows) == total and all(int(r['trial_id']) == i and r['completed'] == '1'
            for i, r in enumerate(rows, 1)), 'Combined results are incomplete or out of order')
    outcomes = Counter(row['status'] for row in rows)
    for key in ('succeeded', 'nonconverged', 'failed'):
        require(outcomes[key] == summary[key + '_trials'], f'Outcome total mismatch: {key}')
    combined = loadmat(folder / 'benchmark_results.mat', struct_as_record=False, squeeze_me=True)
    trials = combined['trialResults']
    require(np.array_equal(np.ravel(trials.trial_id), np.arange(1, total + 1)) and
            np.all(np.ravel(trials.completed) == 1) and
            np.array_equal(np.ravel(trials.success), [int(row['success']) for row in rows]) and
            all(getattr(combined['runIdentity'], k) == v for k, v in backup.IDENTITY.items()),
            'Combined MAT identity, completion, or success flags differ from CSV')
    task_count = manifest['task_count']

    def verify_shard(task):
        base = folder / 'checkpoints/tasks' / f'{task:05d}'
        count = 0
        for gid in range(task + 1, total + 1, task_count):
            stem = f'trial_{gid:012d}'
            commit = json.loads((base / (stem + '.commit.json')).read_bytes())
            require(commit['trial_id'] == gid and commit['task_index'] == task and
                    commit['task_count'] == task_count, f'Trial {gid}: commit identity')
            require(all(commit[k] == v for k, v in backup.IDENTITY.items()), f'Trial {gid}: commit manifest')
            def read_object(key, extension):
                digest = commit[key]
                require(re.fullmatch(r'[a-f0-9]{64}', digest), f'Trial {gid}: invalid digest')
                data = (base / 'objects' / f'{stem}.{digest}.{extension}').read_bytes()
                require(hashlib.sha256(data).hexdigest() == digest, f'Trial {gid}: {extension} checksum')
                return data
            side = json.loads(read_object('sidecar_sha256', 'json'))
            mat = loadmat(io.BytesIO(read_object('sha256', 'mat')), variable_names=['checkpoint'],
                          struct_as_record=False, squeeze_me=True)['checkpoint']
            expected = backup.expected_parameters(gid)
            row = rows[gid - 1]
            require(all(side[k] == v for k, v in backup.IDENTITY.items()) and side['completed'] is True
                    and side['trial_id'] == int(mat.globalId) == gid, f'Trial {gid}: checkpoint identity')
            require(side['parameters'] == expected and
                    np.array_equal(np.ravel(mat.parameters), expected), f'Trial {gid}: grid parameters')
            require(row['status'] == side['status'] == str(mat.status)
                    and bool(int(row['success'])) == side['success'] == bool(mat.success),
                    f'Trial {gid}: outcome mismatch')
            require(hasattr(mat.result, 'referenceResult') and hasattr(mat.result, 'mziResult'),
                    f'Trial {gid}: missing optimizer results')
            if gid in diag_paths:
                diagnostic = json.loads(diag_paths[gid].read_bytes())
                require(diagnostic['global_trial_id'] == gid and diagnostic['parameters'] == expected
                        and diagnostic['status'] == side['status'], f'Trial {gid}: diagnostic mismatch')
            count += 1
            if count % 5000 == 0:
                print(f'Shard {task}: checked {count} trial records', flush=True)
        return count

    with ThreadPoolExecutor(max_workers=task_count) as pool:
        per_shard = list(pool.map(verify_shard, range(task_count)))
    verify = {
        **backup.IDENTITY,
        'verified_at_utc': backup.now(),
        'bucket_output': backup.LAUNCH['run_uri'],
        'all_checks_passed': True,
        'bucket_objects_checked_against_size_and_md5': len(inventory),
        'bucket_bytes': sum(int(o['size']) for o in inventory),
        'completed_trials': total,
        'outcomes': {k: outcomes[k] for k in ('succeeded', 'nonconverged', 'failed')},
        'trials_with_mat_sidecar_and_commit': sum(per_shard),
        'original_supplementary_trial_diagnostics': len(diag_paths),
        'trial_ids_with_no_supplementary_diagnostic_in_bucket': missing_diagnostics,
        'checkpoint_mat_and_sidecar_sha256_and_contents_checked': True,
        'checked_per_task': per_shard,
        'combined_file_sha256': {
            name: hashlib.sha256((folder / name).read_bytes()).hexdigest()
            for name in ('trial_results.csv', 'benchmark_results.mat', 'benchmark_summary.csv')
        },
    }
    backup.atomic(folder / 'verification.json', (json.dumps(verify, indent=2) + '\n').encode())
    print(json.dumps(verify), flush=True)


if __name__ == '__main__':
    main()
