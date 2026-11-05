"""The real guest runner as real processes on this machine: fences, identity, bounds, sockets and sealing.

Stand-in workloads hold real sockets and take real signals. What cannot run here is named where it is faked: ``tc`` is a
scripted program, and the systemd path runs through shims. Neither says anything about a real Droplet.
"""
import argparse
import errno
import json
import os
import pathlib
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

import fake_run_guest
import guest_runner
import run_checks
import run_executor
import run_fixtures as rf
import run_plan
import scoring_fixtures as sf
import search

SESSION = 'do-local-guest-a'
HERE = pathlib.Path(__file__).parent
PROC_NET_UDP = """  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode ref pointer drops
  611: 00000000:1F91 00000000:0000 07 00000000:00000200 00:00000000 00000000  1000        0 91234 2 ffff8e0 7
  612: 0100007F:1F92 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 91235 2 ffff8e1 0
"""


def wait_until(predicate, limit_s=10.0):
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError('the condition was not reached')


def _alive(pid):
    """A live process, as cgroup.procs lists one: a zombie is not listed, and a reaped pid is gone."""
    return guest_runner.process_start_id(pid) is not None


class GuestFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.addCleanup(rf.make_writable, temporary.name)
        self.root = pathlib.Path(temporary.name)
        self.game_port, self.metrics_port = rf.free_ports()
        self.hosts = rf.install_local_hosts(self.root, self.game_port, self.metrics_port, workload_seconds=0.3)
        self.guests = self.hosts.guests
        self.adapter = self.hosts.adapter
        self.sha = run_executor.sha256_path(run_executor.RUNNER_SOURCE)
        self.runner = run_plan.runner_remote_path(self.sha)
        for role in ('game', 'bot'):
            self.guests.put(role, str(run_executor.RUNNER_SOURCE), self.runner, 5)
        programs = self.adapter.program_paths()
        self.manifest = dict(session=dict(id=SESSION), workload={}, source=dict(benchmark_sha='a' * 40, server_config_sha256=run_executor.sha256_path(self.adapter.config_path()),
                                                                                binary_sha256=dict(game=run_executor.sha256_path(programs['game']), bot=run_executor.sha256_path(programs['bot']))))
        self.sampler_sha = run_executor.sha256_path(self.adapter.sampler_path('game'))
        self.addCleanup(self.kill_all)

    def kill_all(self):
        for line in guest_runner.process_table() or ():
            if str(self.root) in line and line.split()[0].isdigit() and int(line.split()[0]) != os.getpid():
                try:
                    os.kill(int(line.split()[0]), signal.SIGKILL)
                except OSError:
                    pass

    def do(self, role, command, *arguments):
        result = self.guests.run(role, ['python3', self.runner, command] + list(arguments), 30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def trial(self, ordinal=1, target=25):
        return search.Trial(search.run_id(SESSION, ordinal, search.COARSE, target, 1), ordinal, search.COARSE, target, 1, search.EXPLORATION_HOLD_S, ())

    def plan(self, role='game', trial=None, token=1, bound_s=30.0, stop_grace_s=1.0, unit_mode=guest_runner.PROCESS_GROUP, launch_slack_s=60.0, stop_slack_s=600.0):
        return run_plan.role_plan(self.adapter, self.manifest, 'b' * 64, trial or self.trial(), role, dict(game='127.0.0.1', bot='127.0.0.1'), self.sampler_sha, token, unit_mode,
                                  time.time() + launch_slack_s, bound_s, time.time() + stop_slack_s, stop_grace_s)

    def fence(self, role='game', token=1):
        return self.do(role, 'fence', '--session', SESSION, '--token', str(token))

    def grant(self, plan):
        """The guest's half of a grant, with the same window as the plan. A host that refuses to mint leaves the plan as it was, and the start reports why."""
        minted = self.do(plan['role'], 'grant_prepare', '--session', plan['session_id'], '--token', str(plan['fencing_token']))
        return dict(plan, grant=dict(id=minted['grant_id'], ttl_s=max(0.0, plan['launch_not_after_wall'] - time.time()))) if minted.get('ok') else plan

    def start(self, plan):
        plan = plan if 'grant' in plan else self.grant(plan)
        return self.do(plan['role'], 'start', '--plan-json', json.dumps(plan))

    def status(self, plan):
        return self.do(plan['role'], 'status', '--run-id', plan['run_id'], '--role', plan['role'])

    def stop(self, plan, token=1, reason='test', wait_s=5.0):
        return self.do(plan['role'], 'stop', '--run-id', plan['run_id'], '--role', plan['role'], '--token', str(token), '--reason', reason, '--wait-s', str(wait_s))

    def seal(self, plan, token=1, *extra):
        return self.do(plan['role'], 'seal', '--run-id', plan['run_id'], '--role', plan['role'], '--token', str(token), *extra)

    def tree(self, plan):
        return self.guests.runner_root(plan['role']) / 'runs' / plan['run_id'] / plan['role']


class Fencing(GuestFixture):
    def test_the_fence_only_rises_and_a_replaced_controller_cannot_start_anything(self):
        self.assertTrue(self.fence(token=3)['raised'])
        self.assertFalse(self.fence(token=3)['raised'])
        lower = self.fence(token=2)
        self.assertEqual((lower['ok'], lower['code']), (False, 'stale_fence'))
        refused = self.start(self.plan(token=2))
        self.assertEqual(refused['code'], 'stale_fence')
        self.assertFalse(self.tree(self.plan(token=2)).exists(), 'a refused start leaves no directory')

    def test_a_start_with_no_fence_is_refused(self):
        self.assertEqual(self.start(self.plan())['code'], 'not_fenced')

    def test_another_session_cannot_fence_this_host(self):
        self.fence()
        document = self.do('game', 'fence', '--session', 'other-session', '--token', '9')
        self.assertEqual(document['code'], 'foreign_session')

    def test_a_closed_fence_stays_closed_refuses_starts_and_still_lets_a_run_be_stopped_and_sealed(self):
        self.fence()
        plan = self.plan()
        self.assertTrue(self.start(plan)['ok'])
        closed = self.do('game', 'fence', '--session', SESSION, '--token', '1', '--close', 'operator abort')
        self.assertEqual(closed['closed'], 'operator abort')
        self.stop(plan)
        self.assertTrue(self.seal(plan)['ok'])
        late = self.plan(trial=self.trial(2, 50))
        self.assertEqual(self.start(late)['code'], 'session_closed')
        self.assertFalse(self.tree(late).exists(), 'a refused start leaves no directory')
        raised = self.fence(token=2)
        self.assertEqual(raised['closed'], 'operator abort', 'a newer controller cannot reopen it')
        self.assertEqual(self.start(self.plan(trial=self.trial(2, 50), token=2))['code'], 'session_closed')

    def test_a_run_directory_with_no_plan_still_answers_only_to_the_current_token(self):
        self.fence(token=2)
        tree = self.tree(self.plan())
        tree.mkdir(parents=True)
        document = self.do('game', 'stop', '--run-id', self.plan()['run_id'], '--role', 'game', '--token', '1', '--reason', 'late')
        self.assertEqual(document['code'], 'stale_fence')
        self.assertEqual(self.seal(self.plan(), 1)['code'], 'stale_fence')

    def test_a_stale_controller_cannot_stop_or_seal_a_newer_run(self):
        self.fence()
        plan = self.plan()
        self.assertTrue(self.start(plan)['ok'])
        self.fence(token=2)
        self.assertEqual(self.stop(plan, token=1)['code'], 'stale_fence')
        self.assertEqual(self.seal(plan, 1)['code'], 'stale_fence')
        self.assertTrue(self.status(plan)['supervisor']['alive'])
        self.assertTrue(self.stop(plan, token=2)['stopped'])


class Launch(GuestFixture):
    def test_a_run_gets_fresh_identities_a_private_tree_and_an_independent_sampler(self):
        self.fence()
        first_plan = self.plan()
        first = self.start(first_plan)
        self.assertTrue(first['ok'], first)
        wait_until(lambda: self.status(first_plan)['socket'])
        self.stop(first_plan)
        self.seal(first_plan)
        second_plan = self.plan(trial=self.trial(2, 50))
        second = self.start(second_plan)
        self.assertTrue(second['ok'], second)
        wait_until(lambda: self.status(second_plan)['socket'])
        self.assertNotEqual(first['processes']['game']['pid'], second['processes']['game']['pid'])
        self.assertNotEqual(first['processes']['sampler']['pid'], second['processes']['sampler']['pid'])
        self.assertNotEqual(first['processes']['game']['pid'], first['processes']['sampler']['pid'], 'the sampler is its own process')
        self.assertNotEqual(self.tree(first_plan), self.tree(second_plan))
        ledger = self.do('game', 'inspect')['ledger']
        self.assertEqual(run_checks.launch_problems(second_plan, second, [e for e in ledger if e['run_id'] != second_plan['run_id']]), [])
        self.assertEqual(run_checks.socket_problems(second_plan, self.status(second_plan), [e for e in ledger if e['run_id'] != second_plan['run_id']], False), [])

    def test_a_second_start_while_one_is_active_is_an_overlap(self):
        self.fence()
        self.start(self.plan())
        self.assertEqual(self.start(self.plan(trial=self.trial(2, 50)))['code'], 'overlap')

    def test_the_same_run_id_can_never_start_again(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        self.seal(plan)
        before = run_executor.sha256_path(self.tree(plan) / guest_runner.SEAL)
        self.assertEqual(self.start(plan)['code'], 'duplicate_run_dir')
        self.assertEqual(run_executor.sha256_path(self.tree(plan) / guest_runner.SEAL), before, 'nothing was overwritten')

    def test_a_plan_cannot_name_a_path_outside_its_run_tree(self):
        self.fence()
        for changes in (dict(role='../../escape'), dict(run_id='../escape'), dict(schema='other')):
            document = self.do('game', 'start', '--plan-json', json.dumps(dict(self.plan(), **changes)))
            self.assertEqual(document['code'], 'bad_request', changes)
        self.assertFalse((self.guests.runner_root('game') / 'escape').exists())

    def test_a_late_start_request_is_refused_on_the_guest(self):
        self.fence()
        self.assertEqual(self.start(self.plan(launch_slack_s=-5.0))['code'], 'launch_window_closed')

    def test_slow_preparation_past_the_window_starts_nothing(self):
        self.fence()
        plan = self.grant(self.plan(launch_slack_s=0.2, bound_s=2, stop_grace_s=0.1))
        host = guest_runner.Host(self.guests.runner_root('game'))
        real = guest_runner.host_facts

        def slow(host_, plan_):
            facts = real(host_, plan_)
            time.sleep(1.5)
            return facts
        with mock.patch.object(guest_runner, 'host_facts', side_effect=slow), self.assertRaises(guest_runner.Refused) as caught:
            guest_runner.cmd_start(types.SimpleNamespace(plan_json=json.dumps(plan)), host)
        self.assertEqual(caught.exception.code, 'launch_window_closed')
        self.assertFalse(self.tree(plan).exists(), 'no directory and no workload')
        self.assertEqual(self.do('game', 'inspect')['active'], None)

    def test_a_workload_that_no_longer_fits_after_preparation_starts_nothing(self):
        self.fence()
        plan = dict(self.plan(), minimum_bound_s=120.0, stop_by_wall=time.time() + 60.0)
        self.assertEqual(self.start(plan)['code'], 'launch_window_closed')
        self.assertFalse(self.tree(plan).exists())

    def supervise_directly(self, plan):
        host = guest_runner.Host(self.guests.runner_root('game'))
        tree = self.tree(plan)
        tree.mkdir(parents=True)
        (tree / 'plan.json').write_text(json.dumps(plan))
        with mock.patch.object(guest_runner, '_spawn', side_effect=AssertionError('no workload may be created')):
            guest_runner.cmd_supervise(types.SimpleNamespace(run_dir=str(tree)), host)
        return guest_runner.read_json(tree / 'result.json')

    def test_a_supervisor_scheduled_past_the_window_creates_no_workload(self):
        self.fence()
        result = self.supervise_directly(self.grant(self.plan(launch_slack_s=-5.0)))
        self.assertEqual((result['refused'], result['processes']), ('launch_window_closed', {}))

    def test_a_supervisor_finds_a_fence_that_rose_or_closed_while_it_was_scheduled(self):
        self.fence(token=2)
        self.assertEqual(self.supervise_directly(self.plan(token=1))['refused'], 'stale_fence')
        self.do('game', 'fence', '--session', SESSION, '--token', '2', '--close', 'abort')
        self.assertEqual(self.supervise_directly(self.plan(trial=self.trial(2, 50), token=2))['refused'], 'session_closed')

    def test_a_supervisor_that_finds_a_stop_request_creates_no_workload(self):
        self.fence()
        plan = self.grant(self.plan())
        tree = self.tree(plan)
        tree.mkdir(parents=True)
        (tree / 'stop.request').write_text('{}')
        (tree / 'plan.json').write_text(json.dumps(plan))
        with mock.patch.object(guest_runner, '_spawn', side_effect=AssertionError('no workload may be created')):
            guest_runner.cmd_supervise(types.SimpleNamespace(run_dir=str(tree)), guest_runner.Host(self.guests.runner_root('game')))
        self.assertEqual(guest_runner.read_json(tree / 'result.json')['refused'], 'stop_requested')

    def test_a_refusal_from_the_supervisor_reaches_the_start_with_its_own_code(self):
        tree = self.root / 'handshake'
        tree.mkdir()
        (tree / 'result.json').write_text(json.dumps(dict(refused='launch_window_closed', stop_reason='launch_refused:late')))
        with self.assertRaises(guest_runner.Refused) as caught:
            guest_runner._await_handshake(tree)
        self.assertEqual(caught.exception.code, 'launch_window_closed')

    def test_the_bound_counts_from_the_actual_launch_not_from_the_plan(self):
        self.fence()
        plan = self.plan(bound_s=60.0, stop_grace_s=0.2, stop_slack_s=1.5)
        self.assertTrue(self.start(plan)['ok'])
        identity = guest_runner.read_json(self.tree(plan) / 'identity.json')
        self.assertLessEqual(identity['bound_s'], 1.5, 'what is left of the absolute limit, not the requested 60 s')
        final = wait_until(lambda: (lambda s: s if s['result'] else None)(self.status(plan)), 10.0)
        self.assertLessEqual(final['result']['bound_s'], 1.5)

    def test_changed_program_or_config_bytes_are_refused_immediately_before_launch(self):
        self.fence()
        plan = self.plan()
        pathlib.Path(self.adapter.config_path()).write_text('{"changed": true}\n')
        document = self.start(plan)
        self.assertEqual(document['code'], 'hash_mismatch')
        self.assertIn('server_config.json', document['detail'])

    def test_a_leftover_process_refuses_the_start_and_the_preflight_names_it(self):
        self.fence()
        program = self.adapter.program_paths()['game']
        leftover = subprocess.Popen([program, '--port', str(rf.free_ports(1)[0])], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (leftover.kill(), leftover.wait()))
        plan = self.plan()
        facts = wait_until(lambda: (lambda f: f if f['leftovers'] else None)(self.do('game', 'preflight', '--plan-json', json.dumps(plan))))
        self.assertEqual([item['pid'] for item in facts['leftovers']], [leftover.pid])
        self.assertEqual(self.start(plan)['code'], 'leftover_process')

    def test_a_held_port_refuses_the_start(self):
        self.fence()
        plan = self.plan()
        held = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        held.bind(('127.0.0.1', self.game_port))
        self.addCleanup(held.close)
        self.assertEqual(self.start(plan)['code'], 'port_busy')
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        self.assertIn('port udp/%d still holds a socket' % self.game_port, run_checks.host_problems(plan, facts, facts['boot_id'], facts['runner_sha256']))

    def test_the_plan_text_on_the_command_line_is_not_mistaken_for_a_leftover(self):
        self.fence()
        plan = self.plan()
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        self.assertEqual(facts['leftovers'], [])

    def test_uncleared_impairment_reaches_the_rules_from_a_real_subprocess(self):
        plan = self.plan()
        self.fence()
        self.hosts.state_file.write_text(json.dumps([dict(kind='prio', dev='lo0'), dict(kind='netem', dev='lo0')]))
        facts = self.do('game', 'preflight', '--plan-json', json.dumps(plan))
        problems = run_checks.host_problems(plan, facts, facts['boot_id'], facts['runner_sha256'])
        self.assertIn('qdisc netem is not a cleared state', problems)
        self.assertIn('qdisc prio is not a cleared state', problems)

    def test_missing_tc_is_unknown_not_clear(self):
        self.assertEqual(run_checks.impairment_problems(dict(available=False)), ['network impairment state could not be read'])
        self.assertEqual(run_checks.impairment_problems(None), ['network impairment state could not be read'])


class Bounds(GuestFixture):
    def test_a_workload_that_ignores_sigterm_still_ends_at_its_bound_with_no_controller(self):
        self.adapter.game_extra = ['--ignore-term']
        self.fence()
        plan = self.plan(bound_s=1.0, stop_grace_s=0.5)
        started = time.monotonic()
        self.assertTrue(self.start(plan)['ok'])
        final = wait_until(lambda: (lambda s: s if s['result'] else None)(self.status(plan)), 10.0)
        self.assertLess(time.monotonic() - started, 6.0)
        self.assertEqual(final['result']['stop_reason'], 'bound_exhausted')
        self.assertEqual(final['result']['processes']['game']['signal'], signal.SIGKILL)
        self.assertFalse(final['processes']['game']['alive'])

    def test_the_absolute_stop_time_holds_even_if_the_relative_bound_is_longer(self):
        self.fence()
        plan = self.plan(bound_s=60.0, stop_grace_s=0.2, stop_slack_s=0.8)
        self.assertTrue(self.start(plan)['ok'])
        final = wait_until(lambda: (lambda s: s if s['result'] else None)(self.status(plan)), 10.0)
        self.assertEqual(final['result']['stop_reason'], 'bound_exhausted')

    def test_a_dead_supervisor_cannot_leave_a_workload_running(self):
        self.fence()
        plan = self.plan()
        started = self.start(plan)
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_until(lambda: not self.status(plan)['supervisor']['alive'])
        self.assertTrue(self.status(plan)['processes']['game']['alive'], 'the workload outlived its supervisor, as a process group mode allows')
        stopped = self.stop(plan)
        self.assertTrue(stopped['stopped'])
        self.assertTrue(stopped['escalated'])
        self.assertFalse(self.status(plan)['processes']['game']['alive'])


class Identity(GuestFixture):
    def test_a_reused_pid_is_not_our_process_and_is_never_signalled(self):
        self.fence()
        plan = self.plan()
        started = self.start(plan)
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_until(lambda: not self.status(plan)['supervisor']['alive'])
        os.killpg(started['processes']['game']['pid'], signal.SIGKILL)
        # An unrelated process is given the numbers of the dead workload, as the kernel may do with a pid.
        stranger = subprocess.Popen([sys.executable, '-c', 'import os,time; os.setsid(); time.sleep(60)'])
        self.addCleanup(lambda: (stranger.kill(), stranger.wait()))
        tree = self.tree(plan)
        identity = json.loads((tree / 'identity.json').read_text())
        identity['processes']['game']['pid'] = stranger.pid
        identity['processes']['sampler']['pid'] = stranger.pid
        (tree / 'identity.json').write_text(json.dumps(identity))
        summary = self.status(plan)
        self.assertFalse(summary['processes']['game']['alive'], 'same pid, different start time: not ours')
        stopped = self.stop(plan)
        self.assertTrue(stopped['stopped'])
        self.assertIsNone(stranger.poll(), 'the stranger keeps running')

    def test_same_process_compares_the_kernel_start_time(self):
        me = guest_runner.identity_of(os.getpid())
        self.assertTrue(guest_runner.same_process(me))
        self.assertFalse(guest_runner.same_process(dict(me, start_id='ticks:1')))
        self.assertFalse(guest_runner.same_process(dict(me, start_id=None)))

    def test_same_process_needs_this_boot(self):
        me = guest_runner.identity_of(os.getpid())
        self.assertFalse(guest_runner.same_process(dict(me, boot_id='a-previous-boot')))
        self.assertFalse(guest_runner.same_process(dict(me, boot_id=None)), 'an identity with no boot proves nothing')
        with mock.patch.object(guest_runner, 'boot_id', return_value=None):
            self.assertFalse(guest_runner.same_process(me), 'and neither does a host whose boot cannot be read')

    def test_a_process_with_matching_numbers_from_another_boot_is_never_signalled(self):
        victim = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], start_new_session=True)
        self.addCleanup(lambda: (victim.kill(), victim.wait()))
        wait_until(lambda: guest_runner.process_start_id(victim.pid))
        identity = dict(guest_runner.identity_of(victim.pid), boot_id='a-previous-boot')
        with mock.patch.object(guest_runner.os, 'killpg', side_effect=AssertionError('never signalled')):
            self.assertFalse(guest_runner._signal_identity(identity, signal.SIGKILL))
        self.assertIsNone(victim.poll())

    def test_a_run_recorded_before_a_reboot_is_not_alive_and_its_stop_kills_nothing(self):
        self.fence()
        plan = self.plan()
        started = self.start(plan)
        tree = self.tree(plan)
        # Everything as a reboot leaves it: the same numbers can come back, but the boot id cannot.
        os.kill(started['supervisor']['pid'], signal.SIGKILL)
        wait_until(lambda: not self.status(plan)['supervisor']['alive'])
        identity = json.loads((tree / 'identity.json').read_text())
        survivor = identity['processes']['game']
        identity['supervisor']['boot_id'] = 'a-previous-boot'
        for item in identity['processes'].values():
            item['boot_id'] = 'a-previous-boot'
        (tree / 'identity.json').write_text(json.dumps(identity))
        summary = self.status(plan)
        self.assertFalse(summary['processes']['game']['alive'])
        self.assertTrue(self.stop(plan)['stopped'])
        self.assertEqual(guest_runner.process_start_id(survivor['pid']), survivor['start_id'], 'it was not ours to signal')
        os.killpg(survivor['pid'], signal.SIGKILL)

    def test_linux_process_identity_reads_the_kernel_start_field(self):
        with tempfile.TemporaryDirectory() as proc:
            directory = pathlib.Path(proc) / '4242'
            directory.mkdir()
            fields = ['S'] + ['0'] * 18 + ['987654'] + ['0'] * 30
            (directory / 'stat').write_text('4242 (omega server) ' + ' '.join(fields))
            self.assertEqual(guest_runner.process_start_id(4242, proc), 'ticks:987654')
            fields[0] = 'Z'
            (directory / 'stat').write_text('4242 (omega server) ' + ' '.join(fields))
            self.assertIsNone(guest_runner.process_start_id(4242, proc), 'a zombie has exited')
            self.assertIsNone(guest_runner.process_start_id(1, proc), 'no such pid')

    def test_linux_socket_rows_are_per_socket_and_owned_by_the_exact_process(self):
        self.assertEqual(guest_runner.parse_proc_net_udp(PROC_NET_UDP, 8081), [dict(local='00000000:1F91', inode='91234', drops=7, rx_queue=512)])
        with tempfile.TemporaryDirectory() as proc:
            root = pathlib.Path(proc)
            (root / 'net').mkdir()
            (root / 'net' / 'udp').write_text(PROC_NET_UDP)
            (root / 'net' / 'udp6').write_text('  sl\n')
            fd = root / '4242' / 'fd'
            fd.mkdir(parents=True)
            os.symlink('socket:[91234]', str(fd / '7'))
            self.assertEqual(guest_runner.observe_socket(4242, 8081, str(root))['inode'], '91234')
            self.assertIsNone(guest_runner.observe_socket(4242, 8082, str(root)), 'that socket belongs to someone else')


