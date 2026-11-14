"""Validate the approved artifact-export patch without contacting Google."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys
import unittest

HERE = Path(__file__).resolve().parent
ORIGINAL = HERE.parent / 'cloud/replication-20261026/plans/matlab-glop-cmp-20261026-1405/source/cloud'
WORK = HERE / 'uploader-validation'
WORK.mkdir(exist_ok=True)
old = ORIGINAL / 'durable_uploader.py'
raw = old.read_bytes()
before = b'worker_json = path.suffix.lower() == ".json" and path.parent.name == "workers"'
after = b'live_json = path.suffix.lower() == ".json" and path.parent.name in {"workers", "trials"}'
assert raw.count(before) == 1
raw = raw.replace(before, after).replace(b'path.is_file() and (worker_json or', b'path.is_file() and (live_json or')
(WORK / 'durable_uploader.py').write_bytes(raw)
(WORK / 'test_durable_uploader.py').write_bytes((ORIGINAL / 'test_durable_uploader.py').read_bytes())
sys.path.insert(0, str(WORK))
from test_durable_uploader import DurabilityTests


class ExportChecks(unittest.TestCase):
    def setUp(self):
        self.fixture = DurabilityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)

    def test_complete_trial_and_worker_json_are_exported_verbatim(self):
        f = self.fixture
        for kind, name in [('trials', 'trial_000000000001.json'), ('workers', 'worker_123.json')]:
            path = f.root / 'results/live/attempt' / kind / name
            path.parent.mkdir(parents=True, exist_ok=True)
            data = json.dumps({'global_trial_id': 1, 'result': {'completed': True}}).encode()
            path.write_bytes(data)
            self.assertEqual(f.publisher.upload_artifacts(), [])
            key = 'run/artifacts/tasks/00000/' + path.relative_to(f.root).as_posix()
            self.assertEqual(f.store.get(key), data)

    def test_temporary_records_and_uncommitted_objects_do_not_count_as_trials(self):
        f = self.fixture
        path = f.root / 'results/live/attempt/trials/trial_000000000001.json.tmp-123'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{partial')
        snapshot, errors = f.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot['completed_trials'], 0)
        self.assertFalse(any('.tmp-' in name for name in f.store.objects))

    def test_json_export_failure_is_retried_without_losing_committed_mat(self):
        f = self.fixture
        f.trial()
        path = f.root / 'results/live/attempt/trials/trial_000000000001.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'{"global_trial_id":1}')
        key = 'run/artifacts/tasks/00000/' + path.relative_to(f.root).as_posix()
        f.store.always_fail.add(key)
        snapshot, errors = f.publisher.publish()
        self.assertTrue(errors)
        self.assertEqual(snapshot['completed_trials'], 1)
        f.store.always_fail.clear()
        snapshot, errors = f.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot['completed_trials'], 1)
        self.assertEqual(f.store.get(key), path.read_bytes())


suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(DurabilityTests),
                            unittest.defaultTestLoader.loadTestsFromTestCase(ExportChecks)])
result = unittest.TextTestRunner(verbosity=2).run(suite)
record = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
              skipped=len(result.skipped), uploader_sha256=hashlib.sha256(raw).hexdigest())
(HERE / 'cloud-export-tests.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
raise SystemExit(0 if result.wasSuccessful() else 1)
