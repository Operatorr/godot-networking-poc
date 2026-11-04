#!/usr/bin/env python3
"""Regenerate the retained offline fault timelines for handoff slice 2 (issue #65).

Every scenario runs on a scripted clock and a fake provider, so the output is byte-reproducible,
contains no credential and proves nothing about a live account. ``test_fault_evidence`` regenerates
it and compares it with the committed SHA256SUMS. Each timeline records attempted operations,
resource inventories, incidents and final statuses, and the checks asserted against them.

    python3 fault_evidence.py --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice2
"""
import argparse
import hashlib
import json
import pathlib
import sys

import cleanup_provider
import fault_harness
import fixture_support as fx
import manifest as manifest_mod
import registry
import registry_client
import registry_fixtures as rf
import session_clock

SESSION = 'do-cap-1v1g-20261030a'
SHORT = dict(cap_s=600, reserve_s=120, grace_s=100)


class Context:
    """The small part of ``unittest.TestCase`` the stack needs, outside a test run."""

    def __init__(self):
        self.cleanups = []

    def addCleanup(self, func, *args):
        self.cleanups.append((func, args))

    def assertLess(self, first, second, message=''):
        if not first < second:
            raise AssertionError(message)

    def close(self):
        for func, args in reversed(self.cleanups):
            func(*args)


def lost_controller_cleanup_by_c(stack, checks):
    _, _, _, ack, _ = stack.ready(SESSION, **SHORT)
    c, d = session_clock.parse(ack['cleanup_c_utc']), session_clock.parse(ack['deadline_d_utc'])
    stack.run_until(lambda: stack.closed(SESSION))
    first_delete = stack.provider.ops_named('delete_droplet')[0]['at']
    checks('first delete issued by C', first_delete <= c)
    checks('verified absent before D', stack.clock.wall_value < d)
    checks('no resource survives', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))
    checks('evidence stays visibly unknown', stack.registry.status(SESSION)['evidence']['status'] == 'unknown')


def api_outage_overdue_then_verified(stack, checks):
    _, _, _, ack, _ = stack.ready(SESSION, **SHORT)
    d = session_clock.parse(ack['deadline_d_utc'])
    rule = stack.provider.fail(rf.outage)
    while stack.clock.wall_value < d + 60:
        stack.step(1)
    overdue = [i for i in stack.registry.incidents(SESSION) if i['kind'] == 'cleanup-overdue']
    checks('one overdue incident is open after D', len(overdue) == 1 and overdue[0]['status'] == 'open')
    checks('nothing was deleted or called clean', stack.registry.status(SESSION)['overall'] == 'cleanup_overdue')
    stack.provider.faults.remove(rule)
    stack.run_until(lambda: stack.closed(SESSION))
    final = stack.registry.status(SESSION)
    checks('actual overrun is recorded', final['cleanup']['overrun_s'] >= 60)
    checks('the breach stays visible after cleanup', final['cleanup']['overdue'] is True)
    bursts = {}
    for attempt in stack.registry.attempts(SESSION):
        bursts[(attempt['resource_key'], attempt['sweep_seq'])] = bursts.get((attempt['resource_key'], attempt['sweep_seq']), 0) + 1
    checks('no burst exceeded six attempts', max(bursts.values()) <= 6)


