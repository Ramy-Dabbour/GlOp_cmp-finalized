"""Offline producer/uploader integration tests; no Google credentials needed."""
import datetime as dt
import gzip
import io
import json
from pathlib import Path
import tempfile
import ssl
import urllib.error
import urllib.parse
import unittest
from unittest import mock

import live_reporter as live


class MemoryStore:
    def __init__(self):
        self.data = {}
        self.generations = {}
        self.events = []
        self.lose_response = False

    def get(self, name):
        return self.data.get(name)

    def generation(self, name):
        return self.generations.get(name, 0)

    def put(self, name, data, content_type="application/json", generation=None):
        if generation is not None and generation != self.generation(name):
            raise live.Conflict()
        self.data[name] = data
        self.generations[name] = self.generation(name)+1
        self.events.append(name)
        if self.lose_response and name.endswith(".jsonl.gz"):
            self.lose_response = False
            raise OSError("Simulated successful upload with lost response")


class LiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root/"trials").mkdir()
        (self.root/"workers").mkdir()
        self.store = MemoryStore()
        self.prefix = "outputs/unit-job"
        self.state = dict(task_index=0, task_count=1, status="running",
                          started_at=live.now(), total_trials=3, assigned_trials=3)
        live.atomic_json(self.root/"state.json", self.state)

    def publisher(self):
        return live.Publisher(self.root, self.store, self.prefix, "unit-job", 0, 1, 8)

    def record(self, index, status="succeeded"):
        record = dict(global_trial_id=index, status=status, completed_at=live.now(),
                      elapsed_seconds=2, parameters=[4,.2,0,4,4,index], end_to_end_error=.1,
                      result=dict(x=[1,2], design=dict(real=[1,2],imag=[3,4]),
                                  failureIdentifier="fixture:Failed" if status=="failed" else ""))
        live.atomic_json(self.root/"trials"/f"trial_{index:012d}.json", record)
        return record

    def chunks(self):
        return [json.loads(line) for name,data in self.store.data.items() if name.endswith(".jsonl.gz")
                for line in gzip.decompress(data).splitlines()]

    def test_publishes_complete_result_while_matlab_still_running(self):
        record = self.record(1)
        snapshot = self.publisher().publish()
        self.assertEqual(snapshot["status"], "running")
        self.assertEqual(snapshot["completed_trials"], 1)
        self.assertEqual(self.chunks(), [record])
        self.assertEqual(json.loads(self.store.get(self.prefix+"/live/summary.json"))["completed_trials"],1)
        self.assertLess(next(i for i,n in enumerate(self.store.events) if n.endswith(".jsonl.gz")),
                        self.store.events.index(self.prefix+"/live/tasks/00000/latest.json"))
        self.assertFalse((self.root/"trial_shard_00000.mat").exists())

    def test_restarts_and_lost_response_do_not_duplicate_trials(self):
        self.record(1)
        self.store.lose_response = True
        with self.assertRaises(OSError):
            self.publisher().publish()
        self.record(2, "failed")
        self.publisher().publish()
        snapshot = self.publisher().publish()
        self.assertEqual(sorted(record["global_trial_id"] for record in self.chunks()),[1,2])
        self.assertEqual(snapshot["failed_trials"],1)
        self.assertEqual(snapshot["published_trials"],2)
        self.assertFalse((self.root/"_pending.jsonl.gz").exists())

    def test_final_flush_does_not_claim_missing_trials_completed(self):
        self.record(1)
        self.state["status"] = "completed"
        live.atomic_json(self.root/"state.json",self.state)
        snapshot = self.publisher().publish(final=True)
        self.assertEqual(snapshot["status"],"incomplete")
        self.assertEqual(snapshot["published_trials"],1)

    def test_final_flush_preserves_all_outcomes(self):
        self.record(1)
        self.record(2,"nonconverged")
        self.record(3,"failed")
        self.state["status"] = "completed"
        live.atomic_json(self.root/"state.json",self.state)
        snapshot = self.publisher().publish(final=True)
        self.assertEqual(snapshot["status"],"completed")
        self.assertEqual([snapshot[k] for k in ("succeeded_trials","nonconverged_trials","failed_trials")],[1,1,1])
        self.assertEqual(len(self.chunks()),3)
        self.assertEqual(json.loads(self.store.get(self.prefix+"/live/summary.json"))["status"],"completed")

    def test_worker_heartbeat_distinguishes_active_and_stale(self):
        recent = dict(active=True, updated_at=live.now(), stage="reference", objective_evaluations=27)
        stale = dict(active=True, updated_at=(dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=300)).isoformat(),stage="mzi",objective_evaluations=10)
        live.atomic_json(self.root/"workers/worker_1.json",recent)
        live.atomic_json(self.root/"workers/worker_2.json",stale)
        snapshot = self.publisher().publish()
        self.assertEqual((snapshot["active_workers"],snapshot["stale_workers"]),(2,1))
        self.assertEqual({w["objective_evaluations"] for w in snapshot["workers"]},{27,10})

    def test_partial_failure_keeps_completed_records(self):
        self.record(1)
        self.state.update(status="failed", failure_identifier="fixture:Unexpected")
        live.atomic_json(self.root/"state.json",self.state)
        snapshot = self.publisher().publish(final=True)
        self.assertEqual(snapshot["status"],"failed")
        self.assertEqual(len(self.chunks()),1)
        self.assertEqual(json.loads(self.store.get(self.prefix+"/live/summary.json"))["status"],"incomplete")

    def test_wrong_task_assignment_is_rejected(self):
        self.state.update(task_count=2,total_trials=6)
        live.atomic_json(self.root/"state.json",self.state)
        self.record(2)
        publisher = live.Publisher(self.root,self.store,self.prefix,"unit-job",0,2,8)
        with self.assertRaisesRegex(RuntimeError,"misassigned"):
            publisher.publish()

    def test_chunks_are_batched_and_every_trial_is_recoverable(self):
        self.state.update(total_trials=250,assigned_trials=250)
        live.atomic_json(self.root/"state.json",self.state)
        for index in range(1,251):
            self.record(index)
        snapshot = self.publisher().publish()
        self.assertEqual(snapshot["published_trials"],250)
        self.assertEqual(len([name for name in self.store.data if name.endswith(".jsonl.gz")]),3)
        self.assertEqual(sorted(r["global_trial_id"] for r in self.chunks()),list(range(1,251)))

    def test_last_finishing_task_refreshes_global_summary(self):
        self.state.update(task_count=2,total_trials=2,assigned_trials=1,status="completed")
        live.atomic_json(self.root/"state.json",self.state)
        self.record(1)
        first = live.Publisher(self.root,self.store,self.prefix,"unit-job",0,2,8)
        first.publish(final=True)
        summary = json.loads(self.store.get(self.prefix+"/live/summary.json"))
        self.assertEqual(summary["status"],"running")
        root = self.root/"second"
        state = dict(self.state,task_index=1)
        live.atomic_json(root/"state.json",state)
        record = dict(self.record(2),global_trial_id=2)
        live.atomic_json(root/"trials/trial_000000000002.json",record)
        live.Publisher(root,self.store,self.prefix,"unit-job",1,2,8).publish(final=True)
        summary = json.loads(self.store.get(self.prefix+"/live/summary.json"))
        self.assertEqual((summary["status"],summary["completed_trials"]),("completed",2))

    def test_concurrent_global_update_retries_with_fresh_generation(self):
        original = self.store.put
        calls = []
        def conflicting(name, data, content_type="application/json", generation=None):
            if name.endswith("summary.json") and not calls:
                calls.append(name)
                self.store.generations[name] = 1
                raise live.Conflict()
            original(name,data,content_type,generation)
        with mock.patch.object(self.store,"put",side_effect=conflicting):
            self.publisher().publish()
        self.assertEqual(self.store.generation(self.prefix+"/live/summary.json"),2)


