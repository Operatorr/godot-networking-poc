#!/usr/bin/env python3
"""A climb run must not lie about what it built, and must not lose evidence or leak a server."""
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
import climb


class BuildScript(unittest.TestCase):
    """Runs the real shell text against a stand-in cargo."""

    def run_with_cargo(self, exit_code):
        with tempfile.TemporaryDirectory() as tmp:
            cargo = Path(tmp) / "cargo"
            cargo.write_text(f"#!/bin/sh\necho cargo-said-this\nexit {exit_code}\n")
            cargo.chmod(cargo.stat().st_mode | stat.S_IXUSR)
            script = climb.build_script(repo=tmp, cargo=str(cargo), log=str(Path(tmp) / "build.log"))
            return subprocess.run(["sh", "-c", script], text=True, capture_output=True)

    def test_failed_cargo_fails_the_script_and_still_shows_its_output(self):
        r = self.run_with_cargo(101)
        self.assertEqual(r.returncode, 101)
        self.assertIn("cargo-said-this", r.stdout)

    def test_successful_cargo_passes(self):
        self.assertEqual(self.run_with_cargo(0).returncode, 0)


class CmdBuild(unittest.TestCase):
    def build(self, remote, check_output):
        with mock.patch.object(climb, "setup_remote"), mock.patch.object(climb, "add_bin") as add_bin, \
                mock.patch.object(climb, "ssh_cmd", return_value=["ssh"]), \
                mock.patch.object(climb, "remote", side_effect=remote) as remote_mock, \
                mock.patch.object(climb.sp, "check_output", side_effect=check_output), \
                mock.patch.object(climb.sp, "run") as run:
            try:
                climb.cmd_build(mock.Mock(ref="abc"))
                raised = None
            except (SystemExit, subprocess.CalledProcessError) as exc:
                raised = exc
        return raised, add_bin, [c.args[0] for c in remote_mock.call_args_list], run

    @staticmethod
    def git_ok(args, **_):
        return "commit\n" if args[1] == "rev-parse" else b"archive-bytes"

    def test_failed_build_registers_and_copies_nothing(self):
        def remote(cmd, **_):
            if "cargo" in cmd:
                raise SystemExit("remote failed (101)")
            return "digest  path\n"
        raised, add_bin, commands, _ = self.build(remote, self.git_ok)
        self.assertIsInstance(raised, SystemExit)
        add_bin.assert_not_called()
        self.assertFalse([c for c in commands if "sha256sum" in c or " cp " in c])

    def test_failed_archive_reaches_neither_the_host_nor_cargo(self):
        def git(args, **_):
            if args[1] == "rev-parse":
                return "commit\n"
            raise subprocess.CalledProcessError(128, args)
        raised, add_bin, commands, run = self.build(lambda cmd, **_: "digest  path\n", git)
        self.assertIsInstance(raised, subprocess.CalledProcessError)
        run.assert_not_called()
        self.assertEqual(commands, [])
        add_bin.assert_not_called()

    def test_successful_build_registers_the_requested_commit(self):
        raised, add_bin, _, run = self.build(lambda cmd, **_: "digest0000  path\n", self.git_ok)
        self.assertIsNone(raised)
        self.assertEqual(run.call_args.kwargs["input"], b"archive-bytes")
        add_bin.assert_called_once_with("digest0000", "commit", "abc")


class StopRemote(unittest.TestCase):
    def stop_command(self, output=""):
        with mock.patch.object(climb, "remote", return_value=output) as remote:
            climb.stop_remote()
        return remote.call_args.args[0]

    def test_sampler_pattern_matches_the_sampler_but_not_the_stop_script(self):
        # procps pkill -f spares only itself, so the shell running this text must not match.
        self.assertIsNone(re.search(climb.SAMPLER_PATTERN, self.stop_command()))
        sampler = f"python3 {climb.R_HOME}/scripts/sample_host.py --out host.ndjson"
        self.assertIsNotNone(re.search(climb.SAMPLER_PATTERN, sampler))

    def test_pattern_is_quoted_so_the_shell_cannot_expand_it(self):
        self.assertIn(f"'{climb.SAMPLER_PATTERN}'", self.stop_command())

    def test_a_server_that_survives_is_an_error(self):
        with self.assertRaisesRegex(SystemExit, "still running"):
            self.stop_command("4242\n")


class FakeProcess:
    def __init__(self, polls):
        self.polls, self.pid, self.returncode, self.killed = list(polls), 4242, None, False

    def poll(self):
        if self.polls:
            self.returncode = self.polls.pop(0)
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode

    def terminate(self):
        pass