def stale_controller_after_takeover(stack, checks):
    _, sha, token, _, _ = stack.ready(SESSION, **SHORT)
    stack.client.mutate('dispatch_run', 'dispatch-1', session_id=SESSION, run_id='run-1', fencing_token=token, manifest_sha256=sha, estimated_duration_s=30)
    other = stack.new_client('controller-b')
    new_token = other.acquire(SESSION, takeover=True)['fencing_token']
    refused = []
    for call in (lambda: stack.client.mutate('dispatch_run', 'dispatch-1', session_id=SESSION, run_id='run-1', fencing_token=token, manifest_sha256=sha, estimated_duration_s=30),
                 lambda: stack.client.mutate('dispatch_run', session_id=SESSION, run_id='run-2', fencing_token=token, manifest_sha256=sha, estimated_duration_s=30),
                 lambda: stack.client.mutate('request_cleanup', session_id=SESSION, fencing_token=token, reason='stale')):
        try:
            call()
        except registry_client.RegistryRejected as rejection:
            refused.append(rejection.code)
    checks('every stale request was refused', refused == ['stale_fencing_token'] * 3)
    checks('only the first run exists', [r['run_id'] for r in stack.registry.runs(SESSION)] == ['run-1'])
    checks('the active run is retained as interrupted', stack.registry.runs(SESSION)[0]['state'] == 'interrupted')
    checks('takeover paused the session', stack.registry.status(SESSION)['state'] == registry.PAUSED)
    other.mutate('request_cleanup', session_id=SESSION, fencing_token=new_token, reason='operator abort after takeover')
    stack.run_until(lambda: stack.closed(SESSION))


def rate_limit_then_auth_repair(stack, checks):
    stack.ready(SESSION, **SHORT)
    stack.provider.fail(lambda: cleanup_provider.ProviderRateLimited('429 too many requests', status=429, retry_after_s=45), times=1)
    stack.registry.operator_abort(SESSION, 'rate limit fixture')
    stack.watchdog.tick()
    before = len(stack.provider.ops)
    stack.step(44)
    checks('no request during the provider hold', len(stack.provider.ops) == before)
    rule = stack.provider.fail(rf.auth_failure)
    stack.step(40)
    kinds = {i['kind']: i['status'] for i in stack.registry.incidents(SESSION)}
    checks('auth failure is an open incident', kinds.get('provider-auth') == 'open')
    checks('auth failure is not cleanup success', stack.registry.status(SESSION)['state'] == registry.DELETING)
    stack.provider.faults.remove(rule)
    stack.run_until(lambda: stack.closed(SESSION))
    kinds = {i['kind']: i['status'] for i in stack.registry.incidents(SESSION)}
    checks('repair resolves it and cleanup completes', kinds.get('provider-auth') == 'resolved')


def ownership_refusal_preserves_unrelated(stack, checks):
    stack.provider.add_droplet('production-arena', ['production'])
    stack.provider.add_droplet('mgmt-1', ['omega-management'])
    _, _, _, _, ids = stack.ready(SESSION, **SHORT)
    droplet_id = ids['game'].split(':')[1]
    stack.provider.data['droplets'][droplet_id]['tags'] = ['someone-elses-tag']
    stack.registry.operator_abort(SESSION, 'ownership fixture')
    stack.step(60)
    checks('mismatched Droplet was never deleted', droplet_id in stack.provider.live_ids()['droplets']
           and not [o for o in stack.provider.ops_named('delete_droplet') if o['target'] == droplet_id])
    checks('closure is blocked', stack.registry.status(SESSION)['state'] == registry.DELETING)
    stack.registry.disown_resource(SESSION, ids['game'], 'fixture: verified as another owner')
    stack.run_until(lambda: stack.closed(SESSION))
    checks('closure is labelled as a disposition', stack.registry.status(SESSION)['overall'] == 'resources_verified_with_operator_disposition')
    checks('unrelated and management hosts survive', len(stack.provider.live_ids()['droplets']) == 3)


def backward_wall_clock_jump(stack, checks):
    _, _, _, ack, _ = stack.ready(SESSION, **SHORT)
    original = (ack['t0_utc'], ack['cleanup_c_utc'], ack['deadline_d_utc'])
    stack.step(10)
    stack.clock.jump_wall(-7200)
    stack.step(session_clock.parse(ack['cleanup_c_utc']) - stack.registry.peek_now())
    status = stack.registry.status(SESSION)
    checks('C arrived on monotonic time', status['state'] == registry.DELETING)
    checks('deadlines are unchanged', (status['t0_utc'], status['cleanup_c_utc'], status['deadline_d_utc']) == original)
    checks('the clock anomaly is recorded', [i['kind'] for i in stack.registry.incidents()] == ['clock-anomaly'])
    checks('registry reports unhealthy', stack.registry.health(SESSION)['registry']['healthy'] is False)


