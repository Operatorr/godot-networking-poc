"""Deterministic scenarios for ``capacity_scorer``: complete recorder trees, one thing changed, and the real prover and scorer over the bytes.

Nothing ran to make these, so each number is arithmetic and no result here says anything about any host. Two ways in:

  ``Scenario``      one tree, scored directly, for exact thresholds and attribution
  ``ScoredSim``     the real executor, registry, prover and scorer over a fake guest whose runs leave these trees behind, for search branches, crashes and resume
"""
import csv
import json
import pathlib
import shutil
import tempfile

import capacity_scorer as cs
import fake_run_guest
import guest_runner
import measurement_fixtures as fx
import measurement_window as mw
import run_fixtures as rf
import run_plan

NS = mw.NS
FROZEN_SCHEMA = dict(id=mw.schema()['id'], sha256=mw.schema_sha256())


# ---- changing a tree -------------------------------------------------------------------------------

def tight_clocks(tree, half_ns=1000):
    """Clock brackets so narrow that the widest and narrowest intervals hold the same Ticks, for checking an exact threshold."""
    tree.brackets = dict(before=fx.bracket('before', fx.BOT_MONO_ORIGIN_WALL - 30 * NS, tree.game_wall_offset, half_ns=half_ns), after=fx.bracket('after', fx.BOT_MONO_ORIGIN_WALL + tree.timeline.finish + 30 * NS, tree.game_wall_offset, half_ns=half_ns))


def tick_rows(tree):
    with tree.path('game/telemetry/ticks.csv').open(newline='') as handle:
        return list(csv.reader(handle))


def write_ticks(tree, rows):
    with tree.path('game/telemetry/ticks.csv').open('w', newline='') as handle:
        csv.writer(handle).writerows(rows)


def ticks_in_window(tree, rows, margin_ns=NS):
    """The row indexes of Ticks well inside the window, so that a change to them cannot depend on the clocks."""
    low, high = fx.to_game_mono(tree.timeline.start) + margin_ns, fx.to_game_mono(tree.timeline.end) - margin_ns
    return [index for index, row in enumerate(rows) if index and low <= int(row[1]) <= high]


def set_slow_ticks(tree, count, work_ns):
    rows = tick_rows(tree)
    for index in ticks_in_window(tree, rows)[:count]:
        rows[index][3] = str(work_ns)
    write_ticks(tree, rows)


def count_ticks(tree, proof=None):
    rows = tick_rows(tree)
    proof = proof or tree.prove(telemetry_schema=FROZEN_SCHEMA)
    low, high = proof['facts']['population']['interval_game_mono_ns']
    return sum(1 for row in rows[1:] if low <= int(row[1]) <= high)


def edit_peer_samples(tree, edit):
    """``edit(bot, seconds_into_window, sample)`` returns a new [at, rtt, loss], or None to drop it. Only in-window samples are offered."""
    start, end = tree.timeline.start, tree.timeline.end
    for shard in range(tree.timeline.threads):
        def change(rows):
            for row in rows:
                if row.get('k') != 'sample':
                    continue
                for item in row['bots']:
                    kept = []
                    for sample in item[-1]:
                        if start <= sample[0] < end:
                            sample = edit(item[0], (sample[0] - start) // NS, sample)
                        if sample is not None:
                            kept.append(sample)
                    item[-1] = kept
        tree.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)


def set_rtt(tree, value_of):
    edit_peer_samples(tree, lambda bot, second, sample: [sample[0], value_of(bot, second), sample[2]])


def set_loss(tree, value_of):
    edit_peer_samples(tree, lambda bot, second, sample: [sample[0], sample[1], value_of(bot, second)])


def game_drop(tree, at_s, count=3):
    """The game socket's counter moves between two reads inside the window."""
    at = fx.to_game_mono(tree.timeline.start + int(at_s * NS))

    def edit(index, row):
        if row['clock']['mono_ns'] > at:
            for item in row['procs']['game']['sockets']:
                item['drops'] += count
    tree.edit_sampler('game', edit)


def game_drop_before_any_window_read(tree, count=1):
    """It moves between the baseline read and the first read inside the window, so it may have fallen just before the start."""
    first_inside = fx.to_game_mono(tree.timeline.start)

    def edit(index, row):
        if row['clock']['mono_ns'] >= first_inside - NS // 2:
            for item in row['procs']['game']['sockets']:
                item['drops'] += count
    tree.edit_sampler('game', edit)


def bot_drop(tree, bot, count=1):
    def edit(index, row):
        for item in row['procs']['bot']['sockets']:
            if item['local_port'] == 40000 + bot and index > 40:
                item['drops'] += count
    tree.edit_sampler('bot', edit)


