import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import build_replication as build
import manage_replication as manage


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=Path(__file__).parent,prefix='test-tmp-')
        self.root=Path(self.temp.name)
        self.plan=self.root/'plan'; self.plan.mkdir()
        self.launch=dict(run_id='matlab-glop-test',project='test-project',region='us-central1',
                         run_uri='gs://bucket/outputs/matlab-glop-test',source_uri='gs://bucket/runs/matlab-glop-test/source',
                         source_sha256='a'*64,config_sha256='b'*64)
        (self.plan/'launch.json').write_text(json.dumps(self.launch))
        (self.plan/'source').mkdir(); (self.plan/'source/manifest.json').write_text('{}')
        self.patch=patch.object(manage,'PROJECT_ROOT',self.root); self.patch.start()
        self.manager=manage.Manager(self.plan)

    def tearDown(self):
        self.patch.stop(); self.temp.cleanup()

    def test_recover_lost_submit_response_without_duplicate_job(self):
        calls=[]
        def cloud(*args,**kwargs):
            calls.append(args)
            if args[:3]==('batch','jobs','describe'): return json.dumps(dict(uid='existing-uid'))
            return None
        self.manager.cloud=cloud
        self.manager.submit()
        self.assertFalse(any(c[:3]==('batch','jobs','submit') for c in calls))
        self.assertEqual(self.manager.state['current_job'],'matlab-glop-test')

    def test_rollover_keeps_configuration_and_storage_namespace(self):
        self.manager.state['jobs']=[dict(job_id='matlab-glop-test')]
        calls=[]
        def cloud(*args,**kwargs):
            calls.append(args)
            return None if args[:3]==('batch','jobs','describe') else json.dumps(dict(uid='retry-uid'))
        self.manager.cloud=cloud
        self.manager.submit()
        submit=next(c for c in calls if c[:3]==('batch','jobs','submit'))
        self.assertEqual(submit[3],'matlab-glop-test-r01')
        self.assertEqual(submit[submit.index('--config')+1],self.plan/'batch.json')
        self.assertFalse(any(c[0]=='storage' for c in calls))
        self.assertEqual(self.manager.launch['run_uri'],self.launch['run_uri'])

    def test_foreign_remote_source_is_never_overwritten(self):
        self.manager.cloud=lambda *a,**k:'{"foreign":true}'
        with self.assertRaisesRegex(RuntimeError,'refusing overwrite'): self.manager.submit()

    def test_foreign_remote_summary_is_rejected(self):
        self.manager.state.update(jobs=[{}],current_job='matlab-glop-test')
        def cloud(*args,**kwargs):
            if args[0]=='batch': return json.dumps(dict(status=dict(state='RUNNING')))
            return json.dumps(dict(self.launch,run_id='another-run'))
        self.manager.cloud=cloud
        self.manager.read_current_object=lambda *a,**k:json.dumps(dict(self.launch,run_id='another-run'))
        with self.assertRaisesRegex(RuntimeError,'identity mismatch'): self.manager.status()

    def test_generated_container_programs_parse(self):
        compile(build.prepare_program('gs://bucket/source','gs://bucket/run','a'*64),'prepare','exec')
        for command in ('restore','daemon','finalize'):
            compile(build.uploader_program(command,'gs://bucket/run'),'uploader','exec')

    def test_partial_export_keeps_failed_metrics_and_correct_denominator(self):
        from scipy.io import loadmat
        import math
        config=dict(build.CONFIG)
        vectors=dict(referenceSolvers=[0],mziSolvers=[1])
        base=dict(reference_solver=0,mzi_solver=1,error='0.5',evaluations='100',elapsed_seconds='2',legacy_error='0',legacy_evaluations='0')
        rows=[dict(base,trial_id='1',completed='1',success='1',status='succeeded',legacy_error='0.5',legacy_evaluations='100'),
              dict(base,trial_id='2',completed='1',success='0',status='nonconverged'),
              dict(base,trial_id='3',completed='0',success='0',status='pending',error='NaN',evaluations='NaN')]
        self.manager.assemble_mat_summary(rows,config,vectors)
        value=loadmat(self.manager.output/'benchmark_results.mat',simplify_cells=True)
        self.assertAlmostEqual(value['benchmarkSummary']['legacy_success_rate'],.5)
        self.assertAlmostEqual(value['benchmarkSummary']['legacy_favorability'],1/math.log(100))
        self.assertEqual(value['trialResults']['error'][1],.5)
        self.assertEqual(value['trialResults']['completed'].tolist(),[1,1,0])

    def test_integrity_failure_never_resubmits_compute(self):
        self.manager.state.update(jobs=[{}],current_job='matlab-glop-test')
        self.manager.status=lambda: (dict(uid='test-uid',status=dict(state='FAILED')),None)
        self.manager.collect=lambda:None
        self.manager.capture_logs=lambda job:[dict(textPayload='Frozen manifest checksum mismatch')]
        submitted=[]
        self.manager.submit=lambda:submitted.append(True)
        with self.assertRaisesRegex(RuntimeError,'Integrity/configuration failure'):
            self.manager._watch_owned()
        self.assertFalse(submitted)
        self.assertTrue((self.plan/'NEEDS_ATTENTION.json').exists())

    def test_stalled_local_status_request_cannot_stall_monitor_for_an_hour(self):
        import subprocess
        with patch.object(manage.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{}','')) as run:
            self.manager.cloud('batch','jobs','describe','example')
            self.assertEqual(run.call_args.kwargs['timeout'],120)
            self.manager.cloud('storage','rsync','source','destination')
            self.assertEqual(run.call_args.kwargs['timeout'],3600)

    def test_live_status_reads_current_object_without_stale_generation(self):
        from unittest.mock import MagicMock
        self.manager.cloud=lambda *a,**k:'test-token'
        response=MagicMock(); response.__enter__.return_value.read.return_value=b'{"completed_trials":7}'
        with patch.object(manage.urllib.request,'urlopen',return_value=response) as request:
            value=self.manager.read_current_object('live/summary.json')
            url=request.call_args.args[0].full_url
            self.assertTrue(url.endswith('live%2Fsummary.json?alt=media'))
            self.assertNotIn('generation',url)
            self.assertEqual(json.loads(value)['completed_trials'],7)


if __name__=='__main__': unittest.main()
