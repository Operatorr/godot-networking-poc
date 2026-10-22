"""Exercise real controller teardown with mocked hosts; never launch a workload."""
import ast
import contextlib
import datetime
import io
import json
import pathlib
import re
import shlex
import types
import unittest


CONTROLLERS = (
    'baseline', 'control', 'bitmap', 'profile', 'bounded', 'buffer',
    'capacity150', 'generator_profile', 'generator_profile_fixed', 'dodge150', 'send150',
)
SCORED = ('capacity150', 'generator_profile', 'generator_profile_fixed', 'dodge150', 'send150')


def teardown(name, fail_command=lambda role, command: False, fail_first_dump=False,
             game_stopped=True):
    # Compile the complete real finally body, retaining its nested handlers and
    # ordering. Only dependencies are replaced; no SSH/process APIs are reachable.
    path = pathlib.Path(__file__).with_name('udp_' + name + '.py')
    tree = ast.parse(path.read_text())
    controller = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'controller')
    final = next(n for n in controller.body if isinstance(n, ast.Try)).finalbody
    calls, writes, audits = [], [], []

    def ssh(role, command):
        calls.append((role, command))
        if fail_command(role, command):
            raise OSError('injected host failure')
        if 'workload-start.json' in command:
            return json.dumps({'utc_ns': 1})
        if 'guard-result.json' in command:
            return json.dumps({'ended_utc_ns': 2})
        return ''

    def dump(path, value):
        writes.append((path.name, dict(value)))
        if fail_first_dump and len(writes) == 1:
            raise OSError('injected local write failure')

    def snapshot(role, label):
        audits.append(role)
        # An unavailable audit should be recorded and must not stop other hosts.
        raise OSError('audit unavailable')

    env = dict(
        time=types.SimpleNamespace(time_ns=lambda: 100, sleep=lambda _: None),
        datetime=datetime, json=json, re=re, shlex=shlex, pathlib=pathlib,
        ssh=ssh, dump=dump, snapshot=snapshot,
        manifest={'experiment_service_start_ns': 1, 'service_invocation': 'invocation'},
        cleanup={}, staged=['game', 'bots'], game_stopped=game_stopped,
        override_installed=True, restoration_armed=True,
        UNIT='owned-unit', SERVICE='game-service', REMOTE='/owned',
        local=pathlib.Path('/unused'), copy=lambda *args: None,
        publish_file=lambda *args: None,
    )
    code = compile(ast.Module(body=final, type_ignores=[]), str(path), 'exec')
    with contextlib.redirect_stdout(io.StringIO()):
        exec(code, env)
    return calls, writes, audits, env


class CleanupTests(unittest.TestCase):
    def assert_completed(self, result):
        calls, writes, audits, _ = result
        self.assertTrue(any('restore.sh' in command for _, command in calls))
        self.assertEqual(set(audits), {'game', 'bots'})
        self.assertIn('cleanup.json', [name for name, _ in writes])

    def test_normal_teardown_restores_and_publishes(self):
        for name in CONTROLLERS:
            with self.subTest(controller=name):
                self.assert_completed(teardown(name))

    def test_failed_socket_snapshot_does_not_skip_resource_release(self):
        for name in CONTROLLERS:
            with self.subTest(controller=name):
                result = teardown(name, lambda role, command: 'final-sockets.txt' in command)
                self.assert_completed(result)
                commands = [command for _, command in result[0]]
                self.assertTrue(any('systemctl stop owned-unit-swarm' in c for c in commands))
                for role in ('game', 'bots'):
                    self.assertTrue(any('systemctl stop owned-unit-' + role + '-collect' in c for c in commands))

    def test_bot_stop_failure_still_restores_and_publishes(self):
        for name in CONTROLLERS:
            with self.subTest(controller=name):
                result = teardown(name, lambda role, command: 'systemctl stop owned-unit-swarm' in command)
                self.assert_completed(result)
                commands = [command for _, command in result[0]]
                self.assertTrue(any('systemctl stop owned-unit-bots-collect' in c for c in commands))

    def test_journal_failure_does_not_skip_restoration(self):
        for name in SCORED:
            with self.subTest(controller=name):
                self.assert_completed(teardown(name, lambda role, command: ' journal --since-ns ' in command))

    def test_initial_manifest_write_failure_does_not_skip_restoration(self):
        for name in CONTROLLERS:
            with self.subTest(controller=name):
                self.assert_completed(teardown(name, fail_first_dump=True))

    def test_partial_setup_keeps_untouched_game_service_running(self):
        for name in CONTROLLERS:
            with self.subTest(controller=name):
                calls, writes, _, _ = teardown(name, game_stopped=False)
                self.assertFalse(any(command == 'sudo -n systemctl stop game-service'
                                     for _, command in calls))
                self.assertFalse(any('restore.sh' in command for _, command in calls))
                self.assertIn('cleanup.json', [name for name, _ in writes])

    def test_failed_game_stop_has_no_verified_stop_timestamp(self):
        for name in SCORED:
            with self.subTest(controller=name):
                result = teardown(name, lambda role, command: command == 'sudo -n systemctl stop game-service')
                self.assert_completed(result)
                self.assertNotIn('game_stopped_utc_ns', result[3]['manifest'])


if __name__ == '__main__':
    unittest.main()