def lose_bot(tree, bot, at_s, reason, server_at_s=None, sent=None, errors=1, server_reason=0):
    """Bot ``bot`` loses its connection ``at_s`` into the hold, on both recorders, with everything a real one leaves: an error, a lower server count, no later ENet samples."""
    timeline = tree.timeline
    at = timeline.start + int(at_s * NS)
    server_at = at if server_at_s is None else timeline.start + int(server_at_s * NS)
    owed = int(at_s * 30)

    def frozen(row):
        row.update(phase='Failed', sent=owed if sent is None else sent, last_input_ns=at - 1000 if owed else None, scheduled_before_disconnect=owed, disconnected=dict(at_ns=at, reason=reason, expected=False), errors=errors)
    tree.edit_frozen_bot(bot, frozen)
    edit_peer_samples(tree, lambda who, second, sample: None if who == bot and sample[0] >= at else sample)
    if server_at_s is not False:
        def population(rows):
            row = next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot%03d' % bot)
            row.update(mono_ns=fx.to_game_mono(server_at), reason=server_reason)
            rows.sort(key=lambda item: (item.get('k') == 'footer', item['mono_ns']))
            for index, item in enumerate(rows):
                item['seq'] = index
        tree.edit_rows('game/telemetry/population.ndjson', population)
        rows = tick_rows(tree)
        for row in rows[1:]:
            if int(row[1]) >= fx.to_game_mono(server_at) and int(row[4]) == timeline.target:
                row[4] = str(timeline.target - 1)
        write_ticks(tree, rows)


def server_row_only(tree, bot, at_s):
    """The server records a departure and a lower count, while the bot's own record shows it connected to the end."""
    at = tree.timeline.start + int(at_s * NS)

    def population(rows):
        row = next(row for row in rows if row.get('k') == 'disconnect' and row.get('name') == 'LoadBot%03d' % bot)
        row.update(mono_ns=fx.to_game_mono(at), reason=0)
        rows.sort(key=lambda item: (item.get('k') == 'footer', item['mono_ns']))
        for index, item in enumerate(rows):
            item['seq'] = index
    tree.edit_rows('game/telemetry/population.ndjson', population)
    rows = tick_rows(tree)
    for row in rows[1:]:
        if int(row[1]) >= fx.to_game_mono(at) and int(row[4]) == tree.timeline.target:
            row[4] = str(tree.timeline.target - 1)
    write_ticks(tree, rows)


def game_died(tree, at_s):
    """The game process vanished ``at_s`` into the hold: its buffered telemetry stops there and it never finished its recorders."""
    timeline = tree.timeline
    at = fx.to_game_mono(timeline.start + int(at_s * NS))
    tree.path('game/telemetry/final.json').unlink()
    write_ticks(tree, [row for index, row in enumerate(tick_rows(tree)) if not index or int(row[1]) < at])

    def population(rows):
        rows[:] = [row for row in rows if row['mono_ns'] < at and row.get('k') != 'footer']
        for index, row in enumerate(rows):
            row['seq'] = index
    tree.edit_rows('game/telemetry/population.ndjson', population)

    def sampler(rows):
        rows[:] = [row for row in rows if row.get('kind') == 'meta' or row['clock']['mono_ns'] < at]
    tree.edit_rows('game/sampler.ndjson', sampler)


def bots_time_out_after_game_died(tree, bots, at_s):
    """What a bot sees once a server is gone: ENet gives up with reason 0, between 5 and 30 s later, and it kept sending until then."""
    for bot in bots:
        lose_bot(tree, bot, at_s, reason=0, server_at_s=False)


def ramp_failure(tree, reason, authenticated=None):
    """The swarm gave up before publishing a window. Each shard is left as a real one leaves it: joined bots, a drain, a footer, and no window rows, under the coordinator's own abort row."""
    timeline = tree.timeline
    authenticated = timeline.target if authenticated is None else authenticated

    def window(document):
        document.update(status='not_established', reason=reason, final_auth_ns=None, barrier_ns=None, start_ns=None, end_ns=None, lost_after_auth=0, lost_rows=[], authenticated_at_end=authenticated)
        for ack in document['acks']:
            ack.update(observed_ns=None, start_ack_ns=None, end_ack_ns=None)
    tree.edit_json('bot/swarm/window.json', window)

    def coordinator(rows):
        rows[:] = [row for row in rows if row.get('k') not in ('window_published', 'barrier', 'drain_requested')]
        rows.insert(-1, dict(k='abort', nonce='fixture-nonce', mono_ns=timeline.drain, reason=reason, authenticated=authenticated))
        for index, row in enumerate(rows):
            row['seq'] = index
        rows[-1]['status'] = 'not_established'
    tree.edit_rows('bot/swarm/coordinator.ndjson', coordinator)
    for shard in range(timeline.threads):
        def change(rows):
            rows[:] = [row for row in rows if row.get('k') not in ('window_observed', 'ack_start', 'ack_end', 'freeze') and not (row.get('k') == 'auth' and row['bot'] > authenticated)]
            for index, row in enumerate(rows):
                row['seq'] = index
            rows[-1].update(start_acked=False, end_acked=False)
        tree.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)
    if authenticated != timeline.target:
        rows = tick_rows(tree)
        for row in rows[1:]:
            row[4] = str(min(int(row[4]), authenticated))
        write_ticks(tree, rows)
        def population(rows):
            rows[:] = [row for row in rows if not (row.get('k') == 'auth' and int(row['name'][7:]) > authenticated)]
            for index, row in enumerate(rows):
                row['seq'] = index
        tree.edit_rows('game/telemetry/population.ndjson', population)
    final = sum(1 for _ in tree.path('game/telemetry/population.ndjson').read_text().splitlines())
    ticks = len(tick_rows(tree)) - 1
    tree.edit_json('game/telemetry/final.json', lambda d: d.update(population_rows=final, tick_rows=ticks))


