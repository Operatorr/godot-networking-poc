#!/usr/bin/env python3
"""Regenerate the retained offline provisioning timelines for handoff slice 3 (issue #66).

Each scenario runs the real adapters, registry and watchdog against a fake DigitalOcean account and fake guests on a
scripted clock. The output is byte-reproducible, holds no credential and proves nothing about a live account.
``test_provision_fault_evidence`` regenerates it and compares it with the committed SHA256SUMS.

    python3 provision_fault_evidence.py --out ../../docs/netcode/perf-notes/digitalocean-capacity/offline-faults/slice3
"""
import argparse
import hashlib
import json
import pathlib
import sys

import fault_evidence
import manifest as manifest_mod
import provision_fixtures as pf
import provisioner
import registry
import registry_client
import session_access
import session_clock

FAST = provisioner.Policy(reconcile_observe_s=30.0, firewall_apply_wait_s=30.0, firewall_update_attempts=2, assign_attempts=2)
NEW_ADDRESS = '198.51.100.200/32'


def finish(sim, result, evidence='complete'):
    sim.client.mutate('record_evidence', session_id=sim.session_id, fencing_token=result.fencing_token, status=evidence, ref='offline-fixture')


def ready_pair_then_clean_close(sim, checks):
    result = sim.run()
    checks('pair reached ready', result.status == provisioner.READY)
    checks('two droplet creates, one firewall, three tags', (len(sim.creates('/v2/droplets')), len(sim.creates('/v2/firewalls')), len(sim.creates('/v2/tags'))) == (2, 1, 3))
    checks('final firewall reached succeeded with the exact bot address', sim.provider.get_firewall(result.firewall_id)['status'] == 'succeeded')
    finish(sim, result)
    sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='batch finished')
    final = sim.drive_cleanup()
    checks('only then does the session read clean', final['overall'] == 'clean')
    checks('every owned droplet is gone', sim.session_droplets() == [])
    checks('unrelated resources survive', sim.unrelated_intact() and sim.session_mutation_targets_only())


def wrong_facts_create_nothing(sim, checks):
    next(s for s in sim.account.sizes if s['slug'] == 's-1vcpu-1gb-amd')['price_hourly'] = 0.5
    sim.account.account['droplet_limit'] = 2
    sim.account.images[247516813]['public'] = False
    result = sim.run()
    checks('refused before t0', (result.status, result.code) == (provisioner.REJECTED, 'preflight_refused'))
    checks('every reason is listed', all(word in result.detail for word in ('price', 'quota', 'official')))
    checks('no provider mutation was attempted', sim.account.mutations() == [])


def missing_authorization_sends_nothing(sim, checks):
    packet = dict(sim.packet, max_pairs=2, not_after_utc=session_clock.iso(sim.clock.wall() - 1))
    result = sim.run(packet=packet)
    checks('refused', (result.status, result.code) == (provisioner.REJECTED, 'authorization_refused'))
    checks('not even a provider read happened', sim.account.requests == [])
    checks('the session was never registered', sim.stack.registry.list_sessions() == [])


def partial_pair_cleans_only_owned(sim, checks):
    original = sim.account._route_droplets

    def refuse_bot(method, parts, query, payload):
        if method == 'POST' and payload['name'].endswith('-bot'):
            return sim.account._reply(422, dict(id='unprocessable_entity', message='fixture: no capacity'))
        return original(method, parts, query, payload)
    sim.account._route_droplets = refuse_bot
    result = sim.run()
    checks('stopped on the definitive refusal', (result.status, result.code) == (provisioner.ABORTED, 'create_rejected'))
    checks('no guest was contacted', sim.guests.commands == [])
    checks('no retry was sent', len(sim.creates('/v2/droplets')) == 2)
    final = sim.drive_cleanup()
    checks('the partial pair is gone and closure is verified', sim.session_droplets() == [] and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    checks('evidence stays independently incomplete', final['overall'] == 'resources_verified_evidence_incomplete')
    checks('unrelated resources survive', sim.unrelated_intact() and sim.session_mutation_targets_only())


def lost_create_response_adopted_without_duplicate(sim, checks):
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=40.0)
    result = sim.run()
    checks('adopted when it became visible', result.status == provisioner.READY)
    checks('exactly one request per droplet', len(sim.creates('/v2/droplets')) == 2)
    checks('exactly two droplets exist', len(sim.session_droplets()) == 2)