class Counters(unittest.TestCase):
    PLAN = dict(watch_socket_port=8081, processes=[dict(name='game')])

    def summary(self, first, last, pid=10, start='ticks:1'):
        row = dict(pid=pid, start_id=start, inode='91', drops=0)
        return dict(socket=dict(first=dict(row, **first), last=dict(row, **last)), processes=dict(game=dict(pid=pid, start_id=start)))

    def test_clean_counters_pass(self):
        self.assertEqual(run_checks.socket_problems(self.PLAN, self.summary(dict(drops=2), dict(drops=5)), [], True), [])

    def test_a_counter_that_moved_backward_is_refused(self):
        self.assertIn('the game socket counter moved backward', run_checks.socket_problems(self.PLAN, self.summary(dict(drops=9), dict(drops=2)), [], True))

    def test_counters_from_an_earlier_socket_are_refused(self):
        ledger = [dict(run_id='old', sealed=True, socket_inodes=['91'])]
        self.assertIn('the game socket has the identity of an earlier run', run_checks.socket_problems(self.PLAN, self.summary({}, {}), ledger, True))

    def test_a_row_from_another_process_is_refused(self):
        problems = run_checks.socket_problems(self.PLAN, self.summary({}, dict(pid=11)), [], True)
        self.assertIn('a socket counter row belongs to a different process', problems)

    def test_a_row_from_another_boot_is_refused(self):
        summary = self.summary({}, dict(boot_id='a-previous-boot'))
        self.assertIn('a socket counter row belongs to a different process', run_checks.socket_problems(self.PLAN, summary, [], True))

    def test_a_socket_replaced_during_the_run_cannot_be_compared(self):
        self.assertIn('the game socket changed during the run: counters cannot be compared', run_checks.socket_problems(self.PLAN, self.summary({}, dict(inode='92')), [], True))

    def test_a_missing_counter_fails_where_counters_are_required(self):
        self.assertIn('the game socket has no drop counter', run_checks.socket_problems(self.PLAN, self.summary(dict(drops=None), dict(drops=None)), [], True))
        self.assertEqual(run_checks.socket_problems(self.PLAN, self.summary(dict(drops=None), dict(drops=None)), [], False), [])

    def test_a_socket_never_seen_is_a_failure(self):
        self.assertEqual(run_checks.socket_problems(self.PLAN, dict(socket=None), [], False), ['the game socket was never observed'])


