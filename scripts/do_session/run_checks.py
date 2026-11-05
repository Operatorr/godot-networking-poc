"""Whether a host may run, and what a run's execution facts allow to be said about it. Pure, like ``readiness``.

A missing fact is a failure, never a pass. Nothing here scores a measurement. It sorts execution facts into three kinds:

  infrastructure   the run says nothing about capacity, and the batch stops
  generator        the swarm itself failed, which is invalid offered load unless the game failed too
  game             the game process failed; only a scorer with its own evidence can call that a capacity failure

``capacity_scorer`` (handoff slice 6, issue #69) sits behind ``apply_scorer``. Without a scorer, as in fixtures with no recorder files, a
finished run is INCONCLUSIVE, which stops the batch and establishes nothing.
"""
import guest_runner
import search

ALLOWED_QDISCS = frozenset(('noqueue', 'mq', 'fq_codel', 'fq', 'pfifo_fast', 'pfifo'))
MIN_RUN_DISK_BYTES = 1024 ** 3
SAMPLER_GRACE_INTERVALS = 5
INFRASTRUCTURE, GENERATOR, GAME = 'infrastructure', 'generator', 'game'
SCORER_OUTCOMES = (search.PASS, search.FAIL, search.INVALID_LOAD, search.INFRASTRUCTURE_FAILURE, search.INCONCLUSIVE)


def impairment_problems(facts):
    facts = facts if isinstance(facts, dict) else {}
    if facts.get('available') is not True:
        return ['network impairment state could not be read']
    problems = []
    kinds = facts.get('qdisc_kinds')
    if not isinstance(kinds, list) or not kinds:
        return ['no qdisc state was reported']
    for kind in kinds:
        if kind not in ALLOWED_QDISCS:
            problems.append('qdisc %s is not a cleared state' % kind)
    if facts.get('filter_count') != 0:
        problems.append('traffic filters remain: %s' % facts.get('filter_count'))
    return problems


def prior_identities(ledger):
    """Every process and socket identity this host has already used."""
    pids, sockets, units = set(), set(), set()
    for entry in ledger if isinstance(ledger, list) else ():
        if entry.get('invocation_id'):
            units.add(entry['invocation_id'])
        for item in list((entry.get('processes') or {}).values()) + ([entry['supervisor']] if entry.get('supervisor') else []):
            pids.add((item.get('pid'), item.get('start_id'), item.get('boot_id')))
        sockets.update(entry.get('socket_inodes') or ())
    return pids, sockets, units


def host_problems(plan, facts, expected_boot_id, expected_runner_sha256, source_sha=None):
    """One host just before anything is launched on it."""
    facts = facts if isinstance(facts, dict) else {}
    problems = []
    if facts.get('boot_id') != expected_boot_id or not expected_boot_id:
        problems.append('host boot identity changed: %s' % facts.get('boot_id'))
    if facts.get('runner_sha256') != expected_runner_sha256:
        problems.append('the runner on the host differs from this controller\'s')
    reported = {item.get('path'): item for item in facts.get('files') or []}
    for expected in plan['verify_files']:
        actual = reported.get(expected['path']) or {}
        if actual.get('sha256') != expected['sha256']:
            problems.append('%s does not have its frozen hash' % expected['path'])
        if expected['role'] == 'program' and actual.get('executable') is not True:
            problems.append('%s is not executable' % expected['path'])
    leftovers = facts.get('leftovers')
    if not isinstance(leftovers, list):
        problems.append('the process table could not be read')
    elif leftovers:
        problems.append('processes remain from an earlier start: %s' % sorted(item.get('pid') for item in leftovers))
    ports = facts.get('ports_free') if isinstance(facts.get('ports_free'), dict) else {}
    for item in plan['ports']:
        name = '%s/%d' % (item['protocol'], item['port'])
        if ports.get(name) is not True:
            problems.append('port %s still holds a socket' % name)
    problems += impairment_problems(facts.get('impairment'))
    if plan['unit_mode'] == guest_runner.SYSTEMD:
        units = facts.get('units')
        if not isinstance(units, list):
            problems.append('the unit list could not be read')
        elif units:
            problems.append('units remain: %s' % ', '.join(sorted(units)))
    if facts.get('active') is not None:
        problems.append('another run is active: %s' % (facts['active'] or {}).get('run_id'))
    if not isinstance(facts.get('disk_free_bytes'), int) or facts['disk_free_bytes'] < MIN_RUN_DISK_BYTES:
        problems.append('too little disk is free for a run: %s bytes' % facts.get('disk_free_bytes'))
    if facts.get('run_dir_exists') is not False:
        problems.append('the run directory already exists')
    fence = facts.get('fence') if isinstance(facts.get('fence'), dict) else {}
    if fence.get('token') != plan['fencing_token'] or fence.get('session_id') != plan['session_id']:
        problems.append('the host fence does not name this controller')
    if source_sha is not None:
        source = facts.get('source') or {}
        if source.get('head') != source_sha or source.get('clean') is not True:
            problems.append('the source on the host is not the frozen clean revision')
    return problems