def ambiguous_and_late_create(stack, checks):
    _, _, token, _ = stack.armed(SESSION, **SHORT)
    tags = rf.fx_tags(SESSION)
    intent = SESSION + ':droplet:game'
    stack.client.mutate('begin_create', session_id=SESSION, intent_id=intent, fencing_token=token)
    stack.client.mutate('record_create_result', session_id=SESSION, intent_id=intent, outcome='ambiguous', note='client timeout')
    stack.registry.operator_abort(SESSION, 'ambiguous create fixture')
    stack.step(77)
    checks('no closure from elapsed time', not stack.closed(SESSION))
    checks('protection is untouched while the create is unresolved', not stack.provider.ops_named('delete_firewall', 'delete_tag'))
    late = stack.provider.add_droplet(SESSION + '-game', [tags['session'], tags['game']])
    stack.run_until(lambda: stack.closed(SESSION))
    checks('the late create was deleted', stack.provider.live_ids()['droplets'] == [])
    resource = next(r for r in stack.registry.status(SESSION)['resources'] if r['provider_id'] == late)
    checks('its exact id was discovered and retained', resource['source'] == 'discovered' and resource['status'] == 'absent')
    checks('the tags it recreated did not survive the clean receipt', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))
    checks('the receipt reads verified absent', stack.registry.status(SESSION)['cleanup']['outcome'] == registry.VERIFIED_ABSENT)


def pending_creates_hold_protection(stack, checks):
    _, _, token, _ = stack.armed(SESSION, **SHORT)
    tags = rf.fx_tags(SESSION)
    firewall = stack.client.guarded_create(SESSION, SESSION + ':firewall', token,
                                           lambda g: stack.provider.add_firewall(g['expected_name'], tags=g['expected_tags']), lambda g: None)
    stack.client.mutate('begin_create', session_id=SESSION, intent_id=SESSION + ':droplet:game', fencing_token=token)
    stack.client.mutate('begin_create', session_id=SESSION, intent_id=SESSION + ':tag:session', fencing_token=token)
    stack.registry.operator_abort(SESSION, 'droplet and tag requests outstanding')
    stack.step(35)
    checks('the firewall is still there at +35 s', firewall.split(':')[1] in stack.provider.live_ids()['firewalls'])
    checks('nothing protective was deleted', not stack.provider.ops_named('delete_firewall', 'delete_tag'))
    stack.step(300)
    checks('still nothing after minutes without evidence', not stack.provider.ops_named('delete_firewall', 'delete_tag'))
    stack.provider.add_tag(tags['session'])
    checks('closure has not happened', not stack.closed(SESSION))
    stack.provider.issue_receipt(SESSION + ':droplet:game#1')
    stack.run_until(lambda: stack.closed(SESSION))
    states = {i['intent_id']: i['state'] for i in stack.registry.status(SESSION)['intents']}
    checks('the receipt settled the Droplet create', states[SESSION + ':droplet:game'] == 'resolved_absent')
    checks('the late tag answered its intent', states[SESSION + ':tag:session'] == 'created')
    checks('no resource survives', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))


