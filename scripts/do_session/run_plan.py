"""What one trial means on each host: pure, from the frozen manifest and the grant. Nothing here touches anything.

``ReleaseAdapter`` is the seam for handoff slice 5. It maps a trial to today's binaries, and the threaded common-window
recorder will change only the arguments it produces. Budget terms come from the same place as admission, so the process
bound and the admitted estimate cannot drift apart.
"""
import hashlib
import json

import guest_runner
import search

RUNNER_DIR = '/home/deploy/omega-agent'
RELEASE_DIR = '/home/deploy/omega-release'
SOURCE_DIR = '/home/deploy/omega-source'
GAME_PORT = 8081
METRICS_PORT = 9100
SAMPLER_INTERVAL_S = 1


def runner_remote_path(runner_sha256):
    """Content addressed, so an upload can never replace the runner a live supervisor is executing."""
    return '%s/guest_runner-%s.py' % (RUNNER_DIR, runner_sha256[:16])


def unit_name(session_id, run_id, role):
    digest = hashlib.sha256((session_id + '\0' + run_id).encode('utf-8')).hexdigest()[:16]
    return 'omega-run-%s-%s.service' % (digest, role)


def workload_s(trial):
    """The part of a trial with workload processes running: join, warmup, hold. Everything else is the reset and export after it."""
    return search.readiness_bound_s(trial.target) + search.POST_AUTH_WARMUP_S + trial.hold_s


class ReleaseAdapter:
    """Today's release layout on a provisioned pair. Every argument is the frozen workload's, named explicitly."""
    release_dir = RELEASE_DIR
    source_dir = SOURCE_DIR
    interface = None
    game_port = GAME_PORT
    metrics_port = METRICS_PORT
    sampler_interval_s = SAMPLER_INTERVAL_S

    def game_address(self, addresses):
        return addresses['game']

    def game_process(self, manifest, trial, addresses):
        program = self.release_dir + '/omega-server'
        return dict(name='game', primary=True, argv=[program, '--config', self.release_dir + '/server_config.json', '--mode', 'arena',
                                                     '--port', str(self.game_port), '--allow-unsigned-tickets'],
                    env=dict(OMEGA_MEASURE_DIR='{run_dir}/telemetry', RUST_LOG='info'), make_dirs=['{run_dir}/telemetry'])

    def bot_process(self, manifest, trial, addresses):
        workload = manifest['workload']
        return dict(name='bot', primary=True, argv=[self.release_dir + '/omega-load-test', '--server', '%s:%d' % (self.game_address(addresses), self.game_port),
                                                    '--bots', str(trial.target), '--duration', str(trial.hold_s), '--behavior', workload['behavior'],
                                                    '--difficulty', str(workload['difficulty']), '--input-hz', str(workload['input_hz']), '--seed', str(workload['seed']),
                                                    '--threads', str(workload['generator_threads']), '--stagger', str(workload['join_stagger_ms']),
                                                    '--output', '{run_dir}/report.json'], env=dict(RUST_LOG='info'))

    def sampler_process(self, role):
        argv = ['python3', self.release_dir + '/sample_host.py', '--out', '{run_dir}/sampler.ndjson', '--pids', '{run_dir}/sampler.pids', '--interval', str(SAMPLER_INTERVAL_S)]
        if role == 'game':
            argv += ['--udp-port', str(self.game_port)]
        return dict(name='sampler', argv=argv)

    def program_paths(self):
        return dict(game=self.release_dir + '/omega-server', bot=self.release_dir + '/omega-load-test')

    def config_path(self):
        return self.release_dir + '/server_config.json'

    def sampler_path(self, role):
        return self.release_dir + '/sample_host.py'

    def completed_exit_codes(self, role):
        """Statuses meaning the process ran to its end. The swarm exits 1 when its own success criteria fail, after writing its report.

        That is a verdict on the server's numbers, not a generator failure, and this slice ignores the verdict itself.
        Anything else is a crash: 2 is a usage or configuration error, 101 a panic, and a signal has no status.
        """
        return (0, 1) if role == 'bot' else (0,)

    def required_on_clean_exit(self, role):
        return ('sampler.ndjson', 'report.json') if role == 'bot' else ('sampler.ndjson',)


def expected_files(adapter, manifest, role, sampler_sha256):
    """Exactly the bytes this run may execute. Binary and config come from the manifest, and the sampler from recorded readiness."""
    source = manifest['source']
    files = [dict(path=adapter.program_paths()[role], sha256=source['binary_sha256'][role], role='program'),
             dict(path=adapter.sampler_path(role), sha256=sampler_sha256, role='support')]
    if role == 'game':
        files.insert(1, dict(path=adapter.config_path(), sha256=source['server_config_sha256'], role='config'))
    return files


def role_plan(adapter, manifest, sha, trial, role, addresses, sampler_sha256, fencing_token, unit_mode, launch_not_after_wall, bound_s, stop_by_wall, stop_grace_s):
    session_id = manifest['session']['id']
    process = adapter.game_process(manifest, trial, addresses) if role == 'game' else adapter.bot_process(manifest, trial, addresses)
    ports = [dict(protocol='udp', port=adapter.game_port), dict(protocol='tcp', port=adapter.metrics_port)] if role == 'game' else []
    return dict(schema=guest_runner.PLAN_SCHEMA, session_id=session_id, manifest_sha256=sha, run_id=trial.run_id, role=role, fencing_token=fencing_token,
                unit_mode=unit_mode, unit=unit_name(session_id, trial.run_id, role), processes=[process], sampler=adapter.sampler_process(role),
                verify_files=expected_files(adapter, manifest, role, sampler_sha256), ports=ports, interface=adapter.interface,
                source_dir=adapter.source_dir if role == 'bot' else None, watch_socket_port=adapter.game_port if role == 'game' else None,
                launch_not_after_wall=launch_not_after_wall, bound_s=bound_s, stop_by_wall=stop_by_wall, stop_grace_s=stop_grace_s,
                sampler_interval_s=adapter.sampler_interval_s, required_on_clean_exit=list(adapter.required_on_clean_exit(role)),
                completed_exit_codes=list(adapter.completed_exit_codes(role)))


def plan_digest(plan):
    return hashlib.sha256(json.dumps(plan, sort_keys=True).encode('utf-8')).hexdigest()