def launch_problems(plan, summary, ledger):
    """A start that returned. Every process must be new, with no identity this host has used before."""
    summary = summary if isinstance(summary, dict) else {}
    problems = []
    pids, _, units = prior_identities(ledger)
    supervisor = summary.get('supervisor') or {}
    processes = summary.get('processes') if isinstance(summary.get('processes'), dict) else {}
    for name in [plan['processes'][0]['name'], 'sampler']:
        item = processes.get(name)
        if not isinstance(item, dict) or not item.get('start_id') or not item.get('boot_id'):
            problems.append('%s has no process identity' % name)
        elif (item.get('pid'), item.get('start_id'), item.get('boot_id')) in pids:
            problems.append('%s has the identity of an earlier process' % name)
    if not supervisor.get('start_id'):
        problems.append('the supervisor has no process identity')
    if plan['unit_mode'] == guest_runner.SYSTEMD:
        invocation = summary.get('invocation_id')
        if not invocation:
            problems.append('the unit has no invocation identity')
        elif invocation in units:
            problems.append('the unit invocation was already used by an earlier run')
    return problems


def socket_problems(plan, summary, ledger, require_counters):
    """The game's socket must be new, owned by this exact process, and its counter must never move backward."""
    if plan.get('watch_socket_port') is None:
        return []
    summary = summary if isinstance(summary, dict) else {}
    socket_view = summary.get('socket') if isinstance(summary.get('socket'), dict) else None
    if socket_view is None:
        return ['the game socket was never observed']
    _, seen, _ = prior_identities(ledger)
    first, last = socket_view.get('first') or {}, socket_view.get('last') or {}
    primary = (summary.get('processes') or {}).get(plan['processes'][0]['name']) or {}
    problems = []
    if first.get('inode') in seen or last.get('inode') in seen:
        problems.append('the game socket has the identity of an earlier run')
    for row in (first, last):
        if row.get('pid') != primary.get('pid') or row.get('start_id') != primary.get('start_id') or row.get('boot_id') != primary.get('boot_id'):
            problems.append('a socket counter row belongs to a different process')
            break
    if first.get('inode') != last.get('inode'):
        problems.append('the game socket changed during the run: counters cannot be compared')
    if require_counters:
        if not isinstance(first.get('drops'), int) or not isinstance(last.get('drops'), int):
            problems.append('the game socket has no drop counter')
        elif last['drops'] < first['drops']:
            problems.append('the game socket counter moved backward')
    return problems


def _exit_of(summary, name):
    return ((summary.get('result') or {}).get('processes') or {}).get(name)


def _sampler_problems(plan, summary):
    """A run that ended within a few sampling intervals could not have samples, and its reason for ending is on record already."""
    role, problems = plan['role'], []
    sampler = summary.get('sampler') or {}
    elapsed = (summary.get('result') or {}).get('elapsed_s')
    long_enough = not isinstance(elapsed, (int, float)) or elapsed >= SAMPLER_GRACE_INTERVALS * plan.get('sampler_interval_s', 1)
    if long_enough and (not isinstance(sampler.get('rows'), int) or sampler['rows'] < 2):
        problems.append('%s sampler left no samples' % role)
    if (summary.get('result') or {}).get('sampler_exited_early'):
        problems.append('%s sampler died during the run' % role)
    return problems