def unknown_create_keeps_protection_past_d(sim, checks):
    sim.policy = FAST
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
    result = sim.run()
    checks('stopped with the outcome unknown', (result.status, result.code) == (provisioner.ABORTED, 'create_outcome_unknown'))
    checks('no retry was sent', len(sim.creates('/v2/droplets')) == 1)
    session = sim.stack.registry.session_row(sim.session_id)
    sim.clock.advance(session_clock.parse(session['deadline_d_utc']) - sim.clock.wall() + 600)
    sim.stack.step(60)
    final = sim.status()
    checks('neither elapsed time nor empty listings settled it', len(final['cleanup']['unresolved_creates']) == 1)
    checks('the session stays open and overdue', final['state'] == registry.DELETING and final['overall'] == 'cleanup_overdue')
    checks('the firewall still protects a possible landing', any(f['name'] == sim.session_id + '-fw' for f in sim.account.firewalls.values()))
    checks('no receipt basis exists', sim.provider.get_request_settlement(final['cleanup']['unresolved_creates'][0]['create_request_ref']) is None)


def operator_disposition_is_not_clean(sim, checks):
    sim.policy = FAST
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, land=False)
    result = sim.run()
    finish(sim, result)
    sim.stack.step(60)
    intent = sim.status()['cleanup']['unresolved_creates'][0]['intent_id']
    sim.stack.registry.dispose_create(sim.session_id, intent, 'offline fixture: account checked by unique tag')
    final = sim.drive_cleanup()
    checks('closure names the disposition', final['cleanup']['outcome'] == registry.VERIFIED_WITH_DISPOSITION)
    checks('it never reads clean', final['overall'] == 'resources_verified_with_operator_disposition')


def late_create_found_after_stop(sim, checks):
    sim.policy = FAST
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1, delay_s=300.0)
    result = sim.run()
    checks('stopped before it landed', result.code == 'create_outcome_unknown')
    sim.stack.step(120)
    checks('still open while the request is unresolved', sim.status()['state'] == registry.DELETING)
    final = sim.drive_cleanup()
    checks('discovered by unique tag', any(r['source'] == 'discovered' for r in final['resources']))
    checks('deleted, then closed', sim.session_droplets() == [] and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)
    checks('no second create', len(sim.creates('/v2/droplets')) == 1)


def duplicate_create_recorded_and_deleted(sim, checks):
    tags = sim.manifest['session']['ownership_tags']
    original = sim.provider.assign_droplet
    added = []

    def assign_then_duplicate(project, droplet):
        original(project, droplet)
        if len(sim.session_droplets()) == 2 and not added:
            added.append(sim.account._new_droplet(dict(name=sim.session_id + '-game', size='s-1vcpu-1gb-amd', region='sgp1', image=247516813, tags=[tags['session'], tags['game']])))
    sim.provider.assign_droplet = assign_then_duplicate
    result = sim.run()
    checks('stopped', (result.status, result.code) == (provisioner.ABORTED, 'unexpected_resource'))
    checks('the duplicate is durably recorded', any(e['kind'] == 'duplicate_create' for e in sim.stack.registry.journal(sim.session_id)))
    final = sim.drive_cleanup()
    checks('all three are deleted', sim.session_droplets() == [] and final['cleanup']['outcome'] == registry.VERIFIED_ABSENT)


def wrong_plan_cleans_owned(sim, checks):
    sim.account.wrong_size[sim.session_id + '-game'] = 's-2vcpu-4gb-amd'
    result = sim.run()
    checks('stopped on the plan', (result.status, result.code) == (provisioner.ABORTED, 'wrong_plan'))
    checks('no guest was contacted', sim.guests.commands == [])
    sim.drive_cleanup()
    checks('owned droplets deleted, unrelated kept', sim.session_droplets() == [] and sim.unrelated_intact())


