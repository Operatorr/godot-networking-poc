"""Deterministic recorder files for ``measurement_window``: every file a real run writes, generated on a mocked timeline.

Nothing ran to make these, so a proof over them shows what the prover does with those bytes and nothing about any window. Real
processes and real time are ``measurement_local``. A test builds one complete tree, breaks one thing, and states the reason it expects.

The two roles get different monotonic origins on purpose, and their wall clocks can differ too, so any accidental comparison of the
two domains breaks the complete case.
"""
import copy
import csv
import json
import pathlib

import manifest as manifest_mod
import measurement_window as mw

NS = mw.NS
BOT_MONO_ORIGIN_WALL = 1_800_000_000 * NS      # wall time at the swarm's monotonic zero
GAME_MONO_ORIGIN_WALL = BOT_MONO_ORIGIN_WALL - 20 * NS
START_TICK = 500
FIELDS = ['id', 'phase', 'alive', 'sent', 'send_errors', 'missed_slots', 'dead_frames', 'decode_failures', 'errors', 'panics', 'snapshots', 'rx_bytes', 'tx_bytes', 'socket_sent', 'socket_zero_sends',
          'socket_send_errors', 'socket_received', 'socket_receive_errors', 'gap_max_ns', 'peer']


def bot_pair(mono):
    wall = BOT_MONO_ORIGIN_WALL + mono
    return dict(wall_before_ns=wall - 1000, mono_ns=mono, wall_after_ns=wall + 1000)


def game_pair(mono, game_wall_offset=0):
    wall = GAME_MONO_ORIGIN_WALL + mono + game_wall_offset
    return dict(wall_before_ns=wall - 1000, mono_ns=mono, wall_after_ns=wall + 1000)


class Timeline:
    def __init__(self, target=8, hold_s=60, threads=4):
        self.target, self.hold_s, self.threads = target, hold_s, threads
        self.stagger_ns = 100_000_000
        self.joins = {bot: (bot - 1) * self.stagger_ns for bot in range(1, target + 1)}
        self.auths = {bot: at + 50_000_000 for bot, at in self.joins.items()}
        self.final_auth = max(self.auths.values())
        self.barrier = self.final_auth + 1_000_000
        self.published = self.final_auth + 2 * NS + 5_000_000
        self.start = self.published + NS
        self.end = self.start + hold_s * NS
        self.drain = self.end + 2 * NS
        self.finish = self.drain + NS

    def owned(self, shard):
        return [bot for bot in range(1, self.target + 1) if (bot - 1) % self.threads == shard]


def write_ndjson(path, rows):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), 'w') as handle:
        for index, row in enumerate(rows):
            handle.write(json.dumps(dict(row, seq=row.get('seq', index))) + '\n')


def scheduled(timeline):
    return timeline.hold_s * 30


