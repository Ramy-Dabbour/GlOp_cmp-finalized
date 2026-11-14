"""Offline regression tests for the COS workspace storage correction.

No Google Cloud commands, licensing checks, or real MATLAB runs are performed.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest import mock


spec = importlib.util.spec_from_file_location(
    "storage_fix_runner", Path(__file__).with_name("matlab_cloud_run.py")
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class StorageFixTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def mount_record(self, path, filesystem="ext4"):
        escaped = path.as_posix().replace("\\", r"\134").replace(" ", r"\040")
        return f"100 20 8:1 / {escaped} rw,relatime - {filesystem} /dev/sda1 rw"

    @contextlib.contextmanager
    def helper_environment(self, mount_records, run_side_effect=None):
        original_read = Path.read_text

        def read_text(path, *args, **kwargs):
            if path == Path("/proc/self/mountinfo"):
                return "\n".join(mount_records)
            return original_read(path, *args, **kwargs)

        output = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(runner, "SHARED", str(self.root)))
            stack.enter_context(mock.patch.object(Path, "read_text", read_text))
            stack.enter_context(mock.patch.object(shutil, "disk_usage", return_value=SimpleNamespace(
                total=100_000_000_000, used=50_000_000_000, free=50_000_000_000)))
            stack.enter_context(mock.patch.object(os, "statvfs", create=True,
                return_value=SimpleNamespace(f_files=1_000_000, f_favail=900_000)))
            stack.enter_context(mock.patch.object(os, "chown", create=True))
            stack.enter_context(mock.patch.object(os, "chmod"))
            stack.enter_context(mock.patch.dict(os.environ, {"CLOUDSDK_PYTHON": "/usr/bin/python3"}))
            run = stack.enter_context(mock.patch.object(subprocess, "run", side_effect=run_side_effect))
            stack.enter_context(contextlib.redirect_stdout(output))
            yield run, output

    def fake_source_transfer(self, arguments, **kwargs):
        self.assertEqual(arguments[:3], ["gcloud", "storage", "rsync"])
        self.assertTrue(kwargs["check"])
        self.assertEqual(os.environ["CLOUDSDK_PYTHON"], sys.executable)
        (Path(arguments[4]) / "main.m").write_text("disp('offline fixture');\n")
        return subprocess.CompletedProcess(arguments, 0)

    def test_all_runnables_share_stateful_host_bind(self):
        source = self.root / "main.m"
        source.write_text("disp('fixture');")
        project = SimpleNamespace(name="fixture", directory=self.root, key="fixture",
            bucket="unit-tests-only", config={"entry_points": ["main.m"]})
        context = SimpleNamespace(settings={
            "license": {"mode": "online", "image_prepared": True},
            "service_account": "batch@example.iam.gserviceaccount.com",
            "transfer_image": "gcr.io/google.com/cloudsdktool/google-cloud-cli:548.0.0-stable"},
            env_image="us-central1-docker.pkg.dev/example/images/matlab:r2026a",
            env_digest="sha256:" + "a" * 64, region="us-central1")
        workflow = ModuleType("matlab_cloud")
        workflow.source_files = lambda project: [source]
        with mock.patch.dict(sys.modules, {"matlab_cloud": workflow}):
            job = runner.build_job(context, project, "fixture-job", "gs://unit-tests-only/source", False)
        group = job["taskGroups"][0]
        self.assertEqual((group["taskCount"], group["parallelism"], group["taskCountPerNode"]), ("1", "1", "1"))
        runnables = group["taskSpec"]["runnables"]
        self.assertEqual(len(runnables), 3)
        for runnable in runnables:
            self.assertEqual(runnable["container"]["volumes"],
                ["/var/lib/google/matlab-cloud:/work/shared:rw"])
        self.assertIn("/work/shared/workspace/main.m", runnables[1]["container"]["commands"][-1])
        self.assertEqual(runnables[1]["environment"]["variables"]["MATLAB_CLOUD_OUTPUT_DIR"], "/work/shared/results")
        self.assertTrue(runnables[2]["alwaysRun"])
        self.assertIn("onlinelicensing", runnables[1]["container"]["commands"])

    def test_generated_helpers_compile(self):
        compile(runner._prepare_program("gs://unit-tests-only/source"), "prepare", "exec")
        compile(runner._collect_program("gs://unit-tests-only/output", "fixture-job"), "collect", "exec")

    def test_prepare_and_collect_with_mocked_transfers(self):
        mount = self.mount_record(self.root)
        with self.helper_environment([mount], self.fake_source_transfer) as (run, output):
            exec(runner._prepare_program("gs://unit-tests-only/source"), {})
            run.assert_called_once()
            self.assertEqual(json.loads((self.root / "_PREPARED.json").read_text()), {"prepared": True})
            diagnostics = json.loads(output.getvalue().splitlines()[0])
            self.assertEqual(diagnostics["filesystem"], "ext4")
            self.assertEqual(diagnostics["mountinfo"], mount)
            self.assertEqual(diagnostics["free_bytes"], 50_000_000_000)
            self.assertEqual(diagnostics["available_inodes"], 900_000)
            run.reset_mock(side_effect=True)
            run.return_value = subprocess.CompletedProcess([], 0)
            exec(runner._collect_program("gs://unit-tests-only/output", "fixture-job"), {})
            self.assertEqual(run.call_count, 4)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertTrue(all(command[:3] == ["gcloud", "storage", "rsync"] for command in commands[:3]))
            self.assertEqual(commands[-1][:3], ["gcloud", "storage", "cp"])
            self.assertIn("--if-generation-match=0", commands[-1])
            marker = json.loads((self.root / runner.TRANSFER_MARKER).read_text())
            self.assertEqual(marker["job_id"], "fixture-job")
            self.assertFalse(marker["scientific_completion_verified"])

    def test_tmpfs_rejected_before_transfer(self):
        with self.helper_environment([self.mount_record(self.root, "tmpfs")]) as (run, output):
            with self.assertRaisesRegex(RuntimeError, "Workspace is backed by tmpfs"):
                exec(runner._prepare_program("gs://unit-tests-only/source"), {})
            run.assert_not_called()
            self.assertFalse((self.root / "_PREPARED.json").exists())
            self.assertEqual(json.loads(output.getvalue())["filesystem"], "tmpfs")

    def test_most_specific_mount_wins(self):
        mounts = [self.mount_record(self.root.parent, "tmpfs"), self.mount_record(self.root)]
        with self.helper_environment(mounts, self.fake_source_transfer) as (run, output):
            exec(runner._prepare_program("gs://unit-tests-only/source"), {})
            run.assert_called_once()
            self.assertEqual(json.loads(output.getvalue())["mountinfo"], mounts[-1])

    def test_missing_mount_record_rejected(self):
        with self.helper_environment([]) as (run, output):
            with self.assertRaisesRegex(RuntimeError, "Cannot identify the workspace backing filesystem"):
                exec(runner._prepare_program("gs://unit-tests-only/source"), {})
            run.assert_not_called()

    def test_failed_transfer_has_no_prepared_or_completion_marker(self):
        with self.helper_environment([self.mount_record(self.root)],
                subprocess.CalledProcessError(1, ["mocked-rsync"])):
            with self.assertRaises(subprocess.CalledProcessError):
                exec(runner._prepare_program("gs://unit-tests-only/source"), {})
            self.assertFalse((self.root / "_PREPARED.json").exists())
            with self.assertRaisesRegex(RuntimeError, "Source preparation did not finish"):
                exec(runner._collect_program("gs://unit-tests-only/output", "fixture-job"), {})
            self.assertFalse((self.root / runner.TRANSFER_MARKER).exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