def delayed_original_create_gets_no_retry(stack, checks):
    _, _, token, _ = stack.armed(SESSION, **SHORT)
    intent = SESSION + ':droplet:game'
    find, create = fault_harness.find_existing(stack.provider, SESSION), fault_harness.create_for(stack.provider)
    grants, retries = [], []

    def still_processing(grant):
        grants.append(grant)
        raise TimeoutError('still being processed')

    try:
        stack.client.guarded_create(SESSION, intent, token, still_processing, find)
    except TimeoutError:
        pass
    refused = 0
    for _ in range(7):
        try:
            stack.client.guarded_create(SESSION, intent, token, retries.append, find)
        except registry_client.CreateUnresolved:
            refused += 1
        stack.step(10)
    checks('every empty listing was refused, including after the former 60 s bound', refused == 7)
    checks('the retry callback never ran', retries == [])
    original = create(grants[0])
    stack.step(5)
    key = stack.client.guarded_create(SESSION, intent, token, retries.append, find)
    checks('the original was adopted by its exact id', key == 'droplet:' + original)
    checks('one Droplet exists', stack.provider.live_ids()['droplets'] == [original])
    state = next(i for i in stack.registry.status(SESSION)['intents'] if i['intent_id'] == intent)
    checks('one request was granted', state['request_count'] == 1)
    stack.registry.operator_abort(SESSION, 'fixture finished')
    stack.run_until(lambda: stack.closed(SESSION))


def unresolved_create_blocks_clean_closure_past_d(stack, checks):
    _, _, token, ack = stack.armed(SESSION, **SHORT)
    d = session_clock.parse(ack['deadline_d_utc'])
    create = fault_harness.create_for(stack.provider)
    find = fault_harness.find_existing(stack.provider, SESSION)
    for suffix in ('tag:session', 'tag:game', 'tag:bot', 'droplet:bot'):
        stack.client.guarded_create(SESSION, SESSION + ':' + suffix, token, create, find)
    stack.client.mutate('begin_create', session_id=SESSION, intent_id=SESSION + ':droplet:game', fencing_token=token)
    stack.registry.operator_abort(SESSION, 'the game Droplet request has no known outcome')
    stack.step(20)
    checks('the known Droplet was deleted at once', stack.provider.live_ids()['droplets'] == [])
    checks('its tags stay while the other request is unresolved', len(stack.provider.live_ids()['tags']) == 3)
    while stack.clock.wall_value < d + 30:
        stack.step(1)
    status = stack.registry.status(SESSION)
    checks('the session stays open past D', status['state'] == registry.DELETING)
    checks('overdue is reported, not success', status['overall'] == 'cleanup_overdue')
    checks('the unresolved request is named', [u['create_request_ref'] for u in status['cleanup']['unresolved_creates']] == [SESSION + ':droplet:game#1'])
    stack.provider.issue_receipt(SESSION + ':droplet:game#1')
    stack.run_until(lambda: stack.closed(SESSION))
    final = stack.registry.status(SESSION)
    checks('the receipt let it finish', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))
    checks('the breach stays visible', final['cleanup']['overdue'] is True and final['cleanup']['overrun_s'] > 0)


def reboot_with_rtc_behind_fails_closed(stack, checks):
    _, sha, token, _, _ = stack.ready(SESSION, **SHORT)
    stack.step(50)
    stack.registry.renew_control(SESSION, token)
    stack.step(50)
    stack.restart_watchdog(reboot=True, downtime_s=600, rtc_error_s=-86400)     # really t0+700, past D
    stack.watchdog.tick()
    status = stack.registry.status(SESSION)
    checks('cleanup started on the unverifiable clock', status['cleanup']['reason'] == registry.CLOCK_UNVERIFIABLE_REASON)
    checks('overdue is reported though D may not have passed', status['cleanup']['overdue'] is True)
    checks('the deadline is labelled uncertain', status['cleanup']['deadline_uncertain'] is True)
    refused = []
    for call in (lambda: stack.registry.renew_control(SESSION, token),
                 lambda: stack.registry.dispatch_run(SESSION, 'after-reboot', token, sha, 60)):
        try:
            call()
        except registry.Rejection as rejection:
            refused.append(rejection.code)
    checks('no renewal and no work', refused == ['clock_unverifiable'] * 2)
    checks('no run was dispatched', stack.registry.runs(SESSION) == [])
    stack.run_until(lambda: stack.closed(SESSION))
    status = stack.registry.status(SESSION)
    checks('resources are verified absent', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))
    checks('the recorded overrun is labelled a lower bound', status['cleanup']['overrun_is_lower_bound'] is True)
    checks('the clock incident stays open without verified time', [i['status'] for i in stack.registry.incidents() if i['kind'] == 'clock-unverifiable'] == ['open'])