def swarm_files(root, timeline, pid=4001, start_id='ticks:9001', boot='boot-bot'):
    directory = root / 'bot' / 'swarm'
    directory.mkdir(parents=True)
    nonce = 'fixture-nonce'
    controls = dict(server='203.0.113.10:8081', bots=timeline.target, threads=timeline.threads, bot_id_assignment='round-robin', join_stagger_ms=100, behavior='strategy', difficulty=1.0, input_hz=30, input_interval_ns=33_333_333,
                    seed=1, hold_s=timeline.hold_s, readiness_timeout_s=60.0, bandwidth_budget_bps=0, warmup_ns=2 * NS, publish_lead_ns=NS, end_guard_ns=2 * NS, drain_ns=1_500_000_000, ticket_auth=False, faults=[])
    (directory / 'swarm.json').write_text(json.dumps(dict(schema=mw.schema()['id'], nonce=nonce, role='bot', pid=pid, kernel_start_id=start_id, boot_id=boot, version='0.1.0', clock=bot_pair(0), build=dict(fault_injection=False), controls=controls)) + '\n')
    rows = [dict(k='header', nonce=nonce, schema=mw.schema()['id'], role='bot', clock=bot_pair(0), pid=pid)]
    for second in range(0, int(timeline.finish // NS) + 1):
        rows.append(dict(k='clock', nonce=nonce, mono_ns=second * NS, clock=bot_pair(second * NS), authenticated=timeline.target, lost_after_auth=0))
    rows.append(dict(k='barrier', nonce=nonce, mono_ns=timeline.barrier, final_auth_ns=timeline.final_auth, authenticated=timeline.target))
    rows.append(dict(k='window_published', nonce=nonce, mono_ns=timeline.published, start_ns=timeline.start, end_ns=timeline.end, hold_ns=timeline.hold_s * NS, final_auth_ns=timeline.final_auth, clock=bot_pair(timeline.published)))
    rows.append(dict(k='drain_requested', nonce=nonce, mono_ns=timeline.drain, clock=bot_pair(timeline.drain), authenticated=timeline.target))
    rows.append(dict(k='footer', nonce=nonce, mono_ns=timeline.finish, clock=bot_pair(timeline.finish), status='window_recorded', recorder_failure=None))
    write_ndjson(directory / 'coordinator.ndjson', rows)
    acks = []
    for shard in range(timeline.threads):
        owned = timeline.owned(shard)
        rows = [dict(k='header', nonce=nonce, schema=mw.schema()['id'], role='bot', shard=shard, shards=timeline.threads, thread='swarm-%d' % shard, bots=owned, bot_fields=FIELDS, gap_bounds_ms=[10, 20, 30, 35, 40, 50, 100],
                     geometry=dict(min=[-1000, -1000], max=[1000, 1000], obstacles_enabled=True, initialized_on_thread=True), clock=bot_pair(0))]
        for bot in owned:
            rows.append(dict(k='join', nonce=nonce, bot=bot, scheduled_ns=timeline.joins[bot], actual_ns=timeline.joins[bot] + 500_000, local_port=40000 + bot))
            rows.append(dict(k='connected', nonce=nonce, bot=bot, mono_ns=timeline.joins[bot] + 10_000_000))
            rows.append(dict(k='auth', nonce=nonce, bot=bot, mono_ns=timeline.auths[bot], entity_id=bot))
        rows.append(dict(k='window_observed', nonce=nonce, mono_ns=timeline.published + 2_000_000, start_ns=timeline.start, end_ns=timeline.end))
        rows.append(dict(k='ack_start', nonce=nonce, mono_ns=timeline.start + 1_000_000, start_ns=timeline.start, lateness_ns=1_000_000, running=len(owned)))
        for second in range(timeline.hold_s + 2):
            at = timeline.start - NS + second * NS
            bots = [[bot, 'Running', True, second * 30, 0, 0, 0, 0, 0, 0, second * 30, 1000, 1000, second * 30, 0, 0, second * 30, 0, 40_000_000, [[at + 100_000 * bot, 12.5, 0]]] for bot in owned]
            rows.append(dict(k='sample', nonce=nonce, mono_ns=at, clock=bot_pair(at), polls=900, max_poll_gap_ns=3_000_000, completed_observer_ns=second, bots=bots))
        rows.append(dict(k='ack_end', nonce=nonce, mono_ns=timeline.end + 1_000_000, end_ns=timeline.end, lateness_ns=1_000_000, running=len(owned)))
        rows.append(dict(k='freeze', nonce=nonce, mono_ns=timeline.end + 1_100_000, start_ns=timeline.start, end_ns=timeline.end, stillborn=[],
                         bots=[dict(id=bot, phase='Running', alive=True, scheduled=scheduled(timeline), sent=scheduled(timeline), send_errors=0, dead_frames=0, gap_buckets=[0, 0, 0, scheduled(timeline) - 1, 0, 0, 0, 0],
                                    gap_max_ns=34_000_000, last_input_ns=timeline.end - 20_000_000, decode_failures=0, errors=0, panics=0, socket_send_errors=0, socket_zero_sends=0, socket_receive_errors=0, disconnected=None, scheduled_before_disconnect=None) for bot in owned]))
        rows.append(dict(k='drain_start', nonce=nonce, mono_ns=timeline.drain + 1_000_000, clock=bot_pair(timeline.drain)))
        rows.append(dict(k='drain_end', nonce=nonce, mono_ns=timeline.drain + 100_000_000, unconfirmed_disconnects=0, bots=[]))
        rows.append(dict(k='footer', nonce=nonce, mono_ns=timeline.finish, clock=bot_pair(timeline.finish), shard=shard, left_early=False, start_acked=True, end_acked=True, polls=60000, max_poll_gap_ns=3_000_000, observer_ns=1000, recorder_failure=None))
        write_ndjson(directory / ('shard-%d.ndjson' % shard), rows)
        acks.append(dict(shard=shard, observed_ns=timeline.published + 2_000_000, start_ack_ns=timeline.start + 1_000_000, end_ack_ns=timeline.end + 1_000_000, finished=True, recorder_failed=False))
    (directory / 'window.json').write_text(json.dumps(dict(schema=mw.schema()['id'], role='bot', nonce=nonce, status='window_recorded', reason=None, bots=timeline.target, shards=timeline.threads, hold_s=timeline.hold_s, final_auth_ns=timeline.final_auth,
                                                           barrier_ns=timeline.final_auth, start_ns=timeline.start, end_ns=timeline.end, acks=acks, unjoined_shards=[], panicked_shards=[], lost_after_auth=0, lost_rows=[],
                                                           authenticated_at_end=0, clock=bot_pair(timeline.finish))) + '\n')


def to_game_mono(mono_bot):
    return mono_bot + BOT_MONO_ORIGIN_WALL - GAME_MONO_ORIGIN_WALL


def game_files(root, timeline, game_wall_offset=0, pid=3001, start_id='ticks:8001', boot='boot-game'):
    directory = root / 'game' / 'telemetry'
    directory.mkdir(parents=True)
    start = to_game_mono(0)
    end = to_game_mono(timeline.finish) + 2 * NS
    (directory / 'process.json').write_text(json.dumps(dict(schema=mw.schema()['id'], role='game', pid=pid, kernel_start_id=start_id, boot_id=boot, clock=game_pair(0, game_wall_offset))) + '\n')
    rows = []
    for second in range(0, int(end // NS) + 1):
        rows.append(dict(k='clock', mono_ns=second * NS, clock=game_pair(second * NS, game_wall_offset), tick=START_TICK + second * 30))
    for bot in range(1, timeline.target + 1):
        rows.append(dict(k='auth', peer=bot, mono_ns=to_game_mono(timeline.auths[bot]) - 5_000_000, tick=START_TICK, entity_id=bot, name='LoadBot%03d' % bot, reason=None, authenticated_after=bot))
    for bot in range(1, timeline.target + 1):
        # USER_QUIT, which is what a real drain's disconnect carries.
        rows.append(dict(k='disconnect', peer=bot, mono_ns=to_game_mono(timeline.drain) + 50_000_000 + bot, tick=START_TICK, entity_id=bot, name='LoadBot%03d' % bot, reason=0, authenticated_after=timeline.target - bot))
    rows.sort(key=lambda row: row['mono_ns'])
    rows.append(dict(k='footer', mono_ns=end, clock=game_pair(end, game_wall_offset)))
    rows = [dict(row, seq=index) for index, row in enumerate(rows)]
    write_ndjson(directory / 'population.ndjson', rows)
    columns = ['utc_ns', 'mono_ns', 'tick', 'work_ns', 'authenticated']
    count = 0
    with (directory / 'ticks.csv').open('w', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        interval = NS // 30
        mono = 0
        tick = START_TICK
        final_auth_game = to_game_mono(timeline.final_auth)
        drain_game = to_game_mono(timeline.drain) + 50_000_000
        while mono <= end:
            authenticated = timeline.target if final_auth_game <= mono <= drain_game else (0 if mono > drain_game else min(timeline.target, sum(1 for bot in timeline.auths if to_game_mono(timeline.auths[bot]) - 5_000_000 <= mono)))
            writer.writerow([GAME_MONO_ORIGIN_WALL + mono, mono, tick, 2_000_000, authenticated])
            count += 1
            tick += 1
            mono += interval
    (directory / 'server.ndjson').write_text('{"mono_ns": 0}\n')
    (directory / 'final.json').write_text(json.dumps(dict(schema=mw.schema()['id'], role='game', tick_rows=count, last_tick=tick - 1, world_tick=tick - 1, population_rows=len(rows), peers_at_shutdown=0, clock=game_pair(end, game_wall_offset))) + '\n')
    return start


READ_NS = 200_000     # how long a fixture collector takes to read its counters


def sampler_rows(role, timeline, port_map, pid, start_id, boot, pair_of, first_mono, last_mono, counters=True, inode=None):
    rows = [dict(kind='meta', platform='fixture', cpus=4, ts=0.0, schema=mw.schema()['id'])]
    mono = first_mono
    seq = 0
    while mono <= last_mono:
        drops = 0 if counters else None
        sockets = [dict(inode=inode or '%s-socket-%d' % (role, port), local='00000000:%04X' % port, local_port=port, drops=drops, rx_queue=0, tx_queue=0) for port in port_map]
        rows.append(dict(ts=1.0, mono_s=seq, clock=pair_of(mono), clock_after=pair_of(mono + READ_NS), seq=seq, boot_id=boot, system={}, udp=dict(snmp=dict(InDatagrams=seq * 100, InErrors=0, RcvbufErrors=0)), collector_ns=250_000,
                         procs={role: dict(pid=pid, alive=True, start_id=start_id, sockets=sockets, cpu_s=seq * 0.2)}))
        mono += NS
        seq += 1
    return rows


def write_sampler(root, role, rows):
    write_ndjson(root / role / 'sampler.ndjson', rows)


def bracket(label, at_wall, game_wall_offset=0, half_ns=5_000_000):
    roles = {}
    for role, offset in (('bot', 0), ('game', game_wall_offset)):
        roles[role] = [dict(before_ns=at_wall - half_ns, guest_wall_ns=at_wall + offset, guest_monotonic_ns=123, after_ns=at_wall + half_ns, boot_id='boot-' + role)]
    return dict(schema='omega.do-session.clock-bracket/1', label=label, roles=roles)


IDENTITIES = dict(bot=dict(bot=dict(pid=4001, start_id='ticks:9001', boot_id='boot-bot', primary=True), sampler=dict(pid=4002, start_id='ticks:9002', boot_id='boot-bot', primary=False)),
                  game=dict(game=dict(pid=3001, start_id='ticks:8001', boot_id='boot-game', primary=True), sampler=dict(pid=3002, start_id='ticks:8002', boot_id='boot-game', primary=False)))


class Tree:
    """One complete run, ready to break. ``prove()`` is the production prover with this run's arguments."""

    def __init__(self, root, target=8, hold_s=60, game_wall_offset=0, identities=None, game_inode=None):
        """``identities`` and ``game_inode`` let a tree stand for processes a fake guest named, which only the integrated fixtures need."""
        self.root = pathlib.Path(root)
        self.timeline = Timeline(target, hold_s)
        self.trial = dict(run_id='fixture-run', ordinal=1, phase='coarse' if hold_s == 60 else 'confirm', target=target, repetition=1, hold_s=hold_s, predecessors=[])
        self.workload = dict(manifest_mod.WORKLOAD_SCHEMA)
        self.identities = copy.deepcopy(identities or IDENTITIES)
        self.game_wall_offset = game_wall_offset
        bot, game = self.identities['bot']['bot'], self.identities['game']['game']
        swarm_files(self.root, self.timeline, bot['pid'], bot['start_id'], bot['boot_id'])
        game_files(self.root, self.timeline, game_wall_offset, game['pid'], game['start_id'], game['boot_id'])
        ports = [40000 + bot_id for bot_id in range(1, target + 1)]
        write_sampler(self.root, 'bot', sampler_rows('bot', self.timeline, ports, bot['pid'], bot['start_id'], bot['boot_id'], bot_pair, 0, self.timeline.finish))
        game_first = to_game_mono(0)
        write_sampler(self.root, 'game', sampler_rows('game', self.timeline, [8081], game['pid'], game['start_id'], game['boot_id'], lambda mono: game_pair(mono, game_wall_offset), game_first, to_game_mono(self.timeline.finish), inode=game_inode))
        self.brackets = dict(before=bracket('before', BOT_MONO_ORIGIN_WALL - 30 * NS, game_wall_offset), after=bracket('after', BOT_MONO_ORIGIN_WALL + self.timeline.finish + 30 * NS, game_wall_offset))

    def prove(self, **options):
        arguments = dict(identities=self.identities, brackets=self.brackets)
        arguments.update(options)
        return mw.prove(self.root, self.trial, self.workload, **arguments)

    # ---- helpers for breaking it ---------------------------------------------------------------

    def path(self, relative):
        return self.root / relative

    def rows(self, relative):
        return [json.loads(line) for line in self.path(relative).read_text().splitlines()]

    def put_rows(self, relative, rows):
        self.path(relative).write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def edit_rows(self, relative, edit):
        rows = self.rows(relative)
        edit(rows)
        self.put_rows(relative, rows)

    def edit_json(self, relative, edit):
        document = json.loads(self.path(relative).read_text())
        edit(document)
        self.path(relative).write_text(json.dumps(document) + '\n')

    def edit_shard_row(self, shard, kind, edit):
        def change(rows):
            for row in rows:
                if row.get('k') == kind:
                    edit(row)
                    return
            raise AssertionError('no %s row' % kind)
        self.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)

    def drop_shard_rows(self, shard, kind):
        def change(rows):
            kept = [row for row in rows if row.get('k') != kind]
            for index, row in enumerate(kept):
                row['seq'] = index
            rows[:] = kept
        self.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)

    def edit_sampler(self, role, edit):
        """``edit(index, row)`` over one collector's measured rows, without its header row."""
        def change(rows):
            for index, row in enumerate(row for row in rows if row.get('kind') != 'meta'):
                edit(index, row)
        self.edit_rows(role + '/sampler.ndjson', change)

    def sampler_pair(self, role, mono):
        """A wall/monotonic pair in this role's own collector domain, for placing a counter read exactly."""
        return bot_pair(mono) if role == 'bot' else game_pair(mono, self.game_wall_offset)

    def role_mono(self, role, mono_bot):
        """A moment on the swarm's clock, on this role's own monotonic clock."""
        return mono_bot if role == 'bot' else to_game_mono(mono_bot)

    def edit_frozen_bot(self, bot, edit):
        shard = (bot - 1) % self.timeline.threads

        def change(row):
            for item in row['bots']:
                if item['id'] == bot:
                    edit(item)
        self.edit_shard_row(shard, 'freeze', change)