def seal_problems(plan, sealed):
    """What the sealed tree proves about the host after the run."""
    role = plan['role']
    seal = (sealed or {}).get('seal') or {}
    final = seal.get('final') or {}
    problems = []
    if not sealed or sealed.get('sealed') is not True or not sealed.get('seal_sha256'):
        return ['%s run directory was not sealed' % role]
    leftovers = final.get('leftovers')
    if not isinstance(leftovers, list) or leftovers:
        problems.append('%s still has processes after the run: %s' % (role, leftovers))
    ports = final.get('ports_free') if isinstance(final.get('ports_free'), dict) else {}
    for item in plan['ports']:
        if ports.get('%s/%d' % (item['protocol'], item['port'])) is not True:
            problems.append('%s still holds %s/%d after the run' % (role, item['protocol'], item['port']))
    problems += ['%s %s' % (role, problem) for problem in impairment_problems(final.get('impairment'))]
    # A process that died or was stopped explains its own missing output, and that reason is already on record.
    primary = _exit_of(sealed, plan['processes'][0]['name']) or {}
    wanted = list(plan.get('required_on_clean_exit') or ()) if primary.get('returncode') in plan['completed_exit_codes'] else []
    present = {item.get('path') for item in seal.get('files') or []}
    for name in wanted:
        if name not in present:
            problems.append('%s evidence %s is missing' % (role, name))
    return problems


def execution_problems(plans, summaries, sealed, ledgers, require_counters=True, interrupted=False):
    """Sort what happened to the processes. Reasons stay separate, because the kinds decide different things."""
    found = {INFRASTRUCTURE: [], GENERATOR: [], GAME: []}
    for role in ('game', 'bot'):
        plan, summary = plans[role], summaries.get(role) or {}
        found[INFRASTRUCTURE] += launch_problems(plan, summary, ledgers.get(role))
        found[INFRASTRUCTURE] += _sampler_problems(plan, summary)
        found[INFRASTRUCTURE] += seal_problems(plan, sealed.get(role))
    found[INFRASTRUCTURE] += socket_problems(plans['game'], summaries.get('game') or {}, ledgers.get('game'), require_counters)
    game, bot = summaries.get('game') or {}, summaries.get('bot') or {}
    bot_exit, game_exit = _exit_of(bot, 'bot'), _exit_of(game, 'game')
    if bot_exit is None:
        found[GENERATOR].append('the swarm left no exit record')
    elif (bot.get('result') or {}).get('stop_reason') == 'bound_exhausted':
        found[GENERATOR].append('the swarm overran its bound and was stopped')
    elif bot_exit.get('returncode') not in plans['bot']['completed_exit_codes']:
        found[GENERATOR].append('the swarm exited %s signal %s' % (bot_exit.get('returncode'), bot_exit.get('signal')))
    if game_exit is None:
        found[GAME].append('the game left no exit record')
    elif (game.get('result') or {}).get('stop_reason') == 'primary_exited':
        found[GAME].append('the game process ended before the swarm finished: exit %s signal %s' % (game_exit.get('returncode'), game_exit.get('signal')))
    elif (game.get('result') or {}).get('stop_reason') == 'bound_exhausted':
        found[GAME].append('the game outlived its bound and was stopped')
    return found


def disposition(problems):
    """What execution alone settles, or that a scorer must look. A timeout or a crash alone is never called capacity."""
    infrastructure, generator, game = problems[INFRASTRUCTURE], problems[GENERATOR], problems[GAME]
    if infrastructure:
        return dict(outcome=search.INFRASTRUCTURE_FAILURE, scorable=False, reasons=list(infrastructure))
    overran = any('overran' in problem for problem in generator)
    if overran:
        return dict(outcome=search.INCONCLUSIVE, scorable=False, reasons=list(generator) + list(game))
    if generator and not game:
        return dict(outcome=search.INVALID_LOAD, scorable=False, reasons=list(generator))
    return dict(outcome=None, scorable=True, reasons=list(generator) + list(game), generator_failed=bool(generator), game_failed=bool(game))


def window_reasons(proof):
    """The window proof's answer as plain reasons, for a verdict record. Nothing here turns it into an outcome."""
    if not isinstance(proof, dict):
        return []
    codes = sorted({str(item.get('code')) for item in proof.get('reasons') or [] if isinstance(item, dict)})
    return ['window proof: %s%s' % (proof.get('status'), ' (%s)' % ', '.join(str(code) for code in codes) if codes else '')]


