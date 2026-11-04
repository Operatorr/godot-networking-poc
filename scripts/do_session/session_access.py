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


def _rule_key(rule, side):
    selector = rule.get(side) or {}
    protocol, ports = rule.get('protocol'), str(rule.get('ports', '0'))
    if protocol == 'icmp' or ports in ('all', '1-65535'):
        ports = '0'
    addresses = []
    for address in selector.get('addresses') or []:
        try:
            addresses.append(str(ipaddress.ip_network(str(address), strict=False)))
        except ValueError:
            addresses.append(str(address))
    return (protocol, ports, rule.get('action', 'allow'), tuple(sorted(addresses)), tuple(sorted(selector.get('tags') or [])),
            tuple(sorted(selector.get('droplet_ids') or [])), tuple(sorted(selector.get('load_balancer_uids') or [])))


def firewall_problems(actual, desired):
    """Why the provider's firewall is not exactly what we asked for. Extra rules count as much as missing ones."""
    problems = []
    if actual.get('name') != desired['name']:
        problems.append('firewall name differs')
    if sorted(actual.get('tags') or []) != sorted(desired['tags']):
        problems.append('firewall targets different tags')
    if actual.get('droplet_ids'):
        problems.append('firewall targets droplets directly')
    for field, side in (('inbound_rules', 'sources'), ('outbound_rules', 'destinations')):
        have = sorted(_rule_key(r, side) for r in actual.get(field) or [])
        want = sorted(_rule_key(r, side) for r in desired[field])
        if have != want:
            problems.append(field + ' differ from the requested exact rules')
    return problems


def applied_problems(actual):
    """Rules on record are not yet rules in force; only the provider's completed status says that."""
    problems = []
    if actual.get('status') != 'succeeded':
        problems.append('firewall status is %r' % actual.get('status'))
    if actual.get('pending_changes'):
        problems.append('firewall has pending changes')
    return problems