def project_assignment_failure(sim, checks):
    sim.policy = FAST
    sim.account.assignment_status = 'service_down'
    result = sim.run()
    checks('stopped', (result.status, result.code) == (provisioner.ABORTED, 'project_assignment_failed'))
    sim.drive_cleanup()
    checks('membership was never what authorized a delete', sim.session_droplets() == [] and sim.unrelated_intact() and sim.session_mutation_targets_only())


def firewall_wrong_stops_before_droplets(sim, checks):
    original = sim.account._new_firewall

    def broaden(payload):
        return original(dict(payload, inbound_rules=payload['inbound_rules'] + [dict(protocol='tcp', ports='9100', sources=dict(addresses=['0.0.0.0/0']))]))
    sim.account._new_firewall = broaden
    result = sim.run()
    checks('read-back caught the extra rule', result.code == 'firewall_verification_failed')
    checks('no droplet was bought', sim.creates('/v2/droplets') == [])
    sim.drive_cleanup()
    checks('the wrong firewall is removed as owned', not any(f['name'] == sim.session_id + '-fw' for f in sim.account.firewalls.values()))


def cloud_init_failure_cleans_owned(sim, checks):
    sim.guests.break_step('bot', 'wait_cloud_init', rc=1, status='error', errors=['fixture failure'])
    result = sim.run()
    checks('stopped', (result.status, result.code) == (provisioner.ABORTED, 'bootstrap_failed'))
    checks('no build started', 'build' not in sim.guests.steps())
    sim.drive_cleanup()
    checks('both droplets deleted', sim.session_droplets() == [])


def impostor_host_key_never_pinned(sim, checks):
    sim.guests.impostor.add('game')
    result = sim.run()
    checks('stopped', (result.status, result.code) == (provisioner.ABORTED, 'host_verification_failed'))
    checks('nothing was pinned for that host', 'game' not in sim.guests.pins)
    checks('no command ran on it', sim.guests.steps('game') == [])


def ownership_ambiguity_refused_not_deleted(sim, checks):
    tags = sim.manifest['session']['ownership_tags']
    sim.policy = FAST
    original = sim.account._route_droplets

    def land_wrong(method, parts, query, payload):
        if method == 'POST':
            return original(method, parts, query, dict(payload, tags=[tags['session'], 'foreign']))
        return original(method, parts, query, payload)
    sim.account._route_droplets = land_wrong
    sim.account.fault('POST', '^/v2/droplets$', 'lost', times=1)
    result = sim.run()
    checks('not adopted', (result.status, result.code) == (provisioner.ABORTED, 'ownership_ambiguous'))
    sim.stack.step(60)
    final = sim.status()
    checks('an incident was opened', any(i['kind'] == 'ownership-mismatch' for i in final['incidents']))
    checks('it was not deleted', sim.account.ops('DELETE', '^/v2/droplets/') == [] and len(sim.session_droplets()) == 1)
    checks('the session is not clean', final['overall'] != 'clean')


def changed_operator_address_refreshed_by_api(sim, checks):
    result = sim.run()
    commands = len(sim.guests.commands)
    outcome = provisioner.refresh_access(sim.client, sim.provider, sim.manifest, result.fencing_token, [NEW_ADDRESS], [NEW_ADDRESS], sim.sleep, sim.monotonic, policy=FAST, evidence=sim.evidence)
    checks('applied', outcome['applied'])
    firewall = sim.provider.get_firewall(result.firewall_id)
    rules = {r['ports']: r['sources']['addresses'] for r in firewall['inbound_rules']}
    checks('the old address is gone', '203.0.113.10/32' not in json.dumps(rules))
    checks('the new address is exact', rules['22'] == [NEW_ADDRESS])
    checks('no SSH was needed', len(sim.guests.commands) == commands)


