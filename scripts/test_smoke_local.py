"""Focused local-smoke recovery regressions; no database, game ports or credentials."""

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

import smoke_local as smoke


class Process:
    def __init__(self, pid=123456789):
        self.pid = pid
        self.returncode = None

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        self.returncode = 0
        return 0


class SmokeTests(unittest.TestCase):
    def make_run(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        run = smoke.SmokeRun.__new__(smoke.SmokeRun)
        run.directory = Path(temporary.name)
        run.command = run.directory / "command.txt"
        run.command.write_text("sanctuary")
        run.processes = {}
        run.log_handles = []
        run.user_dirs = []
        run.results = {"result": "PASS", "stages": {}}
        run.started = time.monotonic()
        run.deadline = run.started + 18.5
        run.args = argparse.Namespace(timeout=20)
        run.env = {}
        run.godot = Path("/unused/godot")
        run.api_url = "http://127.0.0.1:1"
        run.stage = "test"
        return run

    def fake_group_shutdown(self, calls):
        def killpg(pid, signum):
            if signum == 0:
                raise ProcessLookupError
            calls.append((pid, signum))
        return mock.patch.object(smoke.os, "killpg", side_effect=killpg)

    def test_command_write_failure_still_stops_processes_and_reports_failure(self):
        run = self.make_run()
        run.results["error"] = "original startup failure"
        run.command = mock.Mock()
        run.command.write_text.side_effect = OSError("disk full")
        process = Process()
        process.returncode = 0
        run.processes = {"api": process}
        calls = []
        with self.fake_group_shutdown(calls):
            run.cleanup()
        self.assertTrue(calls)
        self.assertEqual(run.results["result"], "FAIL")
        self.assertEqual(run.results["error"], "original startup failure")
        self.assertTrue(run.results["cleanup_errors"])
        self.assertTrue((run.directory / "result.json").exists())

    def test_directory_failure_does_not_skip_other_artifacts_or_credentials(self):
        run = self.make_run()
        user_dir = run.directory / "user"
        user_dir.mkdir()
        pgdata = run.directory / "pgdata"
        pgdata.mkdir()
        credentials = run.directory / "client-credentials.json"
        credentials.write_text("disposable fixture")
        partial = run.directory / "bot-credentials.tmp"
        partial.write_text("interrupted fixture write")
        run.user_dirs = [user_dir]
        remove = smoke.shutil.rmtree

        def remove_or_fail(path):
            if path == user_dir:
                raise PermissionError("cannot remove this directory")
            remove(path)

        with mock.patch.object(smoke.shutil, "rmtree", side_effect=remove_or_fail):
            run.cleanup()
        self.assertFalse(pgdata.exists())
        self.assertFalse(credentials.exists())
        self.assertFalse(partial.exists())
        self.assertEqual(run.results["result"], "FAIL")
        self.assertTrue(run.results["cleanup_errors"])

    def test_failed_handle_close_does_not_skip_next_handle_or_report(self):
        run = self.make_run()
        broken, healthy = mock.Mock(), mock.Mock()
        broken.close.side_effect = OSError("flush failed")
        run.log_handles = [broken, healthy]
        run.cleanup()
        healthy.close.assert_called_once()
        self.assertEqual(run.results["result"], "FAIL")
        self.assertTrue((run.directory / "result.json").exists())

    @unittest.skipUnless(os.name == "posix", "runner owns POSIX process groups")
    def test_exited_leader_does_not_leave_sigterm_resistant_child(self):
        run = self.make_run()
        ready = run.directory / "child.pid"
        child_code = (
            "import os,signal,time,pathlib;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            f"pathlib.Path({str(ready)!r}).write_text(str(os.getpid()));"
            "time.sleep(60)"
        )
        parent_code = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{child_code!r}]);"
            "time.sleep(60)"
        )
        parent = subprocess.Popen([sys.executable, "-c", parent_code], start_new_session=True)
        run.processes = {"initdb": parent}
        try:
            until = time.monotonic() + 3
            while not ready.exists() and time.monotonic() < until:
                time.sleep(0.01)
            child_pid = int(ready.read_text())
            run.cleanup()
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
            self.assertTrue(run.results["processes_stopped"])
        finally:
            try:
                os.killpg(parent.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            parent.wait(timeout=1)

    def prepare_with_sources(self, changes):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        build = Path(temporary.name)
        state = {"sources": "before"}

        def command(args, **kwargs):
            if changes and "--editor" in args:
                state["sources"] = "after"
            return subprocess.CompletedProcess(args, 0, stdout="")

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(smoke, "BUILD", build))
        stack.enter_context(mock.patch.object(smoke, "source_fingerprint", side_effect=lambda: state["sources"]))
        stack.enter_context(mock.patch.object(smoke.subprocess, "run", side_effect=command))
        stack.enter_context(mock.patch.object(smoke.subprocess, "check_output", return_value=b"Godot-test"))
        stack.enter_context(mock.patch.object(smoke.shutil, "copy2"))
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        return build

    def test_source_edit_during_preparation_cannot_publish_ready_marker(self):
        build = self.prepare_with_sources(changes=True)
        with self.assertRaisesRegex(smoke.SmokeFailure, "[Ss]ources changed"):
            smoke.prepare(Path("/mock/godot"))
        self.assertFalse((build / "prepared.json").exists())

    def test_unchanged_preparation_publishes_matching_marker(self):
        build = self.prepare_with_sources(changes=False)
        smoke.prepare(Path("/mock/godot"))
        self.assertEqual(json.loads((build / "prepared.json").read_text())["sources"], "before")

    def exercise_final_shutdown(self, crashed_service=None):
        run = self.make_run()
        services = ("postgres", "redis", "api", "sanctuary", "arena")
        run.processes = {name: Process() for name in services}
        run.processes["initdb"] = Process()
        run.processes["initdb"].returncode = 0
        run.start_services = mock.Mock()
        run.start_servers = mock.Mock()
        run.create_accounts = mock.Mock(return_value={role: {"character_name": role} for role in smoke.ROLES})
        run.create_project = mock.Mock(return_value=run.directory)
        run.wait_for = mock.Mock()
        run.ready = mock.Mock(return_value=True)
        run.status = mock.Mock(return_value={"monsters": 1, "shots": 1, "monster_interactions": 1})
        run.request = mock.Mock(return_value={"regions": [{"id": "local"}]})
        run.say = mock.Mock()

        def launch(role, *args):
            process = Process()

            def wait(timeout=None):
                if role == "client" and crashed_service:
                    run.processes[crashed_service].returncode = -9
                process.returncode = 0
                return 0

            process.wait = wait
            run.processes[role] = process

        run.launch = launch
        with mock.patch.object(smoke.socket, "socket"):
            run.run()
        return run

    def test_each_service_exit_during_client_shutdown_fails(self):
        for service in ("postgres", "redis", "api", "sanctuary", "arena"):
            with self.subTest(service=service):
                with self.assertRaisesRegex(smoke.SmokeFailure, service):
                    self.exercise_final_shutdown(service)

    def test_expected_client_exits_allow_success_when_services_live(self):
        self.assertEqual(self.exercise_final_shutdown().results["result"], "PASS")

    def test_cleanup_failure_changes_successful_main_exit_to_failure(self):
        run = self.make_run()
        run.run = mock.Mock()
        run.say = mock.Mock()

        def cleanup():
            run.results["result"] = "FAIL"

        run.cleanup = cleanup
        for name in ("api", "keygen", "omega-server"):
            (run.directory / name).touch()
        smoke.write_json(run.directory / "prepared.json", {"sources": "same", "godot_version": "test"})
        with mock.patch.object(sys, "argv", ["smoke_local.py"]), \
             mock.patch.object(smoke, "BUILD", run.directory), \
             mock.patch.object(smoke, "source_fingerprint", return_value="same"), \
             mock.patch.object(smoke, "executable", return_value=Path("/unused")), \
             mock.patch.object(smoke.subprocess, "check_output", return_value=b"test"), \
             mock.patch.object(smoke, "SmokeRun", return_value=run), \
             mock.patch.object(smoke.signal, "signal"):
            self.assertEqual(smoke.main(), 1)


if __name__ == "__main__":
    unittest.main()
