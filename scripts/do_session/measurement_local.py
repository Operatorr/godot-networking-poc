#!/usr/bin/env python3
"""One real measured run on this machine: real omega-server and omega-load-test, the real runner and supervisor, two host roots on loopback.

Everything is a real process on real clocks, and each role keeps its own root, identities, recorders and monotonic origin. It proves
that the recorders, the barrier and the proof work together. It proves nothing about a Droplet: both endpoints share this host and
its wall clock, so the brackets are real but small, and there is no public route, netem, systemd or /proc on macOS. The macOS collector
has socket endpoints but no drop counters. Nothing here is a capacity observation.

    measurement_local.py --release DIR --target N --hold-s S --out DIR [--require-counters] [--fault SPEC]

``FaultSchedule`` holds what happens to a running pair from outside: pausing a process, killing one, or holding datagrams at the
relay. ``--fault`` needs a build with the ``fault-injection`` feature, which a frozen benchmark build never has.
"""
import argparse
import contextlib
import json
import os
import pathlib
import select
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time

import guest_runner
import manifest as manifest_mod
import measurement_window
import run_plan
import search

HERE = pathlib.Path(__file__).parent
REPO = HERE.parents[1]
SESSION = 'do-local-measure'
TOKEN = 1
START_TIMEOUT_S = 30.0


class LocalAdapter(run_plan.ReleaseAdapter):
    """The production adapter's processes, with a relay's address if one is in the way and paths under one role root per host."""

    def __init__(self, root, game_port, metrics_port, connect_port, bot_extra=()):
        self.root = pathlib.Path(root)
        self.game_port = game_port
        self.metrics_port = metrics_port
        self.connect_port = connect_port
        self.bot_extra = list(bot_extra)
        self.interface = None

    def game_address(self, addresses):
        return '127.0.0.1'

    def program_paths(self):
        return dict(game=str(self.root / 'game/release/omega-server'), bot=str(self.root / 'bot/release/omega-load-test'))

    def config_path(self):
        return str(self.root / 'game/release/server_config.json')

    def sampler_path(self, role):
        return str(self.root / role / 'release/sample_host.py')

    def sampler_process(self, role):
        process = super().sampler_process(role)
        return dict(process, argv=[sys.executable] + process['argv'][1:])

    def bot_process(self, manifest, trial, addresses):
        process = super().bot_process(manifest, trial, addresses)
        argv = process['argv']
        argv[argv.index('--server') + 1] = '127.0.0.1:%d' % self.connect_port
        return dict(process, argv=argv + self.bot_extra)


class Relay(threading.Thread):
    """A real datagram relay in front of the game socket, so a second endpoint can delay or swallow one bot's traffic with no help from either binary."""

    def __init__(self, target_port):
        super().__init__(daemon=True)
        self.target = ('127.0.0.1', target_port)
        self.front = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.front.bind(('127.0.0.1', 0))
        self.port = self.front.getsockname()[1]
        self.clients = {}
        self.order = []
        self.held = {}          # client index -> (until_monotonic or None for ever)
        self.stopped = threading.Event()

    def hold(self, index, seconds=None):
        self.held[index] = None if seconds is None else (time.monotonic() + seconds)

    def _blocked(self, source):
        index = self.order.index(source)
        if index not in self.held:
            return False
        until = self.held[index]
        return until is None or time.monotonic() < until

    def run(self):
        while not self.stopped.is_set():
            sockets = [self.front] + [upstream for upstream in self.clients.values()]
            readable, _, _ = select.select(sockets, [], [], 0.05)
            for item in readable:
                try:
                    data, source = item.recvfrom(65535)
                except OSError:
                    continue
                if item is self.front:
                    if source not in self.clients:
                        upstream = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                        upstream.bind(('127.0.0.1', 0))
                        self.clients[source] = upstream
                        self.order.append(source)
                    if not self._blocked(source):
                        with contextlib.suppress(OSError):
                            self.clients[source].sendto(data, self.target)
                else:
                    for client, upstream in self.clients.items():
                        if upstream is item:
                            if not self._blocked(client):
                                with contextlib.suppress(OSError):
                                    self.front.sendto(data, client)
                            break

    def stop(self):
        self.stopped.set()
        self.join(timeout=2)
        for item in [self.front] + list(self.clients.values()):
            item.close()