class SimultaneousExits(unittest.TestCase):
    """A descheduled supervisor can see both exits in one poll. No real signals, because the point is that single poll."""

    class Child:
        """``code`` per poll, the last repeating: a sampler that is alive at first ends once the supervisor signals it."""

        def __init__(self, pid, *codes):
            self.pid, self.codes = pid, list(codes)

        def poll(self):
            return self.codes.pop(0) if len(self.codes) > 1 else self.codes[0]

    def supervise(self, primary_code, *sampler_codes):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = pathlib.Path(directory.name)
        host, tree = guest_runner.Host(path / 'host'), path / 'run'
        tree.mkdir()
        minted = secrets.token_hex(16)
        (host.control / 'grants').mkdir()
        guest_runner.atomic_json(host.grant_path(minted), dict(grant_id=minted, session_id=SESSION, token=1, boot_id=guest_runner.boot_id(), clock_ns=guest_runner.grant_clock_ns()))
        plan = dict(session_id=SESSION, fencing_token=1, launch_not_after_wall=time.time() + 60, stop_by_wall=time.time() + 600, bound_s=60, stop_grace_s=0.01,
                    processes=[dict(name='bot', primary=True, argv=['standin'])], sampler=dict(argv=['sampler']), grant=dict(id=minted, ttl_s=60.0))
        guest_runner.atomic_json(host.fence_path, dict(session_id=SESSION, token=1))
        (tree / 'plan.json').write_text(json.dumps(plan))
        handler = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, handler)
        with mock.patch.object(guest_runner, '_spawn', side_effect=[self.Child(999999, primary_code), self.Child(999998, *sampler_codes)]):
            guest_runner.cmd_supervise(types.SimpleNamespace(run_dir=str(tree)), host)
        return guest_runner.read_json(tree / 'result.json')

    def test_a_sampler_failure_in_the_same_poll_as_the_primary_exit_is_not_hidden(self):
        result = self.supervise(0, 77)
        self.assertEqual(result['stop_reason'], 'primary_exited')
        self.assertEqual(result['processes']['sampler']['returncode'], 77)
        self.assertTrue(result['sampler_exited_early'])
        problems = run_checks._sampler_problems(dict(role='bot', sampler_interval_s=1), dict(result=result, sampler=dict(rows=100)))
        self.assertEqual(problems, ['bot sampler died during the run'], 'visible even with plenty of retained samples')

    def test_a_sampler_stopped_by_the_supervisor_is_not_a_failure(self):
        result = self.supervise(0, None, -15)
        self.assertEqual(result['processes']['sampler']['signal'], 15)
        self.assertFalse(result['sampler_exited_early'])