class StorageApiTests(unittest.TestCase):
    def test_sdk_system_trust_is_used_without_disabling_tls_verification(self):
        trusted_context=ssl.create_default_context()
        # This Windows host lacks Linux's bundle; verify the runtime selection.
        with mock.patch.object(Path,"is_file",return_value=True),mock.patch.object(live.ssl,"create_default_context",return_value=trusted_context) as create:
            context=live.GcsStore("unit-bucket").ssl_context
        create.assert_called_once_with(cafile=str(Path("/etc/ssl/certs/ca-certificates.crt")))
        self.assertEqual(context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(context.check_hostname)

    def test_vm_credentials_and_generation_preconditions_are_sent_correctly(self):
        requests=[]
        def respond(request,**kwargs):
            requests.append(request)
            if request.full_url.startswith("http://metadata.google.internal/"):
                return io.BytesIO(b'{"access_token":"unit-test-token","expires_in":3600}')
            return io.BytesIO(b'{}')
        with mock.patch.object(live.urllib.request,"urlopen",side_effect=respond):
            store=live.GcsStore("unit-bucket")
            store.put("outputs/job/trial file.gz",b"data","application/gzip",generation=0)
            store.put("outputs/job/latest.json",b"{}",generation=42)
        self.assertEqual(len(requests),3) # Token reused for the second upload.
        self.assertEqual(requests[0].get_header("Metadata-flavor"),"Google")
        query=urllib.parse.parse_qs(urllib.parse.urlsplit(requests[1].full_url).query)
        self.assertEqual(query["name"],["outputs/job/trial file.gz"])
        self.assertEqual(query["ifGenerationMatch"],["0"])
        self.assertEqual(requests[1].get_header("Authorization"),"Bearer unit-test-token")
        self.assertEqual(requests[1].data,b"data")

    def test_cloud_generation_conflict_is_detected_and_auth_failures_are_not_hidden(self):
        def respond(request,**kwargs):
            if request.full_url.startswith("http://metadata.google.internal/"):
                return io.BytesIO(b'{"access_token":"unit-test-token","expires_in":3600}')
            raise urllib.error.HTTPError(request.full_url,412,"conflict",None,None)
        with mock.patch.object(live.urllib.request,"urlopen",side_effect=respond):
            with self.assertRaises(live.Conflict):
                live.GcsStore("unit-bucket").put("record",b"data",generation=0)
        store=live.GcsStore("unit-bucket")
        store.token="unit-test-token"
        store.expires=float("inf")
        error=urllib.error.HTTPError("https://storage.googleapis.com",401,"expired",None,None)
        with mock.patch.object(live.urllib.request,"urlopen",side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                store.get("record")
        self.assertEqual(store.expires,0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