def add_bot_end(tree, bot, error, disconnected=None, panics=0):
    shard = (bot - 1) % tree.timeline.threads

    def change(rows):
        at = tree.timeline.joins[bot] + 200_000_000
        rows.insert(-1, dict(k='bot_end', nonce='fixture-nonce', bot=bot, mono_ns=at, phase='Failed', error=error, unexpected=disconnected is not None, panics=panics, disconnected=disconnected))
        for index, row in enumerate(rows):
            row['seq'] = index
    tree.edit_rows('bot/swarm/shard-%d.ndjson' % shard, change)


def ramp_slow_ticks(tree, fraction_percent):
    """Slow Ticks where the server held players, on a ramp that produced no window."""
    rows = tick_rows(tree)
    held = [index for index, row in enumerate(rows) if index and int(row[4]) >= 1]
    for index in held[:len(held) * fraction_percent // 100 + 1]:
        rows[index][3] = str(50_000_000)
    write_ticks(tree, rows)


# ---- evidence a generator proof needs, and whose it is ---------------------------------------------------

def _cut_file(tree, relative):
    data = tree.path(relative).read_bytes()
    tree.path(relative).write_bytes(data[:len(data) // 2])


def _drop_coordinator_rows(tree, kind):
    def change(rows):
        rows[:] = [row for row in rows if row.get('k') != kind]
        for index, row in enumerate(rows):
            row['seq'] = index
    tree.edit_rows('bot/swarm/coordinator.ndjson', change)


def _drop_frozen_bot(tree, bot):
    tree.edit_shard_row((bot - 1) % tree.timeline.threads, 'freeze', lambda row: row.update(bots=[item for item in row['bots'] if item['id'] != bot]))


def _bot_socket(tree, edit, only_index=None):
    def change(index, row):
        if only_index is None or index == only_index:
            for item in row['procs']['bot']['sockets']:
                edit(item)
    tree.edit_sampler('bot', change)


def _drop_bot_socket(tree, port, only_index=None):
    def change(index, row):
        if only_index is None or index == only_index:
            row['procs']['bot']['sockets'] = [item for item in row['procs']['bot']['sockets'] if item['local_port'] != port]
    tree.edit_sampler('bot', change)


def _swarm_wall_step(tree, at_s=20, jump_ns=NS):
    def change(rows):
        for row in rows:
            if isinstance(row.get('clock'), dict) and row['clock']['mono_ns'] >= tree.timeline.start + at_s * NS:
                row['clock'] = dict(row['clock'], wall_before_ns=row['clock']['wall_before_ns'] + jump_ns, wall_after_ns=row['clock']['wall_after_ns'] + jump_ns)
    tree.edit_rows('bot/swarm/coordinator.ndjson', change)


# Each leaves a tree that says nothing of whether the generator kept up, and none of them can be a consequence of anything the server did. (name, the prover's code, the change)
GENERATOR_OMISSIONS = (
    ('footer_without_poll_liveness', 'poll_liveness_missing', lambda t: t.edit_shard_row(0, 'footer', lambda row: row.pop('max_poll_gap_ns'))),
    ('footer_silent_on_leaving_early', 'poll_liveness_missing', lambda t: t.edit_shard_row(0, 'footer', lambda row: row.pop('left_early'))),
    ('sample_without_poll_liveness', 'poll_liveness_missing', lambda t: t.edit_shard_row(1, 'sample', lambda row: row.pop('max_poll_gap_ns'))),
    ('freeze_without_a_time', 'freeze_time_missing', lambda t: t.edit_shard_row(0, 'freeze', lambda row: row.pop('mono_ns'))),
    ('frozen_before_the_end', 'frozen_before_end', lambda t: t.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=t.timeline.end - NS))),
    ('frozen_before_acknowledging_the_end', 'frozen_before_end_acknowledgment', lambda t: t.edit_shard_row(0, 'freeze', lambda row: row.update(mono_ns=t.timeline.end + 500_000))),
    ('no_drain_record', 'drain_missing', lambda t: t.drop_shard_rows(2, 'drain_start')),
    ('drain_without_a_time', 'drain_time_missing', lambda t: t.edit_shard_row(2, 'drain_start', lambda row: row.pop('mono_ns'))),
    ('join_without_times', 'join_missing', lambda t: t.edit_shard_row(3, 'join', lambda row: row.pop('actual_ns'))),
    ('frozen_row_without_a_field', 'input_record_missing', lambda t: t.edit_frozen_bot(1, lambda row: row.pop('gap_buckets'))),
    ('frozen_row_absent', 'input_record_missing', lambda t: _drop_frozen_bot(t, 2)),
    ('no_window_publication', 'window_publish_missing', lambda t: _drop_coordinator_rows(t, 'window_published')),
    ('coordinator_cut_short', 'recorder_truncated', lambda t: _cut_file(t, 'bot/swarm/coordinator.ndjson')),
    ('no_final_authentication_time', 'window_boundaries_missing', lambda t: t.edit_json('bot/swarm/window.json', lambda d: d.update(final_auth_ns=None))),
    ('no_readiness_bound', 'window_boundaries_missing', lambda t: t.edit_json('bot/swarm/swarm.json', lambda d: d['controls'].update(readiness_timeout_s=None))),
    ('silent_on_which_shards_ended', 'swarm_evidence_missing', lambda t: t.edit_json('bot/swarm/window.json', lambda d: d.update(panicked_shards=None))),
    ('shard_file_missing', 'shard_evidence_missing', lambda t: t.path('bot/swarm/shard-1.ndjson').unlink()),
    ('shard_file_cut_short', 'recorder_truncated', lambda t: _cut_file(t, 'bot/swarm/shard-1.ndjson')),
    ('no_bot_collector', 'collector_evidence_missing', lambda t: t.path('bot/sampler.ndjson').unlink()),
    ('generator_socket_absent_from_one_read', 'socket_evidence_missing', lambda t: _drop_bot_socket(t, 40001, only_index=20)),
    ('generator_counter_missing', 'socket_counters_missing', lambda t: _bot_socket(t, lambda item: item.update(drops=None))),
)


def _set_recorder(relative, **fields):
    return lambda tree: tree.edit_json(relative, lambda document: document.update(fields))


def _bot_proc(**fields):
    return lambda tree: tree.edit_sampler('bot', lambda index, row: row['procs']['bot'].update(fields))


def _game_proc(**fields):
    return lambda tree: tree.edit_sampler('game', lambda index, row: row['procs']['game'].update(fields))


def _inode_changes(tree):
    def change(index, row):
        if index > 10:
            for item in row['procs']['bot']['sockets']:
                if item['local_port'] == 40003:
                    item['inode'] = 'another-socket'
    tree.edit_sampler('bot', change)


def _wrong_endpoint(tree):
    def change(index, row):
        for item in row['procs']['bot']['sockets']:
            if item['local_port'] == 40003:
                item['local_port'] = 40999
    tree.edit_sampler('bot', change)


def _unclaimed_socket(tree):
    def change(index, row):
        row['procs']['bot']['sockets'].append(dict(row['procs']['bot']['sockets'][0], inode='nobody', local_port=41999))
    tree.edit_sampler('bot', change)


def _set_abort(tree, edit):
    def change(rows):
        edit(next(row for row in rows if row.get('k') == 'abort'))
    tree.edit_rows('bot/swarm/coordinator.ndjson', change)


def _keep_bot_reads(tree, count):
    def change(rows):
        kept = [row for row in rows if row.get('kind') == 'meta']
        rows[:] = kept + [row for row in rows if row.get('kind') != 'meta'][:count]
    tree.edit_rows('bot/sampler.ndjson', change)


def _last_read_before_abort(tree):
    """How many reads come before a ramp's abort, which is also the index of the first read after it. Reads come at every whole second, from zero."""
    return int(tree.timeline.drain // NS) + 1


def _abort_straddles_the_last_read(tree):
    """The final read and the abort are close enough that the clocks allow either order."""
    last = _last_read_before_abort(tree)
    _set_abort(tree, lambda row: row.update(mono_ns=last * NS - 40_000))
    _keep_bot_reads(tree, last + 1)


def _forget_bot_join(tree, bot=3):
    def change(rows):
        rows[:] = [row for row in rows if not (row.get('k') in ('join', 'connected', 'auth') and row.get('bot') == bot)]
        for row in rows:
            if row.get('k') == 'sample':
                row['bots'] = [item for item in row['bots'] if item[0] != bot]
        for index, row in enumerate(rows):
            row['seq'] = index
    tree.edit_rows('bot/swarm/shard-%d.ndjson' % ((bot - 1) % tree.timeline.threads), change)
    _drop_bot_socket(tree, 40000 + bot)


def _forget_bot_counters(tree, bot=3):
    def change(rows):
        for row in rows:
            if row.get('k') == 'sample':
                row['bots'] = [item for item in row['bots'] if item[0] != bot]
    tree.edit_rows('bot/swarm/shard-%d.ndjson' % ((bot - 1) % tree.timeline.threads), change)


# Ramp evidence that is not the supervised processes', or does not cover what they did. (name, the prover's code, the change). A sealed hash is no help with any of these.
RAMP_NOT_PROVEN = (
    ('foreign_swarm_pid', 'recorder_overwritten', _set_recorder('bot/swarm/swarm.json', pid=123456)),
    ('foreign_swarm_start', 'pid_reused', _set_recorder('bot/swarm/swarm.json', kernel_start_id='ticks:1')),
    ('swarm_states_no_start', 'pid_reused', _set_recorder('bot/swarm/swarm.json', kernel_start_id=None)),
    ('foreign_swarm_boot', 'recorder_overwritten', _set_recorder('bot/swarm/swarm.json', boot_id='another-boot')),
    ('foreign_game_pid', 'recorder_overwritten', _set_recorder('game/telemetry/process.json', pid=123456)),
    ('foreign_game_start', 'pid_reused', _set_recorder('game/telemetry/process.json', kernel_start_id='ticks:1')),
    ('foreign_game_boot', 'recorder_overwritten', _set_recorder('game/telemetry/process.json', boot_id='another-boot')),
    ('foreign_bot_collector_pid', 'process_identity_changed', _bot_proc(pid=123456)),
    ('foreign_bot_collector_start', 'pid_reused', _bot_proc(start_id='ticks:1')),
    ('foreign_game_collector_pid', 'process_identity_changed', _game_proc(pid=123456)),
    ('foreign_game_collector_start', 'pid_reused', _game_proc(start_id='ticks:1')),
    ('socket_changed_inode', 'socket_identity_changed', _inode_changes),
    ('socket_on_the_wrong_endpoint', 'socket_evidence_missing', _wrong_endpoint),
    ('socket_nobody_claims', 'socket_evidence_missing', _unclaimed_socket),
    ('socket_absent_from_one_read', 'socket_evidence_missing', lambda t: _drop_bot_socket(t, 40001, only_index=20)),
    ('socket_never_read', 'socket_evidence_missing', lambda t: _drop_bot_socket(t, 40002)),
    ('socket_counter_missing', 'socket_counters_missing', lambda t: _bot_socket(t, lambda item: item.update(drops=None))),
    ('join_names_no_port', 'socket_evidence_missing', lambda t: t.edit_shard_row(0, 'join', lambda row: row.pop('local_port'))),
    ('no_join_row_for_a_slot_long_past', 'join_missing', _forget_bot_join),
    ('no_counters_for_a_started_bot', 'input_record_missing', _forget_bot_counters),
    ('no_abort_row', 'window_boundaries_missing', lambda t: _drop_coordinator_rows(t, 'abort')),
    ('abort_says_something_else', 'boundary_contradiction', lambda t: _set_abort(t, lambda row: row.update(reason='interrupted'))),
    ('last_read_long_before_the_abort', 'collector_boundary_missing', lambda t: _keep_bot_reads(t, 10)),
    ('last_read_just_before_the_abort', 'collector_boundary_missing', lambda t: _keep_bot_reads(t, _last_read_before_abort(t))),
    ('last_read_may_be_before_the_abort', 'collector_boundary_missing', _abort_straddles_the_last_read),
    ('socket_gone_before_the_read_after_the_abort', 'socket_evidence_missing', lambda t: _drop_bot_socket(t, 40001, only_index=_last_read_before_abort(t))),
    ('no_bot_collector', 'collector_evidence_missing', lambda t: t.path('bot/sampler.ndjson').unlink()),
    ('footer_without_poll_liveness', 'poll_liveness_missing', lambda t: t.edit_shard_row(0, 'footer', lambda row: row.pop('max_poll_gap_ns'))),
    ('no_drain_record', 'drain_missing', lambda t: t.drop_shard_rows(1, 'drain_start')),
    ('shard_owning_someone_elses_bots', 'ownership_mismatch', lambda t: t.edit_shard_row(0, 'header', lambda row: row.update(bots=[2]))),
    ('shard_file_missing', 'shard_evidence_missing', lambda t: t.path('bot/swarm/shard-1.ndjson').unlink()),
)


# ---- what the supervisor keeps when the kernel kills a process -------------------------------------------

OOM_UNIT = run_plan.unit_name('fixture-session', 'fixture-run', 'game')      # a unit's real form, suffix and all
OOM_SUPERVISOR = dict(pid=2999, start_id='ticks:7999', boot_id='boot-game')
OOM_SAMPLER = dict(pid=3002, start_id='ticks:8002', boot_id='boot-game')
OOM_INVOCATION = 'fixture-invocation-oom'


def _oom_reading(at_ns, oom_kill, procs, **more):
    return dict(mono_ns=at_ns, wall_ns=fx.GAME_MONO_ORIGIN_WALL + at_ns, oom_kill=oom_kill, oom_group_kill=0, oom=oom_kill, procs=procs, **more)


def process_oom_document(game, supervisor=None, sampler=None, invocation=OOM_INVOCATION, unit=OOM_UNIT):
    """The file ``guest_runner.OomWatch`` leaves when the kernel takes the game: a fresh empty leaf, the game alone in it, one kill counted local to it, the reap, and the leaf empty."""
    supervisor, sampler = supervisor or OOM_SUPERVISOR, sampler or OOM_SAMPLER
    cgroup = '/system.slice/' + unit
    leaf, supervision = cgroup + '/' + guest_runner.WORKLOAD_LEAF, cgroup + '/' + guest_runner.SUPERVISION_LEAF
    keep = lambda item: {key: item[key] for key in ('pid', 'start_id', 'boot_id')}
    return dict(schema=guest_runner.OOM_SCHEMA, source='cgroup v2 memory.events.local of a leaf holding only the primary process', run_id='fixture-run', role='game', unit=unit, unit_mode='systemd', available=True, unavailable=None, cgroup=cgroup, leaf=leaf, supervision=supervision, invocation_id=invocation,
                supervisor=keep(supervisor), processes=dict(game=keep(game), sampler=keep(sampler)), member_cgroups=dict(game=leaf, sampler=supervision, supervisor=supervision),
                baseline=_oom_reading(1_000, 0, [], unit_oom_kill=0), bound=_oom_reading(2_000, 0, [game['pid']], unit_oom_kill=0),
                primary_exit=_oom_reading(3_000, 1, [], primary='game', returncode=None, signal=9, alive=['sampler'], unit_oom_kill=1),
                final=_oom_reading(4_000, 1, [], unit_oom_kill=1))


def oom_killed(tree, change=None, identity=None):
    """The sealed record of a SIGKILLed game, and the supervisor's file beside it. ``change(document)`` breaks one thing in the file."""
    game = dict(tree.identities['game']['game'])
    document = process_oom_document(game)
    if change is not None:
        change(document)
    tree.path('game/process-oom.json').write_text(json.dumps(document))
    tree.path('plan-game.json').write_text(json.dumps(dict(unit=OOM_UNIT, unit_mode='systemd', role='game')))
    record = execution(game_exit=(None, 9))
    record['roles']['game'].update(identity=identity or dict(supervisor=dict(OOM_SUPERVISOR), processes=dict(game=game, sampler=dict(OOM_SAMPLER)), invocation_id=OOM_INVOCATION))
    return record


def _oom_set(**fields):
    return lambda document: document.update(fields)


def _oom_reading_set(name, **fields):
    return lambda document: document[name].update(fields)


def _oom_cgroup(cgroup):
    """Everything agrees on a cgroup that is not the unit's, so that nothing but its name can refuse it."""
    leaf, supervision = cgroup + '/' + guest_runner.WORKLOAD_LEAF, cgroup + '/' + guest_runner.SUPERVISION_LEAF
    return lambda document: document.update(cgroup=cgroup, leaf=leaf, supervision=supervision, member_cgroups=dict(game=leaf, sampler=supervision, supervisor=supervision))


def _oom_process(name, **fields):
    return lambda document: document['processes'][name].update(fields)


# What must leave a SIGKILL unexplained. (name, the status the attribution reports, the change to the supervisor's file.)
OOM_NOT_ATTRIBUTED = (
    ('another_process_was_the_victim', 'not_attributable', _oom_process('game', pid=123456)),
    ('a_reused_pid', 'not_attributable', _oom_process('game', start_id='ticks:1')),
    ('another_boot', 'not_attributable', _oom_process('game', boot_id='another-boot')),
    ('a_victim_with_no_start_identity', 'not_attributable', _oom_process('game', start_id=None)),
    ('another_supervisor', 'not_attributable', lambda d: d['supervisor'].update(pid=123456)),
    ('another_invocation_of_the_unit', 'not_attributable', _oom_set(invocation_id='other-invocation')),
    ('another_units_cgroup', 'not_attributable', _oom_cgroup('/system.slice/ssh.service')),
    ('another_unit_named', 'not_attributable', lambda d: (_oom_cgroup('/system.slice/omega-run-other-game.service')(d), d.update(unit='omega-run-other-game.service'))),
    ('a_shared_cgroup', 'not_attributable', _oom_cgroup('/user.slice/user-1000.slice/session-1.scope')),
    ('a_member_in_another_cgroup', 'not_attributable', lambda d: d['member_cgroups'].update(game='/system.slice/ssh.service')),
    ('the_sampler_in_the_games_leaf', 'not_attributable', lambda d: d['member_cgroups'].update(sampler=d['leaf'])),
    ('the_supervisor_in_the_games_leaf', 'not_attributable', lambda d: d['member_cgroups'].update(supervisor=d['leaf'])),
    ('the_game_still_in_the_unit_itself', 'not_attributable', lambda d: d['member_cgroups'].update(game=d['cgroup'])),
    ('a_leaf_that_is_not_the_units', 'not_attributable', _oom_set(leaf='/system.slice/ssh.service/workload')),
    ('the_sampler_itself_in_the_leaf_at_a_read', 'not_attributable', lambda d: d['bound']['procs'].append(3002)),
    ('a_stranger_in_the_cgroup', 'not_attributable', lambda d: d['bound']['procs'].append(777)),
    ('a_stranger_at_the_reap', 'not_attributable', lambda d: d['primary_exit']['procs'].append(777)),
    ('a_stranger_before_anything_started', 'not_attributable', lambda d: d['baseline']['procs'].append(777)),
    ('a_leaf_that_was_not_fresh', 'not_attributable', lambda d: (d['baseline'].update(oom_kill=1), d['bound'].update(oom_kill=1), d['primary_exit'].update(oom_kill=2), d['final'].update(oom_kill=2))),
    ('a_kill_counted_only_elsewhere_in_the_unit', 'not_attributable', lambda d: (d['primary_exit'].update(oom_kill=0), d['final'].update(oom_kill=0))),
    ('no_kill_counted', 'not_attributable', _oom_reading_set('primary_exit', oom_kill=0, unit_oom_kill=0)),
    ('two_kills_counted', 'not_attributable', lambda d: (d['primary_exit'].update(oom_kill=2), d['final'].update(oom_kill=2))),
    ('a_kill_only_after_the_reap', 'not_attributable', lambda d: (d['primary_exit'].update(oom_kill=0), d['final'].update(oom_kill=1))),
    ('a_second_kill_after_the_reap', 'not_attributable', lambda d: d['final'].update(oom_kill=2)),
    ('a_stranger_left_in_the_leaf', 'not_attributable', lambda d: d['final']['procs'].append(777)),
    ('a_group_kill', 'not_attributable', _oom_reading_set('primary_exit', oom_group_kill=1)),
    ('the_counter_restarted', 'not_attributable', lambda d: (d['baseline'].update(oom_kill=5), d['bound'].update(oom_kill=5))),
    ('the_counter_went_back_before_the_reap', 'not_attributable', lambda d: (d['baseline'].update(oom_kill=3), d['bound'].update(oom_kill=0), d['primary_exit'].update(oom_kill=4), d['final'].update(oom_kill=4))),
    ('the_counter_went_back_after_the_reap', 'not_attributable', _oom_reading_set('final', oom_kill=0)),
    ('a_read_that_failed', 'not_attributable', _oom_set(primary_exit=dict(unreadable=True))),
    ('no_baseline', 'not_attributable', lambda d: d.pop('baseline')),
    ('reads_out_of_order', 'not_attributable', _oom_reading_set('bound', mono_ns=500)),
    ('the_exit_it_read_was_something_else', 'not_attributable', _oom_reading_set('primary_exit', signal=15)),
    ('no_unit_of_its_own', 'unavailable', _oom_set(available=False, unavailable='this run has no unit of its own, so no cgroup boundary is its alone')),
    ('another_schema', 'refused', _oom_set(schema='omega.other/1')),
    ('the_unit_wide_schema_that_could_not_name_a_victim', 'refused', _oom_set(schema='omega.do-session.process-oom/1')),
)

# The leaf names the game whatever happened to the others, so these are the game's. (name, the change to the supervisor's file.)
OOM_STILL_THE_GAMES = (
    ('the_sampler_died_too', lambda d: d['primary_exit'].update(alive=[], unit_oom_kill=2)),
    ('the_sampler_was_counted_at_the_same_read', lambda d: (d['primary_exit'].update(unit_oom_kill=2), d['final'].update(unit_oom_kill=2))),
)


# ---- scoring one tree --------------------------------------------------------------------------------

def execution(game_exit=None, generator=(), game=(), infrastructure=(), exported=True):
    roles = dict(bot=dict(result=dict(stop_reason='primary_exited', processes=dict(bot=dict(returncode=0, signal=None)))), game=dict(result=dict(stop_reason='stop_requested:workload_finished', processes=dict(game=dict(returncode=0, signal=None)))))
    if game_exit is not None:
        roles['game']['result'] = dict(stop_reason='primary_exited', processes=dict(game=dict(returncode=game_exit[0], signal=game_exit[1])))
        game = list(game) + ['the game process ended before the swarm finished: exit %s signal %s' % game_exit]
    verified = dict(complete=True, failed=[], files=1, copied=1)
    return dict(problems=dict(infrastructure=list(infrastructure), generator=list(generator), game=list(game)), roles=roles, exported=dict(game=verified, bot=verified) if exported else {}, interrupted=None)


class Scenario:
    def __init__(self, root, **options):
        self.tree = fx.Tree(root, **options)

    def retain_brackets(self):
        for label in ('before', 'after'):
            value = self.tree.brackets.get(label)
            path = self.tree.root / ('clock-%s.json' % label)
            if value is None:
                if path.exists():
                    path.unlink()
            else:
                path.write_text(json.dumps(value))

    def proof(self, **options):
        arguments = dict(telemetry_schema=FROZEN_SCHEMA)
        arguments.update(options)
        return self.tree.prove(**arguments)

    def evidence(self, proof=None, execution_record=None, telemetry_schema=FROZEN_SCHEMA, **prove_options):
        self.retain_brackets()
        return dict(run_id=self.tree.trial['run_id'], trial=self.tree.trial, root=str(self.tree.root), execution=execution() if execution_record is None else execution_record, execution_sha256='0' * 64, execution_ref='runs/fixture/execution.json#sha256:' + '0' * 64,
                    window_proof=self.proof(**prove_options) if proof is None else proof, window_proof_sha256='1' * 64, workload=self.tree.workload, telemetry_schema=telemetry_schema)

    def score(self, **options):
        return cs.evaluate(self.evidence(**options))


def summary(document):
    """What a reader needs from one score, with nothing machine-specific. Exact counts stay exact."""
    keep = ('verdict', 'why', 'ticks_wide', 'ticks_narrow', 'over_wide', 'over_narrow', 'worst_possible_ratio', 'least_possible_ratio', 'samples', 'rank', 'p95_ms', 'drops_in_widest_interval', 'drops_proven_inside', 'drops_at_the_uncertain_edge', 'per_second_mean_peak', 'window_mean_of_seconds', 'seconds_at_or_above_limit', 'seconds_without_coverage',
            'borrowed_readings', 'unexpected_disconnects_in_window', 'errors', 'errors_that_are_the_disconnect_itself', 'independent', 'ticks', 'over', 'ratio', 'scope')
    gates = {name: {key: value for key, value in gate.items() if key in keep} for name, gate in document['gates'].items()}
    offered = document.get('offered_load') or {}
    departures = [{key: item.get(key) for key in ('bot', 'source', 'cause', 'reason', 'server_reason', 'order', 'observation_lag_ns')} for item in document['attribution'].get('departures') or ()]
    return dict(classification=document['classification'], outcome=document['outcome'], reasons=document['reasons'], established=document['established'], proof_status=document['inputs']['proof_status'], proof_reasons=document['inputs']['proof_reasons'], gates=gates,
                offered_load=dict(verdict=document['validity']['verdict'], input=document['validity']['offered_input'], sockets=document['validity']['generator_sockets'], independent=sorted({str(item.get('code')) for item in document['validity']['independent_failures']}), unproven=document['validity']['unproven'],
                                  scheduled=offered.get('scheduled_total'), sent=offered.get('sent_total'), worst_ratio=offered.get('worst_ratio')),
                departures=departures, game_exit=document['attribution'].get('game_exit'), establishes_capacity=document['establishes_capacity'])


# ---- a whole search, through the real executor ---------------------------------------------------------

def identities_of(hosts, run_id):
    found = {}
    for role in ('game', 'bot'):
        run = hosts[role].runs[run_id]
        found[role] = {name: dict(item) for name, item in run.identity['processes'].items()}
    return found


class ScoredGuests(fake_run_guest.FakeRunGuests):
    """A fake guest whose finished runs leave the files a real run leaves, shaped by ``script(tree, trial)``. The controller sees only exported bytes."""

    def __init__(self, sim, script):
        super().__init__(sim)
        self.script = script
        self.trees = {}
        self.base = pathlib.Path(tempfile.mkdtemp(prefix='omega-scored-'))
        self.recorder_files = self._files

    def _tree(self, run):
        run_id = run.plan['run_id']
        if run_id in self.trees:
            return self.trees[run_id]
        argv = next(item for item in self.hosts['bot'].runs[run_id].plan['processes'] if item['name'] == 'bot')['argv']
        target, hold_s = int(fake_run_guest.option(argv, '--bots')), int(fake_run_guest.option(argv, '--hold-s'))
        tree = fx.Tree(self.base / run_id, target=target, hold_s=hold_s, identities=identities_of(self.hosts, run_id), game_inode=self.hosts['game'].runs[run_id].socket_rows)
        phase = run_id.split('-')[-3]
        tree.trial = dict(run_id=run_id, phase=phase, target=target, hold_s=hold_s)
        tree.guest_run = self.hosts['game'].runs[run_id]    # what a script needs to write what this run's supervisor would have
        self.script(tree, tree.trial)
        self.trees[run_id] = tree
        return tree

    def _files(self, role, run):
        if run.plan['run_id'] not in self.hosts['bot'].runs or run.plan['run_id'] not in self.hosts['game'].runs:
            return {}      # one role never started, so no recorder wrote anything worth scoring
        root = self._tree(run).root / role
        return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob('*')) if path.is_file()}

    def close(self):
        shutil.rmtree(str(self.base), True)