class Sealing(GuestFixture):
    def test_seal_inventories_every_byte_and_makes_the_tree_read_only(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        wait_until(lambda: self.status(plan)['socket'])
        self.stop(plan)
        sealed = self.seal(plan)
        tree = self.tree(plan)
        listed = {item['path']: item['sha256'] for item in sealed['seal']['files']}
        for name, digest in listed.items():
            self.assertEqual(run_executor.sha256_path(tree / name), digest)
        self.assertEqual({'plan.json', 'identity.json', 'result.json', 'final.json', 'sockets.ndjson', 'game-summary.json', 'game.stdout.log', 'game.stderr.log'} - set(listed), set())
        self.assertEqual(run_executor.sha256_path(tree / guest_runner.SEAL), sealed['seal_sha256'])
        with self.assertRaises(PermissionError):
            (tree / 'result.json').write_text('{}')
        with self.assertRaises(PermissionError):
            (tree / 'new-file').write_text('x')

    def test_seal_refuses_while_anything_runs(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.assertEqual(self.seal(plan)['code'], 'still_running')

    def test_sealing_twice_returns_the_same_seal(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        self.assertEqual(self.seal(plan)['seal_sha256'], self.seal(plan)['seal_sha256'])

    def test_an_interrupted_run_is_sealed_and_says_so(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.fence(token=2)
        self.stop(plan, token=2, reason='controller_replaced')
        sealed = self.seal(plan, 2, '--interrupted', 'controller_replaced')
        self.assertEqual(sealed['seal']['interrupted'], 'controller_replaced')
        self.assertTrue(sealed['result']['stop_reason'].startswith('stop_requested:controller_replaced'))
        self.assertIsNone(self.do('game', 'inspect')['active'], 'the host is free again, with the evidence kept')

    def test_a_crash_after_the_seal_still_ends_read_only_and_inactive(self):
        self.fence()
        plan = self.plan()
        self.start(plan)
        self.stop(plan)
        sealed = self.seal(plan)
        tree = self.tree(plan)
        os.chmod(str(tree), 0o750)
        os.chmod(str(tree / 'result.json'), 0o640)
        (self.guests.runner_root('game') / 'control' / 'active.json').write_text(json.dumps(dict(run_id=plan['run_id'], role='game')))
        again = self.seal(plan)
        self.assertEqual(again['seal_sha256'], sealed['seal_sha256'])
        self.assertEqual(os.stat(str(tree / 'result.json')).st_mode & 0o777, 0o440)
        self.assertIsNone(self.do('game', 'inspect')['active'])


class Contract(GuestFixture):
    """The fake remote must promise only what the real runner delivers."""

    def test_the_fake_documents_have_the_keys_of_the_real_ones(self):
        self.fence()
        plan = self.plan()
        self.assertEqual(set(self.do('game', 'preflight', '--plan-json', json.dumps(plan))), set(fake_run_guest.CONTRACT_KEYS['preflight']))
        self.start(plan)
        wait_until(lambda: self.status(plan)['socket'])
        self.assertEqual(set(self.status(plan)), set(fake_run_guest.CONTRACT_KEYS['status']))
        self.assertEqual(set(self.do('game', 'inspect')), set(fake_run_guest.CONTRACT_KEYS['inspect']))


class FakeKernel:
    """Plain directories standing where cgroupfs would be, keeping only what the supervisor relies on, and refusing what the real one refuses (cgroup-v2.rst):

    a child's interface files appear when its parent enables the controller; a cgroup with processes of its own cannot; ``mkdir`` is create-only; writing a pid to ``cgroup.procs`` moves that process. Each write is to a file, so that it holds from a forked child. It counts OOM kills
    only when a test says so, and no kernel counted anything here. ``forbid`` makes one step refuse, for a unit that was given no delegation.
    """
    EVENTS = 'low 0\nhigh 0\nmax 0\noom %d\noom_kill %d\noom_group_kill 0\n'

    def __init__(self, root, cgroup):
        self.root, self.cgroup = pathlib.Path(root), cgroup
        self.unit = self.root / cgroup.lstrip('/')
        self.unit.mkdir(parents=True)
        (self.unit / 'cgroup.subtree_control').write_text('')
        (self.unit / 'cgroup.procs').write_text('%d\n' % os.getpid())
        (self.unit / 'memory.events').write_text(self.EVENTS % (0, 0))
        self.forbid = set()

    def path(self, cgroup):
        return self.root / cgroup.lstrip('/')

    def _refuse(self, step):
        if step in self.forbid:
            raise PermissionError(errno.EACCES, 'no delegation for ' + step)

    def mkdir(self, cgroup):
        self._refuse('mkdir')
        directory = self.path(cgroup)
        directory.mkdir()
        (directory / 'cgroup.procs').write_text('')
        if '+memory' in (directory.parent / 'cgroup.subtree_control').read_text():
            (directory / 'memory.events.local').write_text(self.EVENTS % (0, 0))

    def write(self, cgroup, name, text):
        directory = self.path(cgroup)
        if name == 'cgroup.subtree_control':
            self._refuse('subtree_control')
            if (directory / 'cgroup.procs').read_text().strip():
                raise OSError(errno.EBUSY, 'no internal processes')
            (directory / name).write_text(text)
            for child in directory.iterdir():
                if child.is_dir():
                    (child / 'memory.events.local').write_text(self.EVENTS % (0, 0))
            return
        self._refuse('enter:' + directory.name)
        for other in self.unit.rglob('cgroup.procs'):
            kept = [line for line in other.read_text().splitlines() if line != text]
            other.write_text(''.join(line + '\n' for line in kept))
        with (directory / 'cgroup.procs').open('a') as handle:
            handle.write(text + '\n')

    def cgroup_of(self, pid, proc_root='/proc'):
        for procs in sorted(self.unit.rglob('cgroup.procs')):
            if str(pid) in procs.read_text().split():
                return '/' + str(procs.parent.relative_to(self.root))
        return None if pid == os.getpid() else self.cgroup_of(os.getpid())     # a child starts where its parent is, and stays there unless it moved

    def count(self, leaf, kills=1):
        """What ``__oom_kill_process`` does before it signals anyone: a count local to the victim's cgroup and in each one above it."""
        (self.unit / leaf / 'memory.events.local').write_text(self.EVENTS % (kills, kills))
        (self.unit / 'memory.events').write_text(self.EVENTS % (kills, kills))

    def count_shell(self, leaf):
        """The same, as a command the real game runs in its last moment, so the counter moves before the signal does."""
        return "printf '%s' > '%s'; printf '%s' > '%s'" % ('oom 1\\noom_kill 1\\noom_group_kill 0\\n', self.unit / leaf / 'memory.events.local', 'oom 1\\noom_kill 1\\noom_group_kill 0\\n', self.unit / 'memory.events')


class OomEvidence(unittest.TestCase):
    """The real supervisor and real child processes, over a directory standing where the kernel's cgroup files would be. No kernel counted anything here, so what is proven is the seam: what the producer does with
    those files, and what the consumer makes of what it wrote. Whether a real kill looks like this on a real Droplet is an operational check that no test here can make."""
    UNIT = run_plan.unit_name('fixture-session', 'fixture-run', 'game')     # the name a real plan carries: systemd-run --unit takes it whole
    CGROUP = '/system.slice/' + UNIT
    LEAF, SUPERVISION = guest_runner.WORKLOAD_LEAF, guest_runner.SUPERVISION_LEAF

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = pathlib.Path(temporary.name)
        self.kernel = FakeKernel(self.root / 'sys', self.CGROUP)
        previous = signal.getsignal(signal.SIGTERM)
        self.addCleanup(signal.signal, signal.SIGTERM, previous)

    def supervise(self, game_script, sampler_argv=None, unit_mode=guest_runner.SYSTEMD, stop_grace_s=2.0, at_the_read=None):
        """Runs the real ``cmd_supervise``. ``game_script`` runs in a real child, and can raise the counter the way the kernel does, before the signal. ``at_the_read(document)`` runs around the supervisor's read after the reap."""
        run_dir = self.root / 'run'
        run_dir.mkdir()
        plan = dict(run_id='fixture-run', role='game', unit=self.UNIT, unit_mode=unit_mode, processes=[dict(name='game', argv=['/bin/sh', '-c', game_script], primary=True)], sampler=dict(name='sampler', argv=sampler_argv or ['/bin/sleep', '30']),
                    stop_grace_s=stop_grace_s, stop_by_wall=time.time() + 60)
        (run_dir / 'plan.json').write_text(json.dumps(plan))
        real_reading, real_exited = guest_runner.cgroup_reading, guest_runner.OomWatch.primary_exited

        def reading(cgroup):
            # cgroup.procs on a real host lists the live members. This stands in for that, from the real children.
            document = real_reading(cgroup)
            if document is not None:
                document['procs'] = [pid for pid in document['procs'] if _alive(pid)]
            return document

        def exited(watch, primary, facts, alive):
            if at_the_read is None:
                return real_exited(watch, primary, facts, alive)
            return at_the_read(lambda: real_exited(watch, primary, facts, alive), watch.document)
        args = argparse.Namespace(run_dir=str(run_dir))
        with mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')), mock.patch.object(guest_runner, 'cgroup_reading', reading), mock.patch.object(guest_runner, 'cgroup_of', self.kernel.cgroup_of), \
                mock.patch.object(guest_runner, '_cgroup_mkdir', self.kernel.mkdir), mock.patch.object(guest_runner, '_cgroup_write', self.kernel.write), mock.patch.object(guest_runner.OomWatch, 'primary_exited', exited), \
                mock.patch.object(guest_runner, '_launch_gate', lambda host, run_dir, plan: 30.0), mock.patch.object(guest_runner, '_spawned_too_late', lambda host, plan: None), mock.patch.dict(os.environ, {'INVOCATION_ID': 'fixture-invocation'}):
            guest_runner.cmd_supervise(args, None)
        return run_dir

    def score(self, run_dir):
        root = tempfile.mkdtemp(prefix='omega-oom-')
        self.addCleanup(shutil.rmtree, root, True)
        scenario = sf.Scenario(root)
        sf.game_died(scenario.tree, 30)
        sf.bots_time_out_after_game_died(scenario.tree, [1, 2], 35)
        shutil.copy(str(run_dir / guest_runner.OOM_EVIDENCE), str(scenario.tree.path('game/' + guest_runner.OOM_EVIDENCE)))
        shutil.copy(str(run_dir / 'plan.json'), str(scenario.tree.path('plan-game.json')))
        identity = json.loads((run_dir / 'identity.json').read_text())
        result = json.loads((run_dir / 'result.json').read_text())
        record = sf.execution(game_exit=(None, 9))
        record['roles']['game'].update(identity=dict(supervisor=identity['supervisor'], processes=identity['processes'], invocation_id=identity['invocation_id']), result=result)
        return scenario.score(execution_record=record)

    def evidence(self, run_dir):
        return json.loads((run_dir / guest_runner.OOM_EVIDENCE).read_text())

    def killed_by_the_kernel(self):
        return '%s; kill -9 $$' % self.kernel.count_shell(self.LEAF)

    def assertUnexplained(self, run_dir, status='not_attributable'):
        document = self.score(run_dir)
        game_exit = document['attribution']['game_exit']
        self.assertEqual((game_exit['kind'], game_exit['demonstrated']), ('killed_with_no_cause_on_record', False), game_exit)
        self.assertEqual(game_exit['process_oom']['status'], status, game_exit['process_oom'])
        self.assertEqual(document['classification'], 'inconclusive_evidence')
        self.assertEqual(document['outcome'], 'INCONCLUSIVE', 'nothing advances on it')
        return game_exit['process_oom']

    def test_the_game_is_alone_in_a_leaf_it_never_left_with_the_others_in_another(self):
        run_dir = self.supervise('sleep 0.4; kill -9 $$')
        evidence, identity = self.evidence(run_dir), json.loads((run_dir / 'identity.json').read_text())
        self.assertEqual(evidence['schema'], guest_runner.OOM_SCHEMA)
        self.assertEqual((evidence['cgroup'], evidence['leaf'], evidence['supervision']), (self.CGROUP, self.CGROUP + '/' + self.LEAF, self.CGROUP + '/' + self.SUPERVISION))
        self.assertEqual(evidence['member_cgroups'], dict(game=evidence['leaf'], sampler=evidence['supervision'], supervisor=evidence['supervision']))
        self.assertEqual(evidence['baseline']['procs'], [], 'before any child existed')
        self.assertEqual(evidence['bound']['procs'], [identity['processes']['game']['pid']])
        self.assertEqual(evidence['primary_exit']['procs'], [], 'a reaped game is gone')
        self.assertEqual(self.kernel.path(self.CGROUP).joinpath('cgroup.procs').read_text(), '', 'the unit itself is an inner node, with no process of its own')

    def test_a_kill_the_kernel_counted_in_the_games_leaf_reaches_the_consumer_as_the_games(self):
        """The positive seam. Mocked: a shell standing for the kernel raises the count just before the real child dies by SIGKILL."""
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel())
        evidence = self.evidence(run_dir)
        self.assertTrue(evidence['available'], evidence)
        self.assertEqual((evidence['baseline']['oom_kill'], evidence['primary_exit']['oom_kill']), (0, 1))
        self.assertEqual(evidence['primary_exit']['signal'], 9)
        document = self.score(run_dir)
        game_exit = document['attribution']['game_exit']
        self.assertEqual((game_exit['kind'], game_exit['demonstrated']), ('out_of_memory', True), game_exit)
        self.assertEqual((game_exit['process_oom']['status'], game_exit['process_oom']['oom_kill_in_leaf']), ('victim_matched', 1))
        self.assertEqual(document['classification'], 'capacity_failure')

    def test_a_sigkill_the_kernel_did_not_count_stays_unexplained(self):
        run_dir = self.supervise('sleep 0.4; kill -9 $$')
        self.assertEqual(self.evidence(run_dir)['primary_exit']['oom_kill'], 0)
        self.assertUnexplained(run_dir)

    def test_the_sampler_chosen_and_not_yet_dead_at_the_read_is_no_kill_of_the_games(self):
        """The ordering that broke the unit-wide count: the game dies of something else, and in the same interval the kernel has counted the sampler and not yet delivered its SIGKILL. Membership shows it alive."""
        def at_the_read(read, document):
            self.kernel.count(self.SUPERVISION)
            read()
            os.kill(document['processes']['sampler']['pid'], signal.SIGKILL)
        run_dir = self.supervise('sleep 0.4; kill -9 $$', at_the_read=at_the_read)
        evidence, result = self.evidence(run_dir), json.loads((run_dir / 'result.json').read_text())
        self.assertEqual(evidence['primary_exit']['alive'], ['sampler'])
        self.assertEqual((evidence['primary_exit']['oom_kill'], evidence['primary_exit']['unit_oom_kill']), (0, 1), 'the unit counted one kill, and the game\'s leaf none')
        self.assertEqual((result['processes']['game']['signal'], result['processes']['sampler']['signal'], result['sampler_exited_early']), (9, 9, False))
        facts = self.assertUnexplained(run_dir)
        self.assertEqual((facts['oom_kill_in_leaf'], facts['unit_oom_kill_at_reap']), (0, 1))
        self.assertIn('0 OOM kills', str(facts['problems']))

    def test_a_sampler_counted_long_before_the_games_delayed_exit_is_no_kill_of_the_games(self):
        def at_the_read(read, document):
            self.kernel.count(self.SUPERVISION)
            time.sleep(0.2)
            read()
        self.assertUnexplained(self.supervise('sleep 0.4; kill -9 $$', at_the_read=at_the_read))

    def test_a_final_sigkill_of_the_sampler_in_teardown_changes_nothing(self):
        """The supervisor escalates on a sampler that will not stop, and the kernel counted that same sampler. Neither says a thing about the game."""
        def at_the_read(read, document):
            self.kernel.count(self.SUPERVISION)
            read()
        run_dir = self.supervise('sleep 0.2; kill -9 $$', sampler_argv=['/bin/sh', '-c', 'trap "" TERM; while :; do sleep 0.05; done'], stop_grace_s=0.3, at_the_read=at_the_read)
        self.assertIn('sampler', json.loads((run_dir / 'result.json').read_text())['killed'], 'it had to be killed')
        self.assertUnexplained(run_dir)

    def test_a_sampler_that_died_early_by_itself_costs_a_kill_the_kernel_named_nothing(self):
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel(), sampler_argv=['/bin/sh', '-c', 'kill -9 $$'])
        self.assertTrue(json.loads((run_dir / 'result.json').read_text())['sampler_exited_early'])
        self.assertEqual(self.score(run_dir)['attribution']['game_exit']['kind'], 'out_of_memory')

    def test_the_kernel_counting_the_game_and_the_sampler_is_still_the_games(self):
        def at_the_read(read, document):
            (self.kernel.unit / 'memory.events').write_text(FakeKernel.EVENTS % (2, 2))
            read()
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel(), at_the_read=at_the_read)
        game_exit = self.score(run_dir)['attribution']['game_exit']
        self.assertEqual((game_exit['kind'], game_exit['process_oom']['oom_kill_in_leaf'], game_exit['process_oom']['unit_oom_kill_at_reap']), ('out_of_memory', 1, 2))

    def test_a_game_that_could_not_enter_its_leaf_stays_unexplained_and_still_runs(self):
        self.kernel.forbid.add('enter:' + self.LEAF)
        run_dir = self.supervise('sleep 0.2; kill -9 $$')
        evidence = self.evidence(run_dir)
        self.assertTrue(evidence['available'], 'the leaf exists')
        self.assertEqual(evidence['member_cgroups']['game'], evidence['supervision'], 'on record as where it stayed')
        self.assertEqual(json.loads((run_dir / 'result.json').read_text())['stop_reason'], 'primary_exited')
        self.assertUnexplained(run_dir)

    def test_a_unit_with_no_delegation_says_unavailable_and_the_run_goes_on(self):
        for step, why in (('mkdir', 'mkdir refused'), ('subtree_control', 'controller refused'), ('enter:' + self.SUPERVISION, 'move refused')):
            with self.subTest(why):
                self.setUp()
                self.kernel.forbid.add(step)
                run_dir = self.supervise('sleep 0.2; kill -9 $$')
                evidence = self.evidence(run_dir)
                self.assertFalse(evidence['available'])
                self.assertIn('no leaf of the workload', evidence['unavailable'])
                self.assertEqual(json.loads((run_dir / 'result.json').read_text())['stop_reason'], 'primary_exited')
                self.assertEqual(json.loads((run_dir / 'result.json').read_text())['processes']['game']['signal'], 9)
                self.assertUnexplained(run_dir, 'unavailable')

    def test_a_leaf_that_already_exists_is_not_taken_for_a_fresh_one(self):
        (self.kernel.unit / self.LEAF).mkdir()
        self.assertIn('no leaf of the workload', self.evidence(self.supervise('kill -9 $$'))['unavailable'])

    def test_a_game_that_a_cgroup_move_took_elsewhere_stays_unexplained(self):
        def at_the_read(read, document):
            document['member_cgroups']['game'] = '/system.slice/ssh.service'
            read()
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel(), at_the_read=at_the_read)
        self.assertUnexplained(run_dir)

    def test_a_stranger_in_the_leaf_at_the_reap_stays_unexplained(self):
        def at_the_read(read, document):
            with (self.kernel.unit / self.LEAF / 'cgroup.procs').open('a') as handle:
                handle.write('%d\n' % document['processes']['sampler']['pid'])
            read()
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel(), at_the_read=at_the_read)
        self.assertIn('may hold only the game', str(self.assertUnexplained(run_dir)['problems']))

    def test_a_reused_pid_or_a_wrong_identity_stays_unexplained(self):
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel())
        evidence = self.evidence(run_dir)
        evidence['processes']['game']['start_id'] = 'bsd:1.0'
        (run_dir / guest_runner.OOM_EVIDENCE).write_text(json.dumps(evidence))
        self.assertIn('not the supervised process', str(self.assertUnexplained(run_dir)['problems']))

    def test_evidence_of_the_unit_wide_schema_could_never_name_a_victim(self):
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel())
        evidence = self.evidence(run_dir)
        evidence['schema'] = 'omega.do-session.process-oom/1'
        (run_dir / guest_runner.OOM_EVIDENCE).write_text(json.dumps(evidence))
        self.assertUnexplained(run_dir, 'refused')

    def test_a_missing_evidence_file_stays_unexplained(self):
        run_dir = self.supervise('sleep 0.4; %s' % self.killed_by_the_kernel())
        (run_dir / guest_runner.OOM_EVIDENCE).write_text('{"schema": ')
        self.assertUnexplained(run_dir, 'missing')

    def test_a_run_with_no_unit_of_its_own_writes_that_it_has_nothing_to_say(self):
        run_dir = self.supervise('kill -9 $$', unit_mode=guest_runner.PROCESS_GROUP)
        evidence = self.evidence(run_dir)
        self.assertFalse(evidence['available'])
        self.assertIn('no unit of its own', evidence['unavailable'])
        self.assertEqual(json.loads((run_dir / 'result.json').read_text())['stop_reason'], 'primary_exited')
        self.assertEqual(self.score(run_dir)['attribution']['game_exit']['process_oom']['status'], 'unavailable')

    def test_a_real_plans_unit_is_what_the_watch_expects_of_its_cgroup(self):
        """systemd-run --unit=NAME.service runs it in a cgroup called NAME.service, with no second suffix."""
        self.assertTrue(self.UNIT.endswith('.service'))
        with mock.patch.object(guest_runner, 'cgroup_of', self.kernel.cgroup_of), mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')), mock.patch.object(guest_runner, '_cgroup_mkdir', self.kernel.mkdir), mock.patch.object(guest_runner, '_cgroup_write', self.kernel.write):
            watch = guest_runner.OomWatch(dict(unit=self.UNIT, unit_mode=guest_runner.SYSTEMD, run_id='fixture-run', role='game'))
        self.assertTrue(watch.document['available'], watch.document)
        self.assertEqual(watch.document['cgroup'], self.CGROUP)

    def test_a_cgroup_that_is_not_the_units_or_cannot_be_read_says_so(self):
        plan = dict(unit=self.UNIT, unit_mode=guest_runner.SYSTEMD, run_id='r', role='game')
        with mock.patch.object(guest_runner, 'cgroup_of', lambda pid, proc_root='/proc': None):
            self.assertIn('no cgroup v2', guest_runner.OomWatch(plan).document['unavailable'])
        with mock.patch.object(guest_runner, 'cgroup_of', lambda pid, proc_root='/proc': '/user.slice/session-1.scope'):
            self.assertIn('not in the run unit', guest_runner.OomWatch(plan).document['unavailable'])
        with mock.patch.object(guest_runner, 'cgroup_of', lambda pid, proc_root='/proc': self.CGROUP), mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'nowhere')):
            self.assertIn('no leaf of the workload', guest_runner.OomWatch(plan).document['unavailable'])

        def no_counter(cgroup):
            self.kernel.path(cgroup).mkdir()
            (self.kernel.path(cgroup) / 'cgroup.procs').write_text('')
        with mock.patch.object(guest_runner, 'cgroup_of', self.kernel.cgroup_of), mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')), mock.patch.object(guest_runner, '_cgroup_mkdir', no_counter), mock.patch.object(guest_runner, '_cgroup_write', self.kernel.write):
            self.assertIn('cannot be read', guest_runner.OomWatch(plan).document['unavailable'], 'a memory controller that gave the leaf no counter')

    def test_collecting_it_never_stops_a_run_from_stopping(self):
        def broken(*_):
            raise RuntimeError('a surprising file')
        with mock.patch.object(guest_runner, 'cgroup_of', broken):
            watch = guest_runner.OomWatch(dict(unit=self.UNIT, unit_mode=guest_runner.SYSTEMD))
        self.assertIn('RuntimeError', watch.document['unavailable'])
        watch.bind(dict(pid=1), {}, None)
        watch.primary_exited('game', dict(returncode=None, signal=9), [])
        watch.finish(self.root / 'nowhere' / 'at' / 'all.json')

    def test_a_missing_counter_is_never_zero(self):
        leaf = self.kernel.unit / self.LEAF
        leaf.mkdir()
        (leaf / 'cgroup.procs').write_text('')
        (leaf / 'memory.events.local').write_text('low 0\nhigh 0\n')
        with mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')):
            self.assertIsNone(guest_runner.cgroup_reading(self.CGROUP + '/' + self.LEAF))
        (leaf / 'memory.events.local').write_text('oom_kill not-a-number\n')
        with mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')):
            self.assertIsNone(guest_runner.cgroup_reading(self.CGROUP + '/' + self.LEAF))

    def test_the_count_it_reads_is_the_one_local_to_the_leaf_and_not_the_hierarchical_one(self):
        leaf = self.kernel.unit / self.LEAF
        leaf.mkdir()
        (leaf / 'cgroup.procs').write_text('')
        (leaf / 'memory.events').write_text('oom_kill 9\n')
        (leaf / 'memory.events.local').write_text('oom_kill 1\n')
        with mock.patch.object(guest_runner, 'CGROUP_ROOT', str(self.root / 'sys')):
            self.assertEqual(guest_runner.cgroup_reading(self.CGROUP + '/' + self.LEAF)['oom_kill'], 1)

    def test_the_v2_line_of_proc_pid_cgroup(self):
        proc = self.root / 'proc' / '42'
        proc.mkdir(parents=True)
        for text, expected in (('0::/system.slice/a.service\n', '/system.slice/a.service'), ('12:memory:/x\n0::/b\n', '/b'), ('12:memory:/x\n', None), ('0::/gone (deleted)\n', None), ('0::relative\n', None)):
            (proc / 'cgroup').write_text(text)
            self.assertEqual(guest_runner.cgroup_of(42, str(self.root / 'proc')), expected, text)
        self.assertIsNone(guest_runner.cgroup_of(43, str(self.root / 'proc')))

    @unittest.skipUnless(os.path.exists('/sys/fs/cgroup/cgroup.controllers') and guest_runner.cgroup_of(os.getpid()) not in (None, '/'), 'needs a Linux host on cgroup v2. Nothing else can run this')
    def test_the_real_files_read_on_a_real_cgroup(self):
        reading = guest_runner.cgroup_reading(guest_runner.cgroup_of(os.getpid()))
        self.assertIsNotNone(reading)
        self.assertIn(os.getpid(), reading['procs'])
        self.assertIsInstance(reading['oom_kill'], int)