def apply_scorer(settled, classification, proof=None):
    """Hold a scorer's answer against the execution facts and the window proof. Refusing it is never a pass. It becomes INCONCLUSIVE, with the reason.

    ``proof`` is ``measurement_window.prove``'s document. It is None only for fixtures that run no prover. A PASS needs a complete
    window; a capacity failure can precede a full hold, but it cannot stand on a generator the proof shows to have failed unless the scorer names the server as the cause.
    """
    if not settled['scorable']:
        return dict(outcome=settled['outcome'], reasons=settled['reasons'] + window_reasons(proof), scored=False)
    if classification is None:
        return dict(outcome=search.INCONCLUSIVE, reasons=['no reviewed scorer is available: this run establishes nothing'] + settled['reasons'] + window_reasons(proof), scored=False)
    outcome = classification.get('outcome') if isinstance(classification, dict) else None
    reason = None
    if outcome not in SCORER_OUTCOMES:
        reason = 'the scorer returned an unknown outcome'
    elif not isinstance(classification.get('evidence_ref'), str) or not classification['evidence_ref'].strip():
        reason = 'the scorer named no evidence'
    elif outcome == search.PASS and (settled['generator_failed'] or settled['game_failed']):
        reason = 'a PASS cannot stand on a run whose processes failed'
    elif outcome == search.FAIL and settled['generator_failed'] and classification.get('generator_failure_attributed_to_server') is not True:
        reason = 'a capacity failure with a failed generator needs the server named as the cause'
    elif proof is not None and outcome == search.PASS and proof.get('status') != 'complete':
        reason = 'a PASS needs a proven common window'
    elif (proof is not None and outcome == search.FAIL and classification.get('generator_failure_attributed_to_server') is not True
          and any(isinstance(item, dict) and item.get('category') == 'generator' for item in proof.get('reasons') or [])):
        reason = 'a capacity failure over a generator the window proof shows failing needs the server named as the cause'
    if reason is not None:
        return dict(outcome=search.INCONCLUSIVE, reasons=[reason] + settled['reasons'] + window_reasons(proof), scored=False)
    return dict(outcome=outcome, reasons=list(classification.get('reasons') or []), scored=True, evidence_ref=classification['evidence_ref'],
                scorer=classification.get('scorer'))


def finished_naturally(plans, summaries):
    """After an interruption: did the workload end by itself, so that no part of it depended on the lost controller?

    The swarm must have reached its own end, and the game must have been stopped after that or still have run. A stop that
    reached a live swarm means the measurement was cut, and nothing can be claimed for it.
    """
    bot, game = summaries.get('bot') or {}, summaries.get('game') or {}
    bot_exit = _exit_of(bot, 'bot')
    return (bot_exit is not None and 'bot' in plans and bot_exit.get('returncode') in plans['bot']['completed_exit_codes']
            and (bot.get('result') or {}).get('stop_reason') == 'primary_exited'
            and (game.get('result') or {}).get('stop_reason') not in (None, 'primary_exited', 'bound_exhausted'))


def interrupted_outcome(plans, summaries, expected_boots):
    """What an interruption does not excuse. Returns a stopping outcome only for a failure the retained evidence itself shows.

    The side effects of being cut short, such as a missing report, say nothing, so they stay INCOMPLETE. A host that rebooted,
    a sampler that died by itself or a swarm that crashed by itself are facts about the environment, and resuming past
    them would hide them.
    """
    reasons = []
    for role in ('game', 'bot'):
        summary = summaries.get(role) or {}
        processes = summary.get('processes') or {}
        boots = {item.get('boot_id') for item in processes.values() if item.get('boot_id')}
        if boots and boots != {expected_boots.get(role)}:
            reasons.append('%s host rebooted: %s' % (role, sorted(boots)))
        if (summary.get('result') or {}).get('sampler_exited_early'):
            reasons.append('%s sampler died during the run' % role)
    if reasons:
        return dict(outcome=search.INFRASTRUCTURE_FAILURE, reasons=reasons)
    bot, game = summaries.get('bot') or {}, summaries.get('game') or {}
    bot_exit, game_stop = _exit_of(bot, 'bot'), (game.get('result') or {}).get('stop_reason')
    completed = (plans.get('bot') or {}).get('completed_exit_codes', (0,))
    if (bot_exit is not None and (bot.get('result') or {}).get('stop_reason') == 'primary_exited' and bot_exit.get('returncode') not in completed
            and game_stop != 'primary_exited'):
        return dict(outcome=search.INVALID_LOAD, reasons=['the swarm crashed by itself: exit %s signal %s' % (bot_exit.get('returncode'), bot_exit.get('signal'))])
    return None