class ScoredSim(rf.RunSim):
    """A provisioned session with the real prover and the real scorer, the executor's own defaults. ``script`` decides what each run's recorders show."""

    def __init__(self, case, script=None, cap_s=None, **options):
        options.setdefault('telemetry_schema', FROZEN_SCHEMA)
        if cap_s is not None:
            options['cap_s'] = cap_s
        super().__init__(case, **options)
        (self.stack.root / 'manifest.json').write_text(json.dumps(self.manifest))     # what ``do_session.py freeze`` leaves in a real session directory
        (self.stack.root / 'manifest.sha256').write_text(self.sha + '\n')
        self.guests = ScoredGuests(self, script or (lambda tree, trial: None))
        case.addCleanup(self.guests.close)

    def executor(self, client=None, token=None, failpoint=None, policy=None, source_problems=None, guests=None, readiness_problems=None, adapter=None, **_):
        return rf.run_executor.RunExecutor(client or self.client, guests or self.guests, self.provider, self.manifest, self.sha, self.stack.root, token if token is not None else self.result.fencing_token, self.sleep, self.monotonic, self.clock.wall, adapter=adapter or rf.ScriptedAdapter(),
                                           policy=policy or rf.FAST_POLICY, failpoint=failpoint, source_problems=source_problems or (lambda: []), readiness_problems=readiness_problems)

    def outcomes(self):
        return [(row['trial']['phase'], row['trial']['target'], row['outcome']) for row in sorted(self.records(), key=lambda row: row['trial']['ordinal'])]

    def score_of(self, run_id):
        return cs.load_retained(self.run_dir(run_id) / 'score.json')


