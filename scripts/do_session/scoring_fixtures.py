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
import measurement_fixtures as fx
import measurement_window as mw
import run_fixtures as rf

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
    """The swarm gave up before publishing a window. Each shard is left as a real one leaves it: joined bots, a drain, a footer, and no window rows."""
    timeline = tree.timeline
    authenticated = timeline.target if authenticated is None else authenticated

    def window(document):
        document.update(status='not_established', reason=reason, final_auth_ns=None, barrier_ns=None, start_ns=None, end_ns=None, lost_after_auth=0, lost_rows=[], authenticated_at_end=authenticated)
        for ack in document['acks']:
            ack.update(observed_ns=None, start_ack_ns=None, end_ack_ns=None)
    tree.edit_json('bot/swarm/window.json', window)

    def coordinator(rows):
        rows[:] = [row for row in rows if row.get('k') not in ('window_published', 'barrier', 'drain_requested')]
        for index, row in enumerate(rows):
            row['seq'] = index
        rows[-1]['status'] = 'not_established'
    tree.edit_rows('bot/swarm/coordinator.ndjson', coordinator)
    for shard in range(timeline.threads):
        def change(rows):
            rows[:] = [row for row in rows if row.get('k') not in ('window_observed', 'ack_start', 'ack_end', 'freeze', 'drain_start')]
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

