"""Whole sessions for the exporter: the real controller, registry, watchdog, prover and scorer over a fake account and fake guests whose runs leave real-format files.

Nothing ran to make any of this, so every number in these sessions is arithmetic and says nothing about any host. ``enrich`` writes what the real server, sampler and supervisor write that the slice 5 trees leave out, so that a report has something to report.
Every marker here is an obviously synthetic value, assembled at run time, so no test leaves a real-looking credential on disk or in the repository.
"""
import json

import evidence_publication
import measurement_fixtures as fx
import run_fixtures as rf
import scoring_fixtures as sf
import ssh_access

NS = fx.NS
SOCKET_MARKER = 'synthetic' + '-socket-' + 'canary-7f3a'
ENDPOINT_MARKER = '198.51.100.' + '77'
KERNEL_ENDPOINT_MARKER = 'C6336' + '44D:9C40'
INTERFACE_TX_PER_S = 40_000
INTERFACE_RX_PER_S = 3_000
APP_BYTES_PER_S = 20_000


def _sample_rows(tree):
    """``server.ndjson`` as ``measurement.rs`` writes it: cumulative, once a second, on the game's own monotonic origin."""
    rows = []
    finish = fx.to_game_mono(tree.timeline.finish) + 2 * NS
    for second in range(int(finish // NS) + 1):
        phases = {name: dict(count=second * 30, total_ns=second * 30 * cost, max_ns=cost * 2, buckets=[0] * 10) for name, cost in (('world_tick', 1_000_000), ('snapshot_build', 400_000), ('outbox_flush', 100_000), ('enet_flush', 100_000), ('service_and_route', 100_000))}
        rows.append(dict(utc_ns=fx.GAME_MONO_ORIGIN_WALL + second * NS, mono_ns=second * NS, boundary='', loop_phases=phases, tick=second * 30, sent_bytes_by_type_channel=[[1, [second * APP_BYTES_PER_S, second * 100, 0]]], received_bytes_by_type_channel=[], send_errors=0, decode_errors=0,
                         event_sends=[second * 90] + [0] * 255, reliable_event_sends=[second * 30] + [0] * 255, source_events=[second * 10] + [0] * 255, baselines=0, deltas=0, players=[]))
    return rows


def enrich(tree, trial=None):
    """What a real game and sampler also leave. A game role's ``sockets.ndjson`` comes from its supervisor, and the rest from a Linux collector."""
    def sampler(role):
        def edit(index, row):
            row['system'] = dict(total_s=float(index * 4), idle_s=float(index * 3), steal_s=index * 0.04)
            row['memory'] = dict(MemTotal=1_000_000_000, MemAvailable=500_000_000 - index, SwapTotal=0, SwapFree=0, oom_kill=0, pgmajfault=index, pswpin=0, pswpout=0)
            row['interfaces'] = dict(lo=dict(rx_bytes=index * 7, rx_packets=index, rx_errs=0, rx_drop=0, tx_bytes=index * 7, tx_packets=index, tx_errs=0, tx_drop=0),
                                     eth0=dict(rx_bytes=index * INTERFACE_RX_PER_S, rx_packets=index, rx_errs=0, rx_drop=0, tx_bytes=index * INTERFACE_TX_PER_S, tx_packets=index, tx_errs=0, tx_drop=0))
            process = row['procs'][role]
            process['rss_bytes'] = 50_000_000 + index
            process['thread_cpu_s'] = {'swarm-%d/%d' % (shard, 7000 + shard): index * 0.1 for shard in range(4)} if role == 'bot' else {'omega-server/%d' % process['pid']: index * 0.2}
        tree.edit_sampler(role, edit)
    sampler('game')
    sampler('bot')
    tree.path('game/telemetry/server.ndjson').write_text(''.join(json.dumps(row) + '\n' for row in _sample_rows(tree)))
    tree.path('game/sockets.ndjson').write_text(json.dumps(dict(inode='fixture', local_port=8081, drops=0)) + '\n')


def expose_socket_fields(tree):
    """A collector that grew new socket fields, including one nobody has heard of. The older publisher's field list knows none of them."""
    def edit(index, row):
        for item in row['procs']['game']['sockets']:
            item.update(remote=ENDPOINT_MARKER + ':40001', remote_hex=KERNEL_ENDPOINT_MARKER, peer_cookie=SOCKET_MARKER)
        row['udp']['socket_owner_note'] = SOCKET_MARKER
    tree.edit_sampler('game', edit)
    tree.path('game/sockets.ndjson').write_text(json.dumps(dict(inode='fixture', local_port=8081, drops=0, remote=ENDPOINT_MARKER, peer_cookie=SOCKET_MARKER)) + '\n')


def enriched(rules=None, default=None, extra=None):
    """A script from ``scoring_fixtures.by_target`` rules, over a whole enriched tree."""
    chooser = sf.by_target(rules or {}, default)

    def script(tree, trial):
        enrich(tree, trial)
        chooser(tree, trial)
        if extra is not None:
            extra(tree, trial)
    return script


CONFIRMING = {50: sf.slow, 35: sf.slow}     # 25 passes, 50 fails, 30 passes, 35 fails, three confirmations at 30


class ExportGuests(sf.ScoredGuests):
    """Fake guests with what can go wrong on the wire. ``get_hook(role, relative, data, attempt)`` returns (returncode, bytes): what arrives, and whether the copy says it worked."""

    def __init__(self, sim, script):
        super().__init__(sim, script)
        self.get_hook = None
        self.attempts = {}

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        if self.get_hook is None or '/do-runs/runs/' not in str(remote_path):
            return super().get(role, remote_path, local_path, timeout_s, on_wait)
        parts = str(remote_path).split('/do-runs/runs/')[1].split('/', 2)
        self.commands.append(dict(role=role, step='get', remote=str(remote_path)))
        data = self.hosts[role].runs[parts[0]].files[parts[2]]
        key = (parts[0], role, parts[2])
        attempt = self.attempts[key] = self.attempts.get(key, 0) + 1
        code, data = self.get_hook(role, parts[0], parts[2], data, attempt)
        if data is not None:
            with open(str(local_path), 'wb') as handle:
                handle.write(data)
        return ssh_access.CommandResult(code, '', '' if code == 0 else 'scripted transfer failure')


class ExportSim(sf.ScoredSim):
    """A session whose manifest names the amended destination. ``run`` goes through the same ``run_batch`` the operator CLI calls."""

    def __init__(self, case, script=None, **options):
        options.setdefault('durable_destination', evidence_publication.AMENDED_DESTINATION)
        super().__init__(case, script, **options)
        self.guests.close()
        self.guests = ExportGuests(self, script or (lambda tree, trial: None))
        case.addCleanup(self.guests.close)
        case.addCleanup(rf.make_writable, self.stack.root)

    def batch(self, **options):
        self.ready()
        return self.executor(**options).run_batch()

    @property
    def root(self):
        return self.stack.root

    def generation(self, name):
        return self.root / 'export' / name

    def document(self, name, relative='inventory.json'):
        return json.loads((self.generation(name) / relative).read_text())
