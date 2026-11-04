"""Exact Cloud Firewall rules for one session, and the check that the provider holds exactly those (issue #59 §3).

Ingress is two rules and nothing else: SSH from exact operator/controller addresses, and unsigned game UDP 8081
from the bot's public address plus explicit operator addresses. Metrics 9100 has no rule, and the server binds it
to loopback as well. Egress stays open, as DigitalOcean firewalls deny outbound traffic that has no rule, and
bootstrap and game replies need it.

Every source must name one host. A range is refused here, before any request, so a changed operator address can
never become a broad rule. No address reaches a guest or its bootstrap data: these rules live only at the provider.
"""
import ipaddress

SSH_PORT = '22'
GAME_PORT = '8081'
METRICS_PORT = '9100'
WORLD = ['0.0.0.0/0', '::/0']
OUTBOUND = tuple(dict(protocol=protocol, ports=ports, destinations=dict(addresses=list(WORLD)))
                 for protocol, ports in (('tcp', 'all'), ('udp', 'all'), ('icmp', None)))
# firewall_rule.yml in DigitalOcean's OpenAPI specification. Any populated selector widens a rule, so all of them count.
SELECTOR_FIELDS = ('addresses', 'droplet_ids', 'kubernetes_ids', 'load_balancer_uids', 'tags')
RULE_FIELDS = ('protocol', 'ports', 'action')
RULE_SIDES = (('inbound_rules', 'sources'), ('outbound_rules', 'destinations'))
NON_PUBLIC = tuple(ipaddress.ip_network(n) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16', '100.64.0.0/10', 'fc00::/7'))


class AccessRefused(ValueError):
    """The requested allowlist is not a set of exact, routable hosts. Nothing was sent."""


def exact_hosts(sources):
    """Normalize to sorted single-host CIDRs, refusing anything broader or unroutable."""
    if not isinstance(sources, (list, tuple)):
        raise AccessRefused('sources must be an explicit list')
    hosts = set()
    for source in sources:
        try:
            network = ipaddress.ip_network(str(source), strict=True)
        except ValueError:
            raise AccessRefused('not an exact address: ' + str(source))
        if network.prefixlen != network.max_prefixlen:
            raise AccessRefused('source is a range, not one host: ' + str(source))
        address = network.network_address
        if (address.is_unspecified or address.is_loopback or address.is_link_local or address.is_multicast or address.is_reserved
                or any(address in block for block in NON_PUBLIC)):
            raise AccessRefused('source is not a routable host: ' + str(source))
        hosts.add(str(network))
    return sorted(hosts)


def firewall_request(manifest, ssh_sources, operator_udp_sources, bot_address=None):
    """The complete firewall representation. PUT replaces everything, so this is also the refresh body."""
    session = manifest['session']
    ssh = exact_hosts(ssh_sources)
    if not ssh:
        raise AccessRefused('at least one exact SSH source is required')
    game = exact_hosts(list(operator_udp_sources) + ([bot_address + '/32'] if bot_address else []))
    inbound = [dict(protocol='tcp', ports=SSH_PORT, sources=dict(addresses=ssh))]
    if game:
        inbound.append(dict(protocol='udp', ports=GAME_PORT, sources=dict(addresses=game)))
    tags = session['ownership_tags']
    return dict(name=session['id'] + '-fw', inbound_rules=inbound, outbound_rules=[_outbound(r) for r in OUTBOUND],
                droplet_ids=[], tags=sorted((tags['game'], tags['bot'])))


def _outbound(rule):
    return {k: v for k, v in rule.items() if v is not None}


def _populated(value):
    return value not in (None, [], {}, '')


def _selector_values(selector, field):
    values = (selector or {}).get(field) if isinstance(selector, dict) else None
    return values if isinstance(values, list) else []


def _rule_key(rule, side):
    """The canonical identity of one rule: every field the API can use to widen it, in comparable form."""
    if not isinstance(rule, dict):
        return ('not-an-object',)
    selector = rule.get(side)
    protocol, ports = rule.get('protocol'), str(rule.get('ports', '0'))
    if protocol == 'icmp' or ports in ('all', '1-65535'):
        ports = '0'
    addresses = []
    for address in _selector_values(selector, 'addresses'):
        try:
            addresses.append(str(ipaddress.ip_network(str(address), strict=False)))
        except ValueError:
            addresses.append(str(address))
    selectors = tuple(tuple(sorted(str(v) for v in _selector_values(selector, field))) for field in SELECTOR_FIELDS if field != 'addresses')
    return (str(protocol), ports, str(rule.get('action') or 'allow'), tuple(sorted(addresses))) + selectors


def rule_shape_problems(field, rule, side):
    """What exact comparison cannot express: a value the schema does not define is refused, never ignored."""
    if not isinstance(rule, dict):
        return [field + ' holds a rule that is not an object']
    problems = []
    for name in sorted(set(rule) - set(RULE_FIELDS) - {side}):
        if _populated(rule[name]):
            problems.append('%s rule has an unknown field %s' % (field, name))
    selector = rule.get(side)
    if _populated(selector) and not isinstance(selector, dict):
        problems.append('%s rule %s is not an object' % (field, side))
    for name, value in (selector.items() if isinstance(selector, dict) else ()):
        if name not in SELECTOR_FIELDS:
            if _populated(value):
                problems.append('%s rule has an unknown selector %s' % (field, name))
        elif _populated(value) and not isinstance(value, list):
            problems.append('%s rule selector %s is not a list' % (field, name))
    return problems


def _rules_of(actual, field):
    rules = actual.get(field)
    return rules if isinstance(rules, list) else []


def target_problems(actual, desired, firewall_id=None):
    """The firewall's identity: exact recorded id, exact name, exactly its two role tags and no direct Droplet."""
    problems = []
    if firewall_id is not None and actual.get('id') != firewall_id:
        problems.append('firewall id differs from the recorded id')
    if actual.get('name') != desired['name']:
        problems.append('firewall name differs')
    if sorted(actual.get('tags') or []) != sorted(desired['tags']):
        problems.append('firewall targets different tags')
    if actual.get('droplet_ids'):
        problems.append('firewall targets droplets directly')
    return problems


def firewall_problems(actual, desired):
    """Why the provider's firewall is not exactly what we asked for. Extra rules count as much as missing ones."""
    problems = target_problems(actual, desired)
    for field, side in RULE_SIDES:
        rules = _rules_of(actual, field)
        for rule in rules:
            problems.extend(rule_shape_problems(field, rule, side))
        if sorted(_rule_key(r, side) for r in rules) != sorted(_rule_key(r, side) for r in desired[field]):
            problems.append(field + ' differ from the requested exact rules')
    return problems


def replacement_problems(actual, desired, firewall_id):
    """May a full replacement overwrite this firewall? Only if it is still what this session alone could have written.

    A session changes exactly one thing between replacements: which single-host addresses appear in its SSH and game
    rules. So those addresses may differ from ``desired``, and any other difference is somebody else's change. A PUT
    would destroy the evidence of it, along with any attachment made to an unrelated host.
    """
    problems = target_problems(actual, desired, firewall_id)
    for field, side in RULE_SIDES:
        for rule in _rules_of(actual, field):
            problems.extend(rule_shape_problems(field, rule, side))
    outbound = 'outbound_rules', 'destinations'
    if (sorted(_rule_key(r, outbound[1]) for r in _rules_of(actual, outbound[0]))
            != sorted(_rule_key(r, outbound[1]) for r in desired[outbound[0]])):
        problems.append('outbound_rules differ from the requested exact rules')
    seen = []
    for rule in _rules_of(actual, 'inbound_rules'):
        key = _rule_key(rule, 'sources')
        if key[:3] not in (('tcp', SSH_PORT, 'allow'), ('udp', GAME_PORT, 'allow')) or key[:3] in seen:
            problems.append('inbound_rules hold a rule this session never wrote')
            continue
        seen.append(key[:3])
        if any(key[4:]):
            problems.append('inbound_rules allow sources other than exact addresses')
        try:
            exact_hosts(list(key[3]))
        except AccessRefused:
            problems.append('inbound_rules allow an address that is not one routable host')
    return problems


def applied_problems(actual):
    """Rules on record are not yet rules in force; only the provider's completed status says that."""
    problems = []
    if actual.get('status') != 'succeeded':
        problems.append('firewall status is %r' % actual.get('status'))
    if actual.get('pending_changes'):
        problems.append('firewall has pending changes')
    return problems
