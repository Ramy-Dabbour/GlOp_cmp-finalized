"""Read immutable checkpoints only. No solver calls or benchmark output changes."""
from pathlib import Path
import csv
import json
import math
from collections import Counter, defaultdict
import numpy as np
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
NAMES = ['ga', 'particleswarm', 'surrogateopt', 'simulannealbnd', 'patternsearch', 'paretosearch']

def refmatrix(raw, lagcount):
    positive = np.zeros(lagcount-1)
    positive[:len(raw)-1] = raw[1:]/2
    direct = np.r_[raw[0], positive, positive[::-1]]
    cross = -direct.copy()
    cross[0] += 1
    return np.vstack([direct, cross, cross, direct])

rows=[]
files=sorted((ROOT/'local-results/checkpoints').glob('trial_*.mat'))
for index, path in enumerate(files):
    c=loadmat(path, simplify_cells=True)['checkpoint']
    r=c['result']; s1=r.get('referenceResult'); s2=r.get('mziResult')
    has1=isinstance(s1, dict); has2=isinstance(s2, dict)
    row={
        'id':int(c['globalId']), 'completed_at':c['completedAt'], 'success':int(c['success']),
        'order':int(r['firOrder']), 'ratio':float(r['passbandRatio']), 'seed':int(r['randomSeed']),
        'reference_solver':NAMES[int(r['referenceSolver'])], 'mzi_solver':NAMES[int(r['mziSolver'])],
        'checkpoint_error':float(c['error']), 'checkpoint_evaluations':float(c['evaluations']),
        'result_completed':int(r['completed']), 'has_stage1':int(has1), 'has_stage2':int(has2),
    }
    for stage, result, present in [(1,s1,has1),(2,s2,has2)]:
        for field in ['exitFlag','isValidSolution','objectiveValue']:
            row[f'stage{stage}_{field}']=float(result[field]) if present else math.nan
        for field in ['functionEvaluations','elapsedSeconds']:
            row[f'stage{stage}_{field}']=float(result['metrics'][field]) if present else math.nan
    row['recovered_error']=math.nan
    row['reference_error_common_metric']=math.nan
    row['stage2_error_common_denominator']=math.nan
    row['decomposition_cross_term']=math.nan
    row['stage1_recomputed_objective']=math.nan
    row['recovered_evaluations']=math.nan
    row['stages_elapsed_seconds']=math.nan
    row['max_dc_offset_from_half']=math.nan
    row['max_even_lag_coefficient']=math.nan
    if has1:
        raw=np.asarray(r['rawSincReference']); x=np.asarray(s1['x'])
        row['stage1_recomputed_objective']=float(np.linalg.norm(x-raw)/np.linalg.norm(raw))
    if has1 and has2:
        actual=np.asarray(s2['realizedCoefficientMatrix'])
        lagcount=(actual.shape[1]+1)//2
        rawmat=refmatrix(raw,lagcount)
        xmat=refmatrix(x,lagcount)
        denom=np.linalg.norm(rawmat)
        row['recovered_error']=float(np.linalg.norm(actual-rawmat)/denom)
        row['reference_error_common_metric']=float(np.linalg.norm(xmat-rawmat)/denom)
        row['stage2_error_common_denominator']=float(np.linalg.norm(actual-xmat)/denom)
        row['decomposition_cross_term']=float(2*np.vdot(xmat-rawmat, actual-xmat).real/denom**2)
        row['recovered_evaluations']=float(s1['metrics']['functionEvaluations']+s2['metrics']['functionEvaluations'])
        row['stages_elapsed_seconds']=float(s1['metrics']['elapsedSeconds']+s2['metrics']['elapsedSeconds'])
        row['max_dc_offset_from_half']=float(np.max(np.abs(actual[:,0]-.5)))
        row['max_even_lag_coefficient']=float(np.max(np.abs(actual[:,2:lagcount:2])))
    rows.append(row)
    if (index+1)%1000==0: print(f'Read {index+1}/{len(files)} immutable checkpoints',flush=True)

with (OUT/'checkpoint-reconstruction.csv').open('w',newline='',encoding='utf-8') as f:
    w=csv.DictWriter(f, fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)