def firewall_retargeted_refused_and_preserved(sim, checks):
    run = sim.provisioner()
    original = run._assign_project
    foreign = sim.unrelated['droplets'][1]

    def retarget():
        original()
        sim.account.firewalls[run.firewall_id].update(tags=['prod'], droplet_ids=[foreign])
    run._assign_project = retarget
    result = run.run()
    checks('stopped on the ownership conflict', (result.status, result.code) == (provisioner.ABORTED, 'ownership_conflict'))
    checks('no replacement touched the retargeted firewall', sim.puts() == [])
    checks('no guest was contacted', sim.guests.commands == [])
    checks('the incident was durable before cleanup began', len(sim.open_incidents()) == 1)
    sim.stack.step(180)
    firewall = sim.account.firewalls[run.firewall_id]
    checks('the foreign attachment is intact', (firewall['tags'], firewall['droplet_ids']) == (['prod'], [foreign]))
    checks('the owned droplets are gone', sim.session_droplets() == [])
    checks('the firewall is not deleted and the session stays open', sim.account.ops('DELETE', '/v2/firewalls/') == [] and sim.status()['state'] != registry.CLOSED)
    checks('unrelated resources survive', sim.unrelated_intact())


def protected_droplet_stops_before_any_operation(sim, checks):
    original = sim.account._new_droplet

    def create(payload):
        return original(dict(payload, tags=list(payload['tags']) + (['omega-management'] if payload['name'].endswith('-game') else [])))
    sim.account._new_droplet = create
    result = sim.run()
    checks('stopped on the ownership conflict', (result.status, result.code) == (provisioner.ABORTED, 'ownership_conflict'))
    checks('no assignment, firewall change or guest work happened', sim.account.ops('POST', '/resources$') == [] and sim.puts() == [] and sim.guests.commands == [])
    sim.stack.step(180)
    protected = next(d for d in sim.account.droplets.values() if d['name'] == sim.session_id + '-game')
    checks('the protected droplet keeps its tag and is not deleted', 'omega-management' in protected['tags'] and sim.account.ops('DELETE', '/v2/droplets/%d$' % protected['id']) == [])
    checks('an incident stays open and the session stays open', len(sim.open_incidents()) == 1 and sim.status()['state'] != registry.CLOSED)


def package_versions_identifiable_after_teardown(sim, checks):
    sim.guests.package_versions = dict(bot=dict(libc6='2.39-fixture2'))
    result = sim.run()
    finish(sim, result)
    sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='batch finished')
    final = sim.drive_cleanup()
    checks('both guests are destroyed', final['overall'] == 'clean' and sim.session_droplets() == [])
    retained = {role: json.loads((sim.evidence.root / ('packages-%s.json' % role)).read_text()) for role in ('game', 'bot')}
    versions = {role: {e['name']: e['version'] for e in retained[role]['inventory']} for role in retained}
    checks('the differing version is named for each role', (versions['game']['libc6'], versions['bot']['libc6']) == ('2.39-fixture1', '2.39-fixture2'))
    checks('the inventory hashes differ', retained['game']['sha256'] != retained['bot']['sha256'])
    report = json.loads((sim.evidence.root / 'readiness.json').read_text())
    checks('the readiness report binds both inventories for later export',
           sorted(a['role'] for a in report['required_artifacts']) == ['bot', 'game']
           and all(hashlib.sha256((sim.evidence.root / ('packages-%s.json' % a['role'])).read_bytes()).hexdigest() == a['sha256'] for a in report['required_artifacts']))


