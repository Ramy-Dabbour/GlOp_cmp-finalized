"""Check the new peer feedback against the frozen, previously reconstructed prefix.

Reads audit data and original exception records; writes only this review folder.
Does not execute MATLAB, run optimizers, or touch live benchmark outputs.
"""
import csv
import datetime as dt
import hashlib
import json
import math
import statistics
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SOURCE = ROOT / 'review/peer-feedback-20261026/checkpoint-reconstruction.csv'
all_rows = list(csv.DictReader(SOURCE.open(encoding='utf-8', newline='')))
rows = [r for r in all_rows if int(r['id']) <= 4947]
assert sorted(int(r['id']) for r in rows) == list(range(1, 4948))
returned = [r for r in rows if r['has_stage2'] == '1']
assert len(returned) == 4938
assert all(r['stage1_isValidSolution'] == '1.0' and
           r['stage2_isValidSolution'] == '1.0' and
           math.isfinite(float(r['recovered_error'])) for r in returned)


def table(column):
    result = []
    for solver in sorted({r[column] for r in returned}):
        subset = [r for r in returned if r[column] == solver]
        errors = [float(r['recovered_error']) for r in subset]
        seconds = [float(r['stage2_elapsedSeconds']) for r in subset]
        result.append(dict(solver=solver, returned=len(subset),
                           mean_end_to_end_error=statistics.mean(errors),
                           median_end_to_end_error=statistics.median(errors),
                           mean_stage2_seconds=statistics.mean(seconds),
                           median_stage2_seconds=statistics.median(seconds)))
    return result


def topology_bound_squared(order, rho):
    harmonics = [2 * math.sin(math.pi * rho * k) / (math.pi * k)
                 for k in range(1, order + 1)]
    denominator = 2 * (rho**2 + (1 - rho)**2 + sum(t*t for t in harmonics))
    return (4*(0.5-rho)**2 + 2*sum(t*t for t in harmonics[1::2])) / denominator


old = json.loads((ROOT / 'review/peer-feedback-20261026/checkpoint-audit-summary.json').read_text())
exceptions = []
for record in old['exception_evidence']:
    path = ROOT / record['file']
    raw = json.loads(path.read_text(encoding='utf-8-sig'))['result']
    assert raw['failureIdentifier'] == record['identifier']
    exceptions.append(dict(trial_id=record['id'], identifier=raw['failureIdentifier'],
                           message=raw['failureMessage'], file=str(path),
                           file_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
assert {e['trial_id'] for e in exceptions} == {
    int(r['id']) for r in rows if r['has_stage2'] != '1'}

pareto = Path('C:/Program Files/MATLAB/R2026a/toolbox/globaloptim/+globaloptim/+paretosearch/checkConvergence.m')
code = pareto.read_text()
assert 'elseif optimState.numberOfObjectives == 1' in code
scalar_branch = code.split('function hasConverged = testSinglobjStopping()', 1)[1].split('function multiobjIterUpdates()', 1)[0]
assert 'EXITFLAG = 1;' in scalar_branch

report = dict(
    verified_at_utc=dt.datetime.now(dt.timezone.utc).isoformat(),
    source_csv=str(SOURCE), source_csv_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
    selection='Global trial IDs 1..4947 inclusive; all returned valid Stage-2 results; no exit-flag filter.',
    trials=len(rows), returned_stage2=len(returned),
    legacy_successes=sum(int(r['success']) for r in rows),
    returned_nonsuccesses=sum(r['success'] == '0' for r in returned),
    stage2_groups=table('mzi_solver'), stage1_groups=table('reference_solver'),
    minimum_squared_error_above_bound=min(float(r['recovered_error'])**2-
        topology_bound_squared(int(r['order']), float(r['ratio'])) for r in returned),
    topology_bounds=[dict(order=n, rho=rho, bound=math.sqrt(topology_bound_squared(n, rho)))
                     for rho in (0.2, 0.3, 0.4, 0.5) for n in range(4, 13)],
    exceptions=exceptions,
    paretosearch=dict(path=str(pareto), sha256=hashlib.sha256(pareto.read_bytes()).hexdigest(),
                     scalar_convergence_branch_verified=True,
                     runtime_success_demonstration_performed=False),
    limitations=['Incomplete, unbalanced rho=0.2, seed=0 prefix; diagnostic rather than final comparison.',
                 'Times describe returned Stage-2 solves under existing desktop concurrency.',
                 'The peer\'s updated outline/archive was not supplied; the pasted feedback was assessed.'])
(HERE / 'feedback-verification.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
print(json.dumps({k: report[k] for k in ('trials', 'returned_stage2', 'legacy_successes',
                                       'returned_nonsuccesses', 'minimum_squared_error_above_bound',
                                       'stage2_groups', 'stage1_groups')}, indent=2))