def free_udp_tcp_port():
    while True:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
        probe.close()
        if guest_runner.port_free('udp', port) and guest_runner.port_free('tcp', port):
            return port


class Runner:
    def __init__(self, root, role, runner_path):
        self.root = pathlib.Path(root) / role / 'runner'
        self.runner_path = runner_path

    def __call__(self, command, *arguments, check=True):
        result = subprocess.run([sys.executable, str(self.runner_path), '--root', str(self.root), command] + [str(a) for a in arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                timeout=120, check=False, env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'))
        document = json.loads(result.stdout.decode() or '{}')
        if check and document.get('ok') is not True:
            raise RuntimeError('%s refused: %s %s %s' % (command, document.get('code'), document.get('detail'), result.stderr.decode()[-400:]))
        return document


def bracket(runners, label):
    document = dict(schema='omega.do-session.clock-bracket/1', label=label, roles={})
    for role, runner in runners.items():
        attempts = document['roles'][role] = []
        for _ in range(3):
            before = time.time()
            reading = runner('clock')
            after = time.time()
            attempts.append(dict(before_ns=int(before * 1e9), guest_wall_ns=reading['wall_ns'], guest_monotonic_ns=reading['monotonic_ns'], after_ns=int(after * 1e9), boot_id=reading['boot_id']))
    return document


SESSION_RUN = 'local-run'


class FaultSchedule:
    """Real things done to a running pair from outside. Each ``step(run)`` runs on a thread once the bot process exists."""

    @staticmethod
    def pause_swarm_in_window(seconds, offset_s=0.5):
        def step(run):
            row = run.await_publication()
            if row is None:
                return
            time.sleep(1.0 + offset_s)     # the publication's lead, then into the hold
            run.pause('bot', seconds)
        return step

    @staticmethod
    def pause_swarm_in_barrier(seconds):
        def step(run):
            if run.await_barrier():
                run.pause('bot', seconds)
        return step

    @staticmethod
    def kill_swarm_in_window(offset_s=1.0):
        def step(run):
            if run.await_publication() is not None:
                time.sleep(1.0 + offset_s)
                run.kill('bot')
        return step

    @staticmethod
    def kill_game_in_window(offset_s=1.0):
        def step(run):
            if run.await_publication() is not None:
                time.sleep(1.0 + offset_s)
                run.kill('game')
        return step

    @staticmethod
    def hold_one_bot(index, seconds):
        def step(run):
            run.relay.hold(index, seconds)
        return step


class LocalRun:
    def __init__(self, release, out, target, hold_s, bot_release=None, bot_extra=(), use_relay=False, readiness_timeout_s=None, schedule=(), config_overrides=None):
        self.release = pathlib.Path(release)
        self.bot_release = pathlib.Path(bot_release or release)
        self.root = pathlib.Path(out)
        self.root.mkdir(parents=True, exist_ok=False)
        self.target, self.hold_s = target, hold_s
        self.schedule = list(schedule)
        self.bot_extra = list(bot_extra)
        self.use_relay = use_relay
        self.readiness_timeout_s = readiness_timeout_s
        self.config_overrides = config_overrides or {}
        self.relay = None
        self.identity = {}
        self.events = []

    # ---- what a schedule can use --------------------------------------------------------------

    def _swarm_dir(self):
        return self.root / 'bot/runner/runs' / SESSION_RUN / 'bot/swarm'

    def _coordinator_rows(self):
        rows = []
        with contextlib.suppress(OSError):
            for line in (self._swarm_dir() / 'coordinator.ndjson').read_text().splitlines():
                with contextlib.suppress(ValueError):
                    rows.append(json.loads(line))
        return rows

    def await_publication(self, limit_s=120):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            row = next((item for item in self._coordinator_rows() if item.get('k') == 'window_published'), None)
            if row is not None:
                return row
            time.sleep(0.02)
        return None

    def await_barrier(self, limit_s=120):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            if any(item.get('k') == 'barrier' for item in self._coordinator_rows()):
                return True
            time.sleep(0.01)
        return False

    def pid(self, role):
        return self.identity[role]['processes'][role]['pid']

    def pause(self, role, seconds):
        pid = self.pid(role)
        self.events.append(dict(what='SIGSTOP', role=role, seconds=seconds))
        os.kill(pid, signal.SIGSTOP)
        try:
            time.sleep(seconds)
        finally:
            os.kill(pid, signal.SIGCONT)

    def kill(self, role):
        self.events.append(dict(what='SIGKILL', role=role))
        os.kill(self.pid(role), signal.SIGKILL)

    # ---- one run -------------------------------------------------------------------------------

    def _install(self, adapter):
        for role, name, source in (('game', 'omega-server', self.release), ('bot', 'omega-load-test', self.bot_release)):
            directory = self.root / role / 'release'
            directory.mkdir(parents=True)
            shutil.copy2(str(source / name), str(directory / name))
            shutil.copy2(str(HERE.parent / 'quick_stress/sample_host.py'), str(directory / 'sample_host.py'))
        config = json.loads((REPO / 'deployment/server_config.loadtest.json').read_text())
        config.update(metrics_port=adapter.metrics_port, **self.config_overrides)
        pathlib.Path(adapter.config_path()).write_text(json.dumps(config))
        tools = self.root / 'tools'
        tools.mkdir()
        shutil.copy2(str(HERE / 'guest_runner.py'), str(tools / 'guest_runner.py'))
        return tools / 'guest_runner.py'

    def execute(self):
        game_port, metrics_port = free_udp_tcp_port(), free_udp_tcp_port()
        connect_port = game_port
        if self.use_relay:
            self.relay = Relay(game_port)
            self.relay.start()
            connect_port = self.relay.port
        adapter = LocalAdapter(self.root, game_port, metrics_port, connect_port, self.bot_extra)
        runner_path = self._install(adapter)
        runners = {role: Runner(self.root, role, runner_path) for role in ('game', 'bot')}
        hashes = dict(game=guest_runner.sha256_file(adapter.program_paths()['game']), bot=guest_runner.sha256_file(adapter.program_paths()['bot']))
        manifest = dict(session=dict(id=SESSION), workload=dict(manifest_mod.WORKLOAD_SCHEMA), source=dict(binary_sha256=hashes, server_config_sha256=guest_runner.sha256_file(adapter.config_path())))
        trial = search.Trial(run_id=SESSION_RUN, ordinal=1, phase='confirm' if self.hold_s == 300 else 'coarse', target=self.target, repetition=1, hold_s=self.hold_s, predecessors=())
        sampler = guest_runner.sha256_file(adapter.sampler_path('game'))
        for runner in runners.values():
            runner('fence', '--session', SESSION, '--token', TOKEN)
        brackets = dict(before=bracket(runners, 'before'))
        whole = run_plan.swarm_bound_s(trial)
        if self.readiness_timeout_s is not None:
            whole = self.readiness_timeout_s + search.POST_AUTH_WARMUP_S + self.hold_s + run_plan.SWARM_TAIL_S
        now = time.time()
        results = {}
        started = []
        schedule_threads = []
        try:
            for role, extra in (('game', 20), ('bot', 0)):
                grant = runners[role]('grant_prepare', '--session', SESSION, '--token', TOKEN)['grant_id']
                plan = run_plan.role_plan(adapter, manifest, 'local', trial, role, dict(game='127.0.0.1', bot='127.0.0.1'), sampler, TOKEN, guest_runner.PROCESS_GROUP, time.time() + 30.0,
                                          whole + 60 + extra, now + whole + 300 + extra, 5.0, minimum_bound_s=whole)
                if role == 'bot' and self.readiness_timeout_s is not None:
                    argv = plan['processes'][0]['argv']
                    argv[argv.index('--readiness-timeout-s') + 1] = str(self.readiness_timeout_s)
                plan = dict(plan, grant=dict(id=grant, ttl_s=60.0))
                (self.root / ('plan-%s.json' % role)).write_text(json.dumps(plan, indent=2, sort_keys=True))
                document = runners[role]('start', '--plan-json', json.dumps(plan, sort_keys=True))
                self.identity[role] = dict(processes=document['processes'], supervisor=document['supervisor'])
                started.append(role)
                if role == 'game':
                    self._await_socket(runners['game'])
            for step in self.schedule:
                thread = threading.Thread(target=step, args=(self,), daemon=True)
                thread.start()
                schedule_threads.append(thread)
            self._await_result(runners['bot'], whole + 120)
            for thread in schedule_threads:
                thread.join(timeout=5)
        finally:
            for role in reversed(started):
                results[role] = runners[role]('stop', '--run-id', SESSION_RUN, '--role', role, '--token', TOKEN, '--reason', 'workload_finished', '--wait-s', 20)
            if self.relay is not None:
                self.relay.stop()
        brackets['after'] = bracket(runners, 'after')
        for role in started:
            results[role] = runners[role]('seal', '--run-id', SESSION_RUN, '--role', role, '--token', TOKEN)
        evidence = self.root / 'evidence'
        for role in started:
            shutil.copytree(str(self.root / role / 'runner/runs' / SESSION_RUN / role), str(evidence / role))
        (evidence / 'clock-before.json').write_text(json.dumps(brackets['before']))
        (evidence / 'clock-after.json').write_text(json.dumps(brackets['after']))
        identities = {role: self.identity[role]['processes'] for role in started}
        (evidence / 'identities.json').write_text(json.dumps(identities))
        return dict(evidence=str(evidence), trial=trial.to_dict(), identities=identities, brackets=brackets, workload=manifest['workload'], results=results, events=self.events,
                    binaries=hashes)

    def _await_socket(self, runner):
        deadline = time.monotonic() + START_TIMEOUT_S
        while time.monotonic() < deadline:
            status = runner('status', '--run-id', SESSION_RUN, '--role', 'game')
            if status.get('socket'):
                return
            if status.get('result'):
                raise RuntimeError('the game ended during startup: %s' % status['result'])
            time.sleep(0.05)
        raise RuntimeError('the game never opened its socket')

    def _await_result(self, runner, limit_s):
        deadline = time.monotonic() + limit_s
        while time.monotonic() < deadline:
            status = runner('status', '--run-id', SESSION_RUN, '--role', 'bot')
            if status.get('result'):
                return status['result']
            time.sleep(0.2)
        raise RuntimeError('the swarm outlived its bound')


def prove(run, require_counters=False, allow_short_hold=True, **overrides):
    """The production prover over a finished local run."""
    arguments = dict(identities=run['identities'], brackets=run['brackets'], require_counters=require_counters, allow_short_hold=allow_short_hold)
    arguments.update(overrides)
    return measurement_window.prove(arguments.pop('root', run['evidence']), run['trial'], run['workload'], **arguments)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--release', required=True)
    parser.add_argument('--bot-release')
    parser.add_argument('--target', type=int, required=True)
    parser.add_argument('--hold-s', type=int, required=True)
    parser.add_argument('--out')
    parser.add_argument('--fault', action='append', default=[])
    parser.add_argument('--require-counters', action='store_true')
    args = parser.parse_args(argv)
    out = args.out or tempfile.mkdtemp(prefix='omega-measure-') + '/run'
    extra = [item for fault in args.fault for item in ('--fault', fault)]
    run = LocalRun(args.release, out, args.target, args.hold_s, bot_release=args.bot_release, bot_extra=extra).execute()
    proof = prove(run, require_counters=args.require_counters, allow_short_hold=args.hold_s not in (60, 300))
    print(json.dumps(dict(out=out, status=proof['status'], reasons=proof['reasons'], contract_hold=proof['facts'].get('contract_hold'), input=proof['facts'].get('input'),
                          population={k: v for k, v in (proof['facts'].get('population') or {}).items() if k != 'interval_game_mono_ns'}, clock=proof['facts'].get('clock')), indent=2, sort_keys=True))
    return 0 if proof['status'] == measurement_window.COMPLETE else 1


if __name__ == '__main__':
    sys.exit(main())