class SystemdPath(GuestFixture):
    """Through shims for ``sudo``, ``systemd-run`` and ``systemctl``, which run the real supervisor. Real units are a Gate A check."""

    def setUp(self):
        super().setUp()
        bin_dir = self.hosts.bin_dir
        self.record = self.root / 'systemd-argv.txt'
        (bin_dir / 'sudo').write_text('#!/bin/sh\nshift\nexec "$@"\n')
        (bin_dir / 'systemd-run').write_text('#!/bin/sh\necho "$@" >> "%s"\nwhile [ "${1#--}" != "$1" ]; do shift; done\nINVOCATION_ID=fixture-invocation-$$ nohup "$@" >/dev/null 2>&1 &\n' % self.record)
        (bin_dir / 'systemctl').write_text('#!/bin/sh\nif [ "$1" = "list-units" ]; then exit 0; fi\necho ActiveState=active\necho InvocationID=shim\n')
        for name in ('sudo', 'systemd-run', 'systemctl'):
            (bin_dir / name).chmod(0o755)

    def test_the_unit_carries_its_own_bound_and_the_run_records_the_invocation(self):
        self.fence()
        plan = self.plan(unit_mode=guest_runner.SYSTEMD, bound_s=30.0, stop_grace_s=1.0)
        started = self.start(plan)
        self.assertTrue(started['ok'], started)
        self.assertTrue(started['invocation_id'].startswith('fixture-invocation-'))
        argv = self.record.read_text()
        self.assertIn('--unit=' + plan['unit'], argv)
        self.assertIn('--property=RuntimeMaxSec=36', argv)
        self.assertIn('--property=KillMode=control-group', argv)
        self.assertIn('--property=Restart=no', argv)
        self.assertEqual(self.status(plan)['unit']['InvocationID'], 'shim')
        ledger = [dict(run_id='old', invocation_id=started['invocation_id'])]
        self.assertIn('the unit invocation was already used by an earlier run', run_checks.launch_problems(plan, started, ledger))
        self.assertEqual(self.stop(plan)['stopped'], True)

    def test_the_unit_keeps_its_supervisor_alive_through_an_oom_kill(self):
        self.fence()
        plan = self.plan(unit_mode=guest_runner.SYSTEMD, bound_s=30.0, stop_grace_s=1.0)
        self.assertTrue(self.start(plan)['ok'])
        self.assertIn('--property=OOMPolicy=continue', self.record.read_text())
        self.stop(plan)

    def test_the_unit_delegates_only_the_memory_controller_to_the_uid_it_already_runs_as(self):
        self.fence()
        plan = self.plan(unit_mode=guest_runner.SYSTEMD, bound_s=30.0, stop_grace_s=1.0)
        self.assertTrue(self.start(plan)['ok'])
        argv = self.record.read_text()
        self.assertIn('--property=Delegate=memory', argv)
        self.assertIn('--uid=%d' % os.getuid(), argv)
        self.assertIn('--property=KillMode=control-group', argv, 'and the whole subtree still goes when the unit does')
        self.stop(plan)

    def test_a_failed_unit_start_is_refused(self):
        (self.hosts.bin_dir / 'systemd-run').write_text('#!/bin/sh\nexit 1\n')
        self.fence()
        document = self.start(self.plan(unit_mode=guest_runner.SYSTEMD))
        self.assertEqual(document['code'], 'unit_start_failed')

    def test_leftover_units_fail_the_host_rules(self):
        plan = self.plan(unit_mode=guest_runner.SYSTEMD)
        facts = dict(units=['omega-run-abc-game.service'], files=[], ports_free={}, leftovers=[], impairment=dict(available=True, qdisc_kinds=['mq'], filter_count=0))
        self.assertIn('units remain: omega-run-abc-game.service', run_checks.host_problems(plan, facts, None, None))


if __name__ == '__main__':
    unittest.main()