def recovery_deadline_survives_reconnect(stack, checks):
    _, _, token, _, _ = stack.ready(SESSION, **SHORT)
    stack.registry.begin_collection(SESSION, token)
    recovery = stack.registry.begin_evidence_recovery(SESSION, token)
    deadline = session_clock.parse(recovery['recovery_deadline_utc'])
    stack.step(50)
    stack.registry.begin_collection(SESSION, token)
    checks('reconnecting returned to collecting', stack.registry.status(SESSION)['state'] == registry.COLLECTING)
    while stack.clock.wall_value < deadline:
        stack.step(1)
    status = stack.registry.status(SESSION)
    checks('the episode ended on time without the controller', status['state'] == registry.DELETING)
    checks('the reason names the recovery bound', status['cleanup']['reason'] == 'evidence_recovery_expired')
    checks('cleanup intent is not later than the deadline', session_clock.parse(status['cleanup']['requested_at']) <= deadline)
    stack.run_until(lambda: stack.closed(SESSION))


def recovery_lasts_until_c_while_ownership_is_prepared(stack, checks):
    _, _, _, ack, _ = stack.ready(SESSION, **SHORT)
    c = session_clock.parse(ack['cleanup_c_utc'])
    while stack.clock.wall_value < c - 60:
        stack.step(1)
    token = stack.client.acquire(SESSION, takeover=True)['fencing_token']
    stack.registry.begin_collection(SESSION, token)
    first_failure = stack.clock.wall_value
    recovery = stack.registry.begin_evidence_recovery(SESSION, token)
    checks('the episode is exactly min(first_failure + grace, C)',
           session_clock.parse(recovery['recovery_deadline_utc']) == min(first_failure + SHORT['grace_s'], c) == c)
    while stack.clock.wall_value < c - 1:
        stack.step(1)
    status = stack.registry.status(SESSION)
    checks('recovery is still active one second before C', status['state'] == registry.EVIDENCE_RECOVERY)
    checks('ownership was prepared meanwhile', len(stack.provider.ops_named('get_droplet')) == 2)
    checks('no delete was issued during recovery', not stack.provider.ops_named('delete_droplet', 'delete_firewall', 'delete_tag'))
    checks('the evidence hosts are intact', len(stack.provider.live_ids()['droplets']) == 2)
    stack.step(1)
    first = stack.provider.ops_named('delete_droplet')[0]['at']
    checks('the first delete was issued at C', first == c)
    stack.run_until(lambda: stack.closed(SESSION))
    checks('no resource survives', stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))


def five_sessions_with_slow_requests_delete_by_c(stack, checks):
    names = ['do-cap-' + c + '-delayed' for c in 'abcde']
    acks = [stack.ready(name, **SHORT)[3] for name in names]
    c = session_clock.parse(acks[0]['cleanup_c_utc'])
    checks('all five share one C', {a['cleanup_c_utc'] for a in acks} == {acks[0]['cleanup_c_utc']})
    stack.executor.run(stack, c - stack.clock.wall_value)
    first = {name: min(session_clock.parse(a['started_at']) for a in stack.registry.attempts(name) if a['op'] == 'delete_droplet') for name in names}
    checks('every session issued its first delete', set(first) == set(names))
    checks('every first delete was issued by C', max(first.values()) <= c)
    checks('no request failed', not [a for name in names for a in stack.registry.attempts(name) if a['result'] == 'error'])
    stack.executor.run(stack, 1500)
    checks('every session verified absent', all(stack.closed(name) for name in names) and stack.provider.live_ids() == dict(droplets=[], firewalls=[], tags=[]))