def broad_source_refused_outage_keeps_rules(sim, checks):
    result = sim.run()
    before = sim.provider.get_firewall(result.firewall_id)['inbound_rules']
    puts = len(sim.account.ops('PUT'))
    refused = False
    try:
        provisioner.refresh_access(sim.client, sim.provider, sim.manifest, result.fencing_token, ['0.0.0.0/0'], [], sim.sleep, sim.monotonic, policy=FAST)
    except session_access.AccessRefused:
        refused = True
    checks('a world-open source is refused with no request', refused and len(sim.account.ops('PUT')) == puts)
    rule = sim.account.fault('PUT', '/v2/firewalls/.*', 'status', status=503)
    outcome = provisioner.refresh_access(sim.client, sim.provider, sim.manifest, result.fencing_token, [NEW_ADDRESS], [], sim.sleep, sim.monotonic, policy=FAST)
    sim.account.rules.remove(rule)
    checks('an outage reports failure', not outcome['applied'])
    checks('the previous exact rules stay in force', sim.provider.get_firewall(result.firewall_id)['inbound_rules'] == before)


def persistent_outage_overdue_then_verified(sim, checks):
    result = sim.run()
    finish(sim, result)
    rule = sim.account.outage()
    session = sim.stack.registry.session_row(sim.session_id)
    sim.clock.advance(session_clock.parse(session['deadline_d_utc']) - sim.clock.wall() + 30)
    sim.stack.step(120)
    overdue = sim.status()
    checks('overdue and not clean during the outage', overdue['overall'] == 'cleanup_overdue')
    checks('the droplets still exist, as nothing pretends otherwise', len(sim.session_droplets()) == 2)
    sim.account.rules.remove(rule)
    final = sim.drive_cleanup()
    checks('cleaned after the provider returned', sim.session_droplets() == [])
    checks('the breach stays visible', final['overall'] == 'resources_verified_after_overdue' and final['cleanup']['overrun_s'] > 0)


def accepted_delete_is_not_absence(sim, checks):
    result = sim.run()
    finish(sim, result)
    sim.account.linger_reads = 12
    sim.client.mutate('request_cleanup', session_id=sim.session_id, fencing_token=result.fencing_token, reason='batch finished')
    sim.stack.step(45)
    midway = sim.status()
    checks('a delete was accepted', len(sim.account.ops('DELETE', r'^/v2/droplets/\d+$')) >= 2)
    checks('the droplets are still listed', len(sim.session_droplets()) == 2)
    checks('accepted is not closed', midway['state'] == registry.DELETING and midway['overall'] != 'clean')
    final = sim.drive_cleanup()
    checks('closed only after authenticated 404s and an empty listing', final['overall'] == 'clean')


def restarted_controller_fails_closed(sim, checks):
    original = sim.guests.pin_host

    def crash(*_):
        raise KeyboardInterrupt
    sim.guests.pin_host = crash
    try:
        sim.run()
    except KeyboardInterrupt:
        pass
    sim.guests.pin_host = original
    checks('the pair exists when the controller dies', len(sim.session_droplets()) == 2)
    session = sim.stack.registry.session_row(sim.session_id)
    sim.clock.advance(session_clock.parse(session['lease_expires_at']) - sim.clock.wall() + 1)
    sim.stack.watchdog.tick()
    client = registry_client.RegistryClient(registry_client.LocalTransport(sim.stack.registry), 'controller-b', attempts=1, retry_delay_s=0, sleep=lambda _: None,
                                            monotonic=sim.monotonic, new_request_id=lambda: 'controller-b-r' + str(next(sim.stack._ids)))
    result = sim.run(client=client)
    checks('the new controller requests cleanup instead of resuming', (result.status, result.code) == (provisioner.ABORTED, 'restart_fails_closed'))
    checks('no further create was sent', len(sim.creates('/v2/droplets')) == 2)
    sim.drive_cleanup()
    checks('owned droplets deleted', sim.session_droplets() == [])