def supervisor_saw_an_oom_kill(tree, change=None):
    """For a whole search: the file this fake run's own supervisor would leave. Hold it to the identities the fake guest really sealed."""
    run = tree.guest_run
    identity = run.identity
    document = process_oom_document(dict(identity['processes']['game'], boot_id=identity['processes']['game']['boot_id']), supervisor=identity['supervisor'], sampler=identity['processes']['sampler'], invocation=identity['invocation_id'], unit=run.plan['unit'])
    document['run_id'] = run.plan['run_id']
    if change is not None:
        change(document)
    tree.path('game/process-oom.json').write_text(json.dumps(document))


def by_target(rules, default=None):
    """A script from (phase, target) or target to a change. A trial with no rule is left healthy."""
    def script(tree, trial):
        change = rules.get((trial['phase'], trial['target']), rules.get(trial['target'], default))
        if change is not None:
            change(tree)
    return script


def slow(tree):
    """A plain, unambiguous capacity failure: 10 percent of the window's Ticks over budget."""
    set_slow_ticks(tree, tree.timeline.hold_s * 3, 50_000_000)


def starved(tree):
    """A plain, unambiguous generator failure, with the server healthy."""
    tree.edit_frozen_bot(1, lambda row: row.update(sent=row['scheduled'] // 2))


def foggy(tree):
    """A plain, unambiguous evidence gap."""
    def edit(index, row):
        for item in row['procs']['game']['sockets']:
            item['drops'] = None
    tree.edit_sampler('game', edit)


def rebooted(tree):
    """A plain, unambiguous infrastructure failure, seen by the collector."""
    def edit(index, row):
        if row['clock']['mono_ns'] >= fx.to_game_mono(tree.timeline.start + 10 * NS):
            row['boot_id'] = 'another-boot'
    tree.edit_sampler('game', edit)
