"""Offline failure-path tests; never contact Google or start MATLAB."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from durable_uploader import (Conflict, IntegrityError, Publisher, encoded,
                              immutable_put, sha256)


class FakeStore:
    def __init__(self):
        self.objects = {}
        self.generations = {}
        self.fail_before = {}
        self.fail_after = {}
        self.always_fail = set()
        self.force_conflict = set()
        self.put_events = []

    def get(self, name):
        return self.objects.get(name)

    def generation(self, name):
        return self.generations.get(name, 0)

    def list_names(self, prefix):
        return sorted(name for name in self.objects if name.startswith(prefix))

    def put(self, name, data, content_type="application/json", generation=None):
        self.put_events.append((name, generation))
        if name in self.always_fail or self.fail_before.get(name, 0):
            self.fail_before[name] = max(0, self.fail_before.get(name, 0) - 1)
            raise OSError("offline failure before write")
        if name in self.force_conflict or generation is not None and generation != self.generation(name):
            raise Conflict("generation mismatch")
        self.objects[name] = data
        self.generations[name] = self.generation(name) + 1
        if self.fail_after.get(name, 0):
            self.fail_after[name] -= 1
            raise OSError("offline ambiguous response after write")


class DurabilityTests(unittest.TestCase):
    def setUp(self):
        self.test_parent = Path(__file__).resolve().parent
        self.temporary = tempfile.TemporaryDirectory(prefix=".test-", dir=self.test_parent)
        self.root = Path(self.temporary.name)
        self.store = FakeStore()
        self.manifest = dict(run_id="isolated-test", source_sha256="a" * 64,
                             config_sha256="b" * 64, config=dict(repeats=2))
        self.publisher = self.make_publisher(self.root)

    def tearDown(self):
        if self.root.resolve().parent != self.test_parent or not self.root.name.startswith(".test-"):
            raise RuntimeError("Refusing to clean a directory outside the test workspace")
        self.temporary.cleanup()

    def make_publisher(self, root, index=0, count=4, manifest=None):
        return Publisher(root, self.store, "run", manifest or self.manifest,
                         index, count, sleep=lambda unused: None)

    def trial(self, trial_id=1, status="succeeded", root=None, **extra):
        root = root or self.root
        directory = root / "results" / "checkpoints"
        directory.mkdir(parents=True, exist_ok=True)
        base = directory / f"trial_{trial_id:012d}"
        mat_data = b"offline MAT stand-in for " + str(trial_id).encode()
        identity = {key: self.manifest[key] for key in ("run_id", "source_sha256", "config_sha256")}
        record = dict(schema_version=1, trial_id=trial_id, completed=True,
                      parameters=[1, 2, 3, 4, 5, 6], success=status == "succeeded",
                      status=status, error=None if status == "failed" else 2.5,
                      evaluations=None if status == "failed" else 7,
                      legacy_error=0 if status != "succeeded" else 2.5,
                      legacy_evaluations=0 if status != "succeeded" else 7,
                      elapsed_seconds=0.5, failure_identifier="sample:failure" if status == "failed" else "",
                      failure_message="numerical failure" if status == "failed" else "",
                      completed_at="2026-10-26T08:00:00Z", sha256=sha256(mat_data), **identity)
        record.update(extra)
        base.with_suffix(".mat").write_bytes(mat_data)
        base.with_suffix(".json").write_bytes(encoded(record))
        return base, record, mat_data

    def state(self, total=1, status="running"):
        state = dict(task_index=0, task_count=4, total_trials=total, status=status,
                     **{key: self.manifest[key] for key in ("run_id", "source_sha256", "config_sha256")})
        (self.root / "results" / "state.json").write_bytes(encoded(state))

    def object_names(self, record, mat_data):
        return self.publisher._object_names(self.publisher._commit(record["trial_id"], mat_data, encoded(record)))

    def test_network_failure_before_write_retries(self):
        self.store.fail_before["immutable"] = 1
        immutable_put(self.store, "immutable", b"same bytes", sleep=lambda unused: None)
        self.assertEqual(self.store.get("immutable"), b"same bytes")
        self.assertEqual(len(self.store.put_events), 2)

    def test_ambiguous_success_is_accepted_only_after_readback(self):
        self.store.fail_after["immutable"] = 1
        immutable_put(self.store, "immutable", b"same bytes", sleep=lambda unused: None)
        self.assertEqual(len(self.store.put_events), 1)
        self.assertEqual(self.store.generation("immutable"), 1)

    def test_collision_does_not_overwrite(self):
        self.store.put("immutable", b"original", generation=0)
        with self.assertRaises(IntegrityError):
            immutable_put(self.store, "immutable", b"different", sleep=lambda unused: None)
        self.assertEqual(self.store.get("immutable"), b"original")

    def test_no_ack_or_completion_until_commit_is_durable(self):
        base, record, mat_data = self.trial()
        self.state(status="completed")
        commit_name = "run/checkpoints/tasks/00000/trial_000000000001.commit.json"
        self.store.always_fail.add(commit_name)
        snapshot, errors = self.publisher.publish()
        self.assertTrue(errors)
        self.assertEqual(snapshot["completed_trials"], 0)
        self.assertEqual(snapshot["status"], "incomplete")
        self.assertFalse((self.root / "results" / "acks" / base.with_suffix(".json").name).exists())
        self.store.always_fail.clear()
        snapshot, errors = self.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot["completed_trials"], 1)
        ack = json.loads((self.root / "results" / "acks" / base.with_suffix(".json").name).read_bytes())
        self.assertEqual(ack["sha256"], sha256(mat_data))
        self.assertEqual(ack["run_id"], self.manifest["run_id"])

    def test_ambiguous_mat_sidecar_commit_preserve_every_outcome_field(self):
        base, record, mat_data = self.trial(status="failed", custom_observation=[1, None, 3])
        self.state()
        mat_name, json_name = self.object_names(record, mat_data)
        for name in (mat_name, json_name, "run/checkpoints/tasks/00000/" + base.name + ".commit.json"):
            self.store.fail_after[name] = 1
        snapshot, errors = self.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot["failed_trials"], 1)
        self.assertEqual(snapshot["latest_trial"], record)
        self.assertEqual(self.store.get(json_name), encoded(record))

    def test_restore_verifies_and_recreates_mat_sidecar_and_ack(self):
        base, record, mat_data = self.trial(status="nonconverged")
        self.publisher.publish()
        second_root = self.root / "retry"
        restored = self.make_publisher(second_root).restore()
        self.assertEqual(restored, 1)
        self.assertEqual((second_root / "results" / "checkpoints" / base.with_suffix(".mat").name).read_bytes(), mat_data)
        self.assertEqual(json.loads((second_root / "results" / "checkpoints" / base.with_suffix(".json").name).read_bytes()), record)
        self.assertTrue((second_root / "results" / "acks" / base.with_suffix(".json").name).is_file())

    def test_restore_ignores_uncommitted_objects(self):
        self.publisher.ensure_manifest()
        self.store.put("run/checkpoints/tasks/00000/objects/trial_000000000001.deadbeef.mat", b"unfinished")
        self.assertEqual(self.publisher.restore(), 0)

    def test_restore_rejects_source_or_manifest_mismatch(self):
        self.publisher.ensure_manifest()
        changed = dict(self.manifest, source_sha256="c" * 64)
        with self.assertRaises(IntegrityError):
            self.make_publisher(self.root / "retry", manifest=changed).restore()

    def test_restore_rejects_corrupt_remote_data_without_ack(self):
        base, record, mat_data = self.trial()
        self.publisher.publish()
        self.store.objects[self.object_names(record, mat_data)[0]] = b"corrupted"
        second_root = self.root / "retry"
        with self.assertRaises(IntegrityError):
            self.make_publisher(second_root).restore()
        self.assertFalse((second_root / "results" / "acks" / base.with_suffix(".json").name).exists())

    def test_artifacts_publish_despite_trial_upload_failure_and_no_full_result(self):
        base, record, mat_data = self.trial()
        self.store.always_fail.add(self.object_names(record, mat_data)[0])
        (self.root / "results" / "trial_results.csv").write_text("trial_id,error\n1,2.5\n")
        (self.root / "results" / "progress.log").write_text("partial progress\n")
        snapshot, errors = self.publisher.publish(final=True)
        self.assertTrue(errors)
        self.assertEqual(snapshot["completed_trials"], 0)
        self.assertIn("run/artifacts/tasks/00000/results/trial_results.csv", self.store.objects)
        self.assertIn("run/artifacts/tasks/00000/results/progress.log", self.store.objects)

    def test_all_four_shards_aggregate_only_durable_records(self):
        for index in range(4):
            root = self.root / f"task{index}"
            self.trial(trial_id=index + 1, root=root)
            publisher = self.make_publisher(root, index=index)
            state = dict(task_index=index, task_count=4, total_trials=1, status="completed",
                         **{key: self.manifest[key] for key in ("run_id", "source_sha256", "config_sha256")})
            (root / "results" / "state.json").write_bytes(encoded(state))
            snapshot, errors = publisher.publish(final=True)
            self.assertFalse(errors)
        summary = json.loads(self.store.get("run/live/summary.json"))
        self.assertEqual(summary["completed_trials"], 4)
        self.assertEqual(summary["total_trials"], 4)
        self.assertEqual(summary["status"], "completed")

    def test_summary_cas_contention_is_harmless(self):
        self.trial()
        self.store.force_conflict.add("run/live/summary.json")
        snapshot, errors = self.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot["completed_trials"], 1)
        self.assertIsNotNone(self.store.get("run/live/tasks/00000/latest.json"))

    def test_misassigned_trial_rejected_before_upload(self):
        self.trial(trial_id=2)
        snapshot, errors = self.publisher.publish()
        self.assertIsInstance(errors[0], IntegrityError)
        self.assertEqual(snapshot["completed_trials"], 0)
        self.assertFalse(any("trial_000000000002" in name for name in self.store.objects))
        self.assertTrue((self.root / "results" / "UPLOAD_FAILED.json").is_file())

    def test_vm_loss_before_commit_can_recompute_different_mat_bytes(self):
        base, record, mat_data = self.trial()
        old_mat, old_json = self.object_names(record, mat_data)
        self.publisher.ensure_manifest()
        self.store.put(old_mat, mat_data, generation=0)
        self.store.put(old_json, encoded(record), generation=0)
        retry_root = self.root / "retry"
        retry = self.make_publisher(retry_root)
        self.assertEqual(retry.restore(), 0)
        new_base, new_record, unused = self.trial(root=retry_root)
        new_mat = b"different MAT header after VM replacement"
        new_record["sha256"] = sha256(new_mat)
        new_record["completed_at"] = "2026-10-26T09:00:00Z"
        new_base.with_suffix(".mat").write_bytes(new_mat)
        new_base.with_suffix(".json").write_bytes(encoded(new_record))
        snapshot, errors = retry.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot["completed_trials"], 1)
        self.assertEqual(self.store.get(old_mat), mat_data)
        self.assertEqual(self.make_publisher(self.root / "third").restore(), 1)

    def test_vm_loss_at_every_remote_upload_cut_point(self):
        for cut in ("before_mat", "before_sidecar", "before_commit", "after_commit_before_ack"):
            with self.subTest(cut=cut):
                self.store = FakeStore()
                root = self.root / cut
                publisher = self.make_publisher(root)
                base, record, mat_data = self.trial(root=root)
                commit = publisher._commit(record["trial_id"], mat_data, encoded(record))
                mat_name, json_name = publisher._object_names(commit)
                commit_name = publisher.checkpoint_prefix + base.name + ".commit.json"
                failure_name = {"before_mat": mat_name, "before_sidecar": json_name,
                                "before_commit": commit_name}.get(cut)
                if failure_name:
                    self.store.always_fail.add(failure_name)
                    snapshot, errors = publisher.publish()
                else:
                    with patch.object(publisher, "_ack", side_effect=OSError("VM lost before ack")):
                        snapshot, errors = publisher.publish()
                self.assertTrue(errors)
                self.assertEqual(snapshot["completed_trials"], 0)
                self.assertFalse((root / "results" / "acks" / base.with_suffix(".json").name).exists())
                self.store.always_fail.clear()
                retry_root = root / "replacement"
                retry = self.make_publisher(retry_root)
                restored = retry.restore()
                if cut == "after_commit_before_ack":
                    self.assertEqual(restored, 1)
                    self.assertEqual(retry.records[1], record)
                else:
                    self.assertEqual(restored, 0)
                    retry_base, retry_record, unused = self.trial(root=retry_root)
                    retry_mat = b"new attempt, new MAT timestamp"
                    retry_record["sha256"] = sha256(retry_mat)
                    retry_base.with_suffix(".mat").write_bytes(retry_mat)
                    retry_base.with_suffix(".json").write_bytes(encoded(retry_record))
                    retry_snapshot, retry_errors = retry.publish()
                    self.assertFalse(retry_errors)
                    self.assertEqual(retry_snapshot["completed_trials"], 1)

    def test_fast_checkpoint_poll_does_not_wait_for_metrics_rpcs(self):
        self.publisher.ensure_manifest()
        self.trial()
        self.store.put_events.clear()
        snapshot, errors = self.publisher.publish(report=False)
        self.assertFalse(errors)
        self.assertEqual(snapshot["completed_trials"], 1)
        self.assertFalse(any("/live/" in name for name, unused in self.store.put_events))

    def test_restore_rejects_invalid_commit_hashes(self):
        self.publisher.ensure_manifest()
        malformed = dict(schema_version=1, trial_id=1, task_index=0, task_count=4,
                         sha256="invalid", sidecar_sha256="b" * 64,
                         **{key: self.manifest[key] for key in ("run_id", "source_sha256", "config_sha256")})
        self.store.put("run/checkpoints/tasks/00000/trial_000000000001.commit.json", encoded(malformed))
        with self.assertRaises(IntegrityError):
            self.publisher.restore()

    def test_active_objective_telemetry_is_visible_without_completed_trial(self):
        self.state(total=10)
        worker_path = self.root / "results" / "live" / "attempt-2" / "workers" / "worker_123.json"
        worker_path.parent.mkdir(parents=True)
        worker_path.write_bytes(encoded(dict(updated_at="2026-10-26T08:00:00Z", active=True,
                                            global_trial_id=1, objective_evaluations=2738,
                                            stage="local-search", stage_evaluations=102,
                                            last_objective=0.05, best_stage_objective=0.01)))
        snapshot, errors = self.publisher.publish()
        self.assertFalse(errors)
        self.assertEqual(snapshot["completed_trials"], 0)
        self.assertEqual(snapshot["active_workers"], 1)
        self.assertEqual(snapshot["workers"][0]["objective_evaluations"], 2738)
        self.assertIn("run/artifacts/tasks/00000/results/live/attempt-2/workers/worker_123.json", self.store.objects)
        finalized, errors = self.publisher.publish(final=True)
        self.assertEqual(finalized["active_workers"], 0)
        self.assertTrue(finalized["workers"][0]["interrupted"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