def summary(selected):
    result={'count':len(selected),'id_min':min(r['id'] for r in selected),'id_max':max(r['id'] for r in selected),
        'successful':sum(r['success'] for r in selected),
        'failed':sum(not r['success'] for r in selected),
        'no_stage2_ids':[r['id'] for r in selected if not r['has_stage2']],
        'all_stage1_valid':all(r['stage1_isValidSolution']==1 for r in selected),
        'reconstructable_end_to_end':sum(math.isfinite(r['recovered_error']) for r in selected),
        'finite_stage1_times':sum(math.isfinite(r['stage1_elapsedSeconds']) for r in selected),
        'finite_stage2_times':sum(math.isfinite(r['stage2_elapsedSeconds']) for r in selected),
        'max_success_error_difference':max(abs(r['checkpoint_error']-r['recovered_error']) for r in selected if r['success']),
        'max_success_eval_difference':max(abs(r['checkpoint_evaluations']-r['recovered_evaluations']) for r in selected if r['success']),
        'max_dc_offset_from_half':max(r['max_dc_offset_from_half'] for r in selected if r['has_stage2']),
        'max_even_lag_coefficient':max(r['max_even_lag_coefficient'] for r in selected if r['has_stage2']),
    }
    result['stage_solver_details']={}
    for stage in [1,2]:
        for name in NAMES:
            subset=[r for r in selected if r['reference_solver' if stage==1 else 'mzi_solver']==name and r[f'has_stage{stage}']]
            field=f'stage{stage}_functionEvaluations'
            result['stage_solver_details'][f'{stage}:{name}']={
                'count':len(subset),'exit_flags':dict(Counter(str(int(r[f'stage{stage}_exitFlag'])) for r in subset)),
                'evals_min':min(r[field] for r in subset),'evals_max':max(r[field] for r in subset),'evals_mean':float(np.mean([r[field] for r in subset])),
                'seconds_mean':float(np.nanmean([r[f'stage{stage}_elapsedSeconds'] for r in subset])),
            }
    pairs=[]
    for first in NAMES:
        for second in NAMES:
            subset=[r for r in selected if r['reference_solver']==first and r['mzi_solver']==second]
            success=[r for r in subset if r['success']]
            valid=[r for r in subset if r['has_stage2'] and r['stage1_isValidSolution'] and r['stage2_isValidSolution']]
            P=len(success)/len(subset)
            E=float(np.mean([r['recovered_error'] for r in success])) if success else math.nan
            C=float(np.mean([r['recovered_evaluations'] for r in success])) if success else math.nan
            pairs.append({'reference_solver':first,'mzi_solver':second,'n':len(subset),'successful':len(success),
                'P':P,'E_success':E,'C_success':C,'F':P/E/math.log(C) if success else 0,
                'E_all_valid':float(np.mean([r['recovered_error'] for r in valid])) if valid else math.nan})
    result['pairs']=pairs
    return result

summaries={'current_snapshot':summary(rows),'prefix_global_ids_through_4947':summary([r for r in rows if r['id']<=4947]),
    'earliest_4947_completed':summary(sorted(rows,key=lambda r:r['completed_at'])[:4947])}

missing_ids=[r['id'] for r in rows if not r['has_stage2']]
exception_evidence=[]
for trialid in missing_ids:
    candidates=sorted((ROOT/'local-results/live').glob(f'*/trials/trial_{trialid:012d}.json'))
    for path in candidates:
        data=json.loads(path.read_text(encoding='utf-8-sig'));res=data['result']
        exception_evidence.append({'id':trialid,'file':str(path.relative_to(ROOT)), 'elapsed_seconds':data['elapsed_seconds'],
          'stage':res.get('failureStage'),'identifier':res.get('failureIdentifier'),'message':res.get('failureMessage')})
summaries['exception_evidence']=exception_evidence
summaries['selected_examples']=[r for r in rows if r['id'] in [1,41,101,141,241,481,4947]]
(OUT/'checkpoint-audit-summary.json').write_text(json.dumps(summaries,indent=2,allow_nan=True),encoding='utf-8')
print(json.dumps({k:{field:value for field,value in v.items() if field not in ['pairs','stage_solver_details']} for k,v in summaries.items() if isinstance(v,dict)},indent=2))
print('Wrote review artifacts only.',flush=True)