def capacity_rejected_before_create_behind_hung_slots(stack, checks):
    hung = ['do-cap-a-hung', 'do-cap-b-hung', 'do-cap-c-hung']
    for name in hung:
        stack.ready(name)
    due = ['do-cap-z-due-%d' % i for i in range(stack.watchdog.deadline_reserved_slots)]
    acks = [stack.ready(name, **SHORT)[3] for name in due]
    c = session_clock.parse(acks[0]['cleanup_c_utc'])
    extra = 'do-cap-z-over-capacity'
    manifest, sha, token = stack.registered(extra, **SHORT)
    stack.watchdog.tick()
    refused = None
    try:
        stack.client.arm(extra, manifest, sha, token)
    except registry_client.RegistryRejected as rejection:
        refused = rejection
    checks('the extra session was refused explicitly', refused is not None and refused.code == 'deadline_capacity_exceeded')
    checks('the refusal says when it would fit', refused.details['retry_after_s'] > 0)
    checks('it has no deadline', stack.registry.status(extra)['t0_utc'] is None)
    checks('nothing was created for it', not [d for d in stack.provider.data['droplets'].values() if extra in d['name']])
    for name in hung:
        stack.registry.operator_abort(name, 'provider calls hang')
    stack.executor.hold_sessions = set(hung)
    stack.step(1)
    while stack.clock.wall_value < c:
        stack.step(1)
    deletes = {a['session_id']: session_clock.parse(a['started_at']) for name in due for a in stack.registry.attempts(name) if a['op'] == 'delete_droplet'}
    checks('every due session deleted by C behind hung slots', set(deletes) == set(due) and max(deletes.values()) <= c)
    checks('hung sessions deleted nothing unread', not [a for name in hung for a in stack.registry.attempts(name) if a['op'] == 'delete_droplet'])


def fairness_with_a_hung_session(stack, checks):
    stack.executor.hold_sessions = {'do-cap-aaa-hung'}
    stack.ready('do-cap-aaa-hung', **SHORT)
    stack.ready('do-cap-bbb-healthy', **SHORT)
    stack.registry.operator_abort('do-cap-aaa-hung', 'hung fixture')
    stack.registry.operator_abort('do-cap-bbb-healthy', 'healthy fixture')
    elapsed = stack.run_until(lambda: stack.closed('do-cap-bbb-healthy'))
    checks('the healthy session closed promptly', elapsed <= 120)
    checks('the hung session is still open', not stack.closed('do-cap-aaa-hung'))
    checks('the hung session holds at most its share', stack.watchdog.ledger.in_flight_counts().get('do-cap-aaa-hung', 0) <= 2)


def watchdog_restart_mid_burst(stack, checks):
    _, _, _, _, ids = stack.ready(SESSION, **SHORT)
    rule = stack.provider.fail(rf.outage, op='get_droplet')
    stack.registry.operator_abort(SESSION, 'restart fixture')
    stack.step(10)
    sweep = next(r for r in stack.registry.resources(SESSION) if r['resource_key'] == ids['game'])['burst_sweep']
    stack.restart_watchdog()
    stack.step(60)
    first = [a for a in stack.registry.attempts(SESSION, ids['game']) if a['sweep_seq'] == sweep]
    checks('the burst resumed, not stacked', len(first) == 6)
    stack.provider.faults.remove(rule)
    stack.run_until(lambda: stack.closed(SESSION))
    checks('journal chain is intact', stack.registry.verify_journal()['valid'])