class RunTrial(unittest.TestCase):
    """The failure points around a trial's first remote launch and its end."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.trial = Path(tmp.name) / "session/01-arm"
        self.swarm = FakeProcess([None, 0])
        self.calls = []
        self.fail_startup = self.fail_stop = self.fail_collect = None
        self.ps_returncode = 0
        for target, kwargs in (("arm_config", {"return_value": b"{}"}), ("push_config", {"return_value": ("cfg", "sha")}),
                               ("preflight", {"return_value": {}}), ("config_diff", {"return_value": {}}),
                               ("harness_hashes", {"return_value": {}}), ("ssh_cmd", {"return_value": ["ssh"]}),
                               ("remote", {"side_effect": self.remote}),
                               ("collect_remote", {"side_effect": self.collect})):
            patcher = mock.patch.object(climb, target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        for target, kwargs in ((climb.sp, {"attribute": "Popen", "side_effect": self.popen}),
                               (climb.sp, {"attribute": "check_output", "return_value": "netstat"}),
                               (climb.sp, {"attribute": "run", "side_effect": self.sp_run}),
                               (climb.time, {"attribute": "sleep"})):
            patcher = mock.patch.object(target, **kwargs)
            patcher.start()
            self.addCleanup(patcher.stop)
        stderr = mock.patch.object(sys, "stderr", new=open(os.devnull, "w"))
        stderr.start()
        self.addCleanup(sys.stderr.close)
        self.addCleanup(stderr.stop)

    def remote(self, cmd, **_):
        if "nohup timeout" in cmd:
            self.calls.append("start")
            if self.fail_startup:
                raise self.fail_startup
            return ""
        if "pkill -INT" in cmd:
            self.calls.append("stop")
            if self.fail_stop:
                raise self.fail_stop
            return ""
        return "effective_receive_bytes=524288"

    def collect(self, trial, rdir):
        self.calls.append("collect")
        if self.fail_collect:
            raise self.fail_collect

    def popen(self, args, **_):
        return self.swarm if args[0] == str(climb.BOT) else FakeProcess([0])

    def sp_run(self, args, **_):
        return subprocess.CompletedProcess(args, self.ps_returncode, stdout="PID TIME %CPU\n", stderr="")

    def run_trial(self):
        return climb.run_trial(self.trial, "n", {"sha256": "s" * 64, "commit": "c"}, {}, 225, 70)

    def manifest(self):
        return json.loads((self.trial / "run.json").read_text())

    def test_bots_exiting_before_ps_is_a_normal_end_of_run(self):
        self.ps_returncode = 1
        self.assertEqual(self.run_trial(), 0)
        self.assertEqual(self.calls, ["start", "stop", "collect"])
        self.assertEqual(self.manifest()["exit"], 0)
        self.assertNotIn("error", self.manifest())

    def test_a_failed_sample_while_bots_run_does_not_stop_the_run(self):
        self.swarm = FakeProcess([None, None, None, 0])
        self.ps_returncode = 1
        self.assertEqual(self.run_trial(), 0)
        self.assertFalse(self.swarm.killed)

    def test_startup_failure_after_launch_stops_and_collects_and_keeps_its_error(self):
        self.fail_startup = SystemExit("ssh dropped during startup")
        with self.assertRaisesRegex(SystemExit, "ssh dropped during startup"):
            self.run_trial()
        self.assertEqual(self.calls, ["start", "stop", "collect"])
        manifest = self.manifest()
        self.assertIsNone(manifest["exit"])
        self.assertEqual(manifest["error"], "ssh dropped during startup")

    def test_startup_timeout_is_cleaned_up_too(self):
        self.fail_startup = subprocess.TimeoutExpired("ssh", 120)
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_trial()
        self.assertEqual(self.calls, ["start", "stop", "collect"])

    def test_failed_stop_still_collects_and_keeps_the_original_error(self):
        self.fail_startup = SystemExit("original")
        self.fail_stop = SystemExit("stop failed")
        with self.assertRaisesRegex(SystemExit, "original"):
            self.run_trial()
        self.assertEqual(self.calls, ["start", "stop", "collect"])
        self.assertEqual(self.manifest()["cleanup_errors"], ["stop server: stop failed"])

    def test_failed_collection_keeps_the_original_error_and_writes_the_manifest(self):
        self.fail_startup = SystemExit("original")
        self.fail_collect = subprocess.CalledProcessError(255, "tar")
        with self.assertRaisesRegex(SystemExit, "original"):
            self.run_trial()
        self.assertIn("collect evidence", self.manifest()["cleanup_errors"][0])

    def test_failed_cleanup_on_a_good_run_fails_the_trial(self):
        self.fail_stop = SystemExit("stop failed")
        with self.assertRaisesRegex(SystemExit, "trial cleanup failed.*stop failed"):
            self.run_trial()
        self.assertEqual(self.calls, ["start", "stop", "collect"])

    def test_refused_preflight_starts_nothing_and_leaves_no_trial_directory(self):
        climb.preflight.side_effect = SystemExit("competing server present")
        with self.assertRaisesRegex(SystemExit, "competing server"):
            self.run_trial()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.trial.exists())


class RefuseUsedTrial(unittest.TestCase):
    def test_a_leftover_attempt_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(SystemExit, "move it aside"):
                climb.refuse_used_trial(Path(tmp))

    def test_a_new_trial_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            climb.refuse_used_trial(Path(tmp) / "new")


if __name__ == "__main__":
    unittest.main()