SCENARIOS = (ready_pair_then_clean_close, wrong_facts_create_nothing, missing_authorization_sends_nothing, partial_pair_cleans_only_owned,
             lost_create_response_adopted_without_duplicate, unknown_create_keeps_protection_past_d, operator_disposition_is_not_clean, late_create_found_after_stop,
             duplicate_create_recorded_and_deleted, wrong_plan_cleans_owned, project_assignment_failure, firewall_wrong_stops_before_droplets, cloud_init_failure_cleans_owned,
             impostor_host_key_never_pinned, ownership_ambiguity_refused_not_deleted, changed_operator_address_refreshed_by_api, broad_source_refused_outage_keeps_rules,
             persistent_outage_overdue_then_verified, accepted_delete_is_not_absence, restarted_controller_fails_closed,
             firewall_retargeted_refused_and_preserved, protected_droplet_stops_before_any_operation, package_versions_identifiable_after_teardown)


def _leak_check(sim):
    """Everything this session wrote or sent, including what would have reached a guest."""
    blobs = [sim.stack.state_bytes().decode('latin-1'), json.dumps(sim.account.requests), json.dumps(sim.account.droplet_requests)]
    blobs += [path.read_text(encoding='utf-8') for path in sim.evidence.root.iterdir() if path.is_file()]
    return manifest_mod.scan_for_secrets(blobs)


def record(sim):
    registry_view = sim.stack.registry
    sessions = [s['session_id'] for s in registry_view.list_sessions()]
    journal_path = sim.evidence.root / 'journal.ndjson'
    return dict(
        provider_requests=[{k: v for k, v in entry.items() if k != 'send_by'} for entry in sim.account.requests],
        guest_steps=[{k: v for k, v in entry.items() if k in ('role', 'step')} for entry in sim.guests.commands],
        provider_inventory_at_end=sim.account.live(),
        user_data_sha256=[hashlib.sha256(r['user_data'].encode('utf-8')).hexdigest() for r in sim.account.droplet_requests],
        registry_journal=[dict(seq=e['seq'], at=e['at'], kind=e['kind']) for e in registry_view.journal()],
        registry_journal_verification=registry_view.verify_journal(),
        provisioning_journal=[json.loads(line) for line in journal_path.read_text().splitlines()] if journal_path.exists() else [],
        sessions={s: {k: v for k, v in registry_view.status(s).items() if k in ('state', 'overall', 'cleanup', 'resources', 'intents', 't0_utc', 'cleanup_c_utc', 'deadline_d_utc')} for s in sessions},
        retained_package_inventories={path.name: json.loads(path.read_text()) for path in sorted(sim.evidence.root.glob('packages-*.json'))},
        incidents=[dict(kind=i['kind'], status=i['status'], last_error=i['last_error']) for i in registry_view.incidents()])


def run_scenario(scenario):
    context = fault_evidence.Context()
    try:
        sim = pf.Sim(context)
        results = []
        scenario(sim, lambda name, passed: results.append(dict(check=name, passed=bool(passed))))
        results.append(dict(check='no credential-shaped value in registry state, evidence or guest bootstrap', passed=_leak_check(sim) == []))
        failed = [r['check'] for r in results if not r['passed']]
        if failed:
            raise AssertionError(scenario.__name__ + ' failed: ' + ', '.join(failed))
        return dict(scenario=scenario.__name__, clock='scripted', provider='fake account behind the real adapter', guests='fake', checks=results, **record(sim))
    finally:
        context.close()


def generate(out):
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    summary = ['# Slice 3 offline provisioning timelines', '',
               'Generated by `scripts/do_session/provision_fault_evidence.py`: the real adapter, registry and watchdog against a fake DigitalOcean account and fake guests on a '
               'scripted clock. No account, network, credential or guest was involved, and none of this is a capacity or live-provider result. '
               'Addresses and package versions are synthetic fixtures; a real session keeps its package inventories in its private session directory, not here. `test_provision_fault_evidence` regenerates the files and compares them with `SHA256SUMS`.', '',
               '| Timeline | Checks passed | Provider requests | Guest steps | Incidents |', '| --- | ---: | ---: | ---: | ---: |']
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
        summary.append('| [%s](%s) | %d/%d | %d | %d | %d |' % (scenario.__name__, name, sum(1 for c in result['checks'] if c['passed']), len(result['checks']),
                                                                len(result['provider_requests']), len(result['guest_steps']), len(result['incidents'])))
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