SCENARIOS = (lost_controller_cleanup_by_c, api_outage_overdue_then_verified, stale_controller_after_takeover,
             rate_limit_then_auth_repair, ownership_refusal_preserves_unrelated, backward_wall_clock_jump,
             ambiguous_and_late_create, fairness_with_a_hung_session, watchdog_restart_mid_burst,
             pending_creates_hold_protection, delayed_original_create_gets_no_retry, reboot_with_rtc_behind_fails_closed,
             recovery_deadline_survives_reconnect, recovery_lasts_until_c_while_ownership_is_prepared,
             unresolved_create_blocks_clean_closure_past_d, five_sessions_with_slow_requests_delete_by_c,
             capacity_rejected_before_create_behind_hung_slots)


def record(stack):
    sessions = [s['session_id'] for s in stack.registry.list_sessions()]
    return dict(
        journal=[dict(seq=e['seq'], at=e['at'], session_id=e['session_id'], kind=e['kind'], data=e['data'])
                 for e in stack.registry.journal()],
        journal_verification=stack.registry.verify_journal(),
        attempted_operations=[dict(op=o['op'], target=o['target'], at=session_clock.iso(o['at'])) for o in stack.provider.ops],
        provider_inventory_at_end=stack.provider.live_ids(),
        sessions={s: stack.registry.status(s) for s in sessions},
        incidents=[stack.registry.incident_report(i['incident_id']) for i in stack.registry.incidents()])


def run_scenario(scenario):
    context = Context()
    try:
        executor = None
        if scenario is fairness_with_a_hung_session:
            executor = fx.DeferredExecutor(hold_sessions=set())
        elif scenario is capacity_rejected_before_create_behind_hung_slots:
            executor = fx.DeferredExecutor()
        elif scenario is five_sessions_with_slow_requests_delete_by_c:
            executor = fx.TimedExecutor()
        stack = rf.Stack(context, executor=executor)
        if isinstance(executor, fx.TimedExecutor):
            executor.clock = stack.clock
        results = []
        scenario(stack, lambda name, passed: results.append(dict(check=name, passed=bool(passed))))
        failed = [r['check'] for r in results if not r['passed']]
        if failed:
            raise AssertionError(scenario.__name__ + ' failed: ' + ', '.join(failed))
        return dict(scenario=scenario.__name__, clock='scripted', provider='fake', checks=results, **record(stack))
    finally:
        context.close()


def generate(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summary = ['# Slice 2 offline fault timelines', '',
               'Generated by `scripts/do_session/fault_evidence.py` on a scripted clock and a fake provider: no account, '
               'network or credential was involved, and none of this is a capacity or live-provider result. '
               '`test_fault_evidence` regenerates the files and compares them with `SHA256SUMS`.', '',
               '| Timeline | Checks passed | Journal events | Attempted operations | Incidents |', '| --- | ---: | ---: | ---: | ---: |']
    sums = []
    for scenario in SCENARIOS:
        result = run_scenario(scenario)
        hits = manifest_mod.scan_for_secrets(result)
        if hits:
            raise AssertionError('credential-like value in ' + scenario.__name__ + ': ' + ', '.join(hits))
        text = json.dumps(result, indent=1, sort_keys=True) + '\n'
        name = scenario.__name__ + '.json'
        (out / name).write_text(text, encoding='utf-8')
        sums.append(hashlib.sha256(text.encode('utf-8')).hexdigest() + '  ' + name)
        summary.append('| [%s](%s) | %d/%d | %d | %d | %d |' % (scenario.__name__, name, sum(1 for c in result['checks'] if c['passed']),
                                                                len(result['checks']), len(result['journal']),
                                                                len(result['attempted_operations']), len(result['incidents'])))
    (out / 'README.md').write_text('\n'.join(summary) + '\n', encoding='utf-8')
    sums.append(hashlib.sha256((out / 'README.md').read_bytes()).hexdigest() + '  README.md')
    (out / 'SHA256SUMS').write_text('\n'.join(sorted(sums, key=lambda line: line.split()[1])) + '\n', encoding='utf-8')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True)
    generate(parser.parse_args(argv).out)
    return 0


if __name__ == '__main__':
    sys.exit(main())
