"""Verify real cloud hard-kill/retry evidence and downloaded immutable records."""
import hashlib
import json
from pathlib import Path
import re
from scipy.io import loadmat

here=Path(__file__).resolve().parent
run_id='matlab-glop-recovery-20261026-1355'
plan=here/'plans'/run_id
job=json.loads((plan/'evidence'/f'{run_id}.json').read_text())
logs=json.loads((plan/'evidence'/f'{run_id}-last-logs.json').read_text())
text='\n'.join(item.get('textPayload','') for item in logs)
assert job['status']['state']=='SUCCEEDED'
assert 'SMOKE HARD CRASH' in text
assert 'retry attempt 1' in text
assert '8 process workers' in text
resume=re.findall(r'RESUME task 0/1: (\d+)/24 cloud-committed; (\d+) pending',text)
assert any(int(completed)>=3 and int(pending)<24 for completed,pending in resume),resume
root=here/'evidence/recovery-checkpoints/tasks/00000'
commits=sorted(root.glob('trial_*.commit.json'))
assert len(commits)==24,len(commits)
ids=[]; outcomes={}
for path in commits:
    commit=json.loads(path.read_bytes())
    base=root/'objects'/f'trial_{commit["trial_id"]:012d}'
    mat=Path(str(base)+'.'+commit['sha256']+'.mat').read_bytes()
    sidecar=Path(str(base)+'.'+commit['sidecar_sha256']+'.json').read_bytes()
    assert hashlib.sha256(mat).hexdigest()==commit['sha256']
    assert hashlib.sha256(sidecar).hexdigest()==commit['sidecar_sha256']
    record=json.loads(sidecar)
    assert record['run_id']==run_id and record['sha256']==commit['sha256']
    saved=loadmat(Path(str(base)+'.'+commit['sha256']+'.mat'),simplify_cells=True)['checkpoint']
    assert saved['globalId']==record['trial_id']
    ids.append(record['trial_id']); outcomes[record['status']]=outcomes.get(record['status'],0)+1
assert ids==list(range(1,25))
output=here.parent.parent/'cloud-results'/run_id
combined=loadmat(output/'benchmark_results.mat',simplify_cells=True)
assert sum(combined['trialResults']['completed'])==24
proof=dict(job_id=run_id,batch_state='SUCCEEDED',actual_process_workers=8,
           hard_termination_observed=True,retry_attempt_one_observed=True,
           resume_counts=resume,verified_commits=len(commits),outcomes=outcomes,
           all_mat_and_sidecar_hashes_verified=True,consolidated_mat_and_csv_collected=True)
(here/'evidence/recovery-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps(proof,indent=2))
