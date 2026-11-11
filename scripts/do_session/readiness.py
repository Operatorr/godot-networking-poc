"""Whether a pair may be called ready. A provider ``active`` status is not enough (issue #59 §3).

Everything here is a pure function of retained observations, so each check has a fixture and a live run is judged by
the same rules. A missing field is a failure, never a pass: ``check`` is written so that an absent value cannot satisfy it.
"""
import hashlib

import manifest as manifest_mod

MIN_NOFILE = 65536
MIN_RESULTS_FREE_GIB = 5
MAX_CLOCK_ERROR_S = 1.0
MAX_CLOCK_UNCERTAINTY_S = 15.0
MEMORY_TOLERANCE = (0.80, 1.05)    # the kernel reports less than the plan; more means a different plan
DISK_TOLERANCE = (0.90, 1.05)
ROOT_LOGIN_REFUSED = ('no',)
CPU_VENDORS = {'premium-amd': 'AuthenticAMD', 'premium-intel': 'GenuineIntel'}
MIN_SAMPLES = 2
# Every guest runs these to exist at all, so a list without them was cut short whatever its own count says.
REQUIRED_PACKAGES = ('base-files', 'dpkg', 'libc6', 'openssh-server', 'python3')
GAME_PORT = 8081
METRICS_PORT = 9100
LOOPBACK = ('127.0.0.1', '::1')


class Findings:
    def __init__(self, role):
        self.role = role
        self.problems = []

    def check(self, name, condition, detail=''):
        if not condition:
            self.problems.append(self.role + ':' + name + (' (' + detail + ')' if detail else ''))


def _within(actual, plan, tolerance):
    return isinstance(actual, (int, float)) and isinstance(plan, (int, float)) and tolerance[0] * plan <= actual <= tolerance[1] * plan


def binaries_frozen(manifest):
    """A calibration session exists to learn what the cold build produces, so its result cannot already be frozen.

    It still proves that the relayed copy equals what the builder made. Lifecycle smoke and capacity manifests freeze
    the hash a calibration observed, and any drift there stops the session instead of being recorded as new truth.
    """
    return manifest['session'].get('kind') != 'calibration'


def expected_binary(manifest, role, built_release=None):
    name = dict(game='omega-server', bot='omega-load-test')[role]
    if binaries_frozen(manifest):
        return name, manifest['source']['binary_sha256'][role]
    return name, (built_release or {}).get(name)


def droplet_problems(manifest, role, droplet):
    """The provider's record of one Droplet against the frozen plan. Any difference is a wrong condition."""
    findings = Findings(role)
    spec = manifest['roles'][role]
    tags = manifest['session']['ownership_tags']
    findings.check('name', droplet.get('name') == manifest['session']['id'] + '-' + role, str(droplet.get('name')))
    findings.check('session_tag', tags['session'] in (droplet.get('tags') or []))
    findings.check('role_tag', tags[role] in (droplet.get('tags') or []))
    findings.check('size', droplet.get('size_slug') == spec['size_slug'], str(droplet.get('size_slug')))
    findings.check('region', droplet.get('region') == spec['region'], str(droplet.get('region')))
    findings.check('image', droplet.get('image_id') == spec['image_id'], str(droplet.get('image_id')))
    findings.check('vcpus', droplet.get('vcpus') == spec['vcpus'], str(droplet.get('vcpus')))
    findings.check('memory', droplet.get('memory_mib') == spec['memory_mib'], str(droplet.get('memory_mib')))
    findings.check('disk', droplet.get('disk_gib') == spec['disk_gib'], str(droplet.get('disk_gib')))
    findings.check('public_ipv4', len(droplet.get('public_ipv4') or []) == 1, 'needs exactly one public route')
    return findings.problems


def package_problems(packages):
    """Whether a guest's package report really is the whole list it says it is. A digest proves nothing without the list."""
    if not isinstance(packages, dict):
        return ['no package report']
    problems = []
    if packages.get('rc') != 0:
        problems.append('the package command exited %s' % packages.get('rc'))
    if packages.get('complete') is not True:
        problems.append('the package list is not complete: %s' % packages.get('incomplete'))
    inventory = packages.get('inventory')
    if not isinstance(inventory, list) or not inventory:
        return problems + ['no package inventory']
    if not all(isinstance(e, dict) and set(e) == {'name', 'version'} and e['name'] and e['version']
               and isinstance(e['name'], str) and isinstance(e['version'], str) for e in inventory):
        return problems + ['package inventory has a malformed entry']
    if packages.get('count') != len(inventory):
        problems.append('package count %s does not match %d entries' % (packages.get('count'), len(inventory)))
    text = ''.join('%s %s\n' % (e['name'], e['version']) for e in inventory)
    if packages.get('sha256') != hashlib.sha256(text.encode('utf-8')).hexdigest():
        problems.append('package digest does not match the inventory')
    missing = sorted(set(REQUIRED_PACKAGES) - {e['name'] for e in inventory})
    if missing:
        problems.append('package inventory lacks ' + ', '.join(missing))
    return problems


def _secret_free(findings, value, name):
    findings.check(name + '_secret_free', not manifest_mod.scan_for_secrets(value))


def observation_problems(manifest, role, observation, image_name, built_release=None):
    """One guest's own account of itself. ``image_name`` is the provider's name for the pinned image."""
    findings = Findings(role)
    spec = manifest['roles'][role]
    obs = observation if isinstance(observation, dict) else {}
    source = manifest['source']
    findings.check('role', obs.get('role') == role)

    cloud = obs.get('cloud_init') or {}
    findings.check('cloud_init_done', cloud.get('rc') == 0 and cloud.get('status') == 'done', str(cloud.get('status')))
    findings.check('cloud_init_errors', cloud.get('errors') == [] and not cloud.get('recoverable_errors'))
    findings.check('cloud_init_boot_finished', cloud.get('boot_finished') is True)

    findings.check('architecture', obs.get('architecture') == 'x86_64' and spec['architecture'] == 'x64', str(obs.get('architecture')))
    findings.check('os_image', (obs.get('os') or {}).get('id') == 'ubuntu' and bool((obs.get('os') or {}).get('version_id'))
                   and str(image_name).startswith(str((obs.get('os') or {}).get('version_id'))), str(obs.get('os')))
    findings.check('kernel', bool(obs.get('kernel')))
    for problem in package_problems(obs.get('packages')):
        findings.check('packages', False, problem)

    cpu, memory = obs.get('cpu') or {}, obs.get('memory') or {}
    findings.check('cpu_count', cpu.get('count') == spec['vcpus'], str(cpu.get('count')))
    vendor = CPU_VENDORS.get(spec['cpu_class'])
    findings.check('cpu_vendor', bool(cpu.get('vendor')) and (vendor is None or cpu.get('vendor') == vendor), str(cpu.get('vendor')))
    findings.check('memory', _within(memory.get('total_mib'), spec['memory_mib'], MEMORY_TOLERANCE), str(memory.get('total_mib')))
    findings.check('no_swap', memory.get('swap_total_mib') == 0, str(memory.get('swap_total_mib')))

    disk = obs.get('disk') or {}
    findings.check('disk', _within(disk.get('root_total_gib'), spec['disk_gib'], DISK_TOLERANCE), str(disk.get('root_total_gib')))
    free = disk.get('results_free_gib')
    findings.check('storage_free', isinstance(free, int) and free >= MIN_RESULTS_FREE_GIB, str(free))
    findings.check('storage_writable', disk.get('results_writable') is True)

    nofile = obs.get('nofile') or {}
    for limit in ('soft', 'hard'):
        value = nofile.get(limit)
        findings.check('nofile_' + limit, isinstance(value, int) and value >= MIN_NOFILE, str(value))

    sshd = obs.get('sshd') or {}
    findings.check('sshd_readable', sshd.get('rc') == 0)
    findings.check('sshd_password_off', sshd.get('passwordauthentication') == 'no')
    findings.check('sshd_keyboard_off', sshd.get('kbdinteractiveauthentication') == 'no')
    findings.check('sshd_pubkey_on', sshd.get('pubkeyauthentication') == 'yes')
    findings.check('sshd_methods', sshd.get('authenticationmethods') == 'publickey', str(sshd.get('authenticationmethods')))
    findings.check('sshd_root_refused', sshd.get('permitrootlogin') in ROOT_LOGIN_REFUSED, str(sshd.get('permitrootlogin')))
    findings.check('authorized_key', obs.get('authorized_keys') == [manifest['ssh_key']['fingerprint_sha256']])

    listeners = obs.get('listeners')
    findings.check('listeners_read', isinstance(listeners, list) and any(l.get('port') == 22 for l in listeners or []))
    occupied = {(l.get('protocol'), l.get('port')) for l in listeners or []}
    findings.check('port_game_free', ('udp', GAME_PORT) not in occupied)
    findings.check('port_metrics_free', ('tcp', METRICS_PORT) not in occupied)

    clock = obs.get('clock') or {}
    findings.check('clock_synchronized', clock.get('ntp_synchronized') is True and clock.get('service') == 'active')
    findings.check('clock_monotonic', isinstance(clock.get('monotonic_ns'), int) and clock['monotonic_ns'] > 0)
    findings.check('clock_boot_id', bool(clock.get('boot_id')))
    secrets = obs.get('secrets') or {}
    findings.check('guest_secret_scan', secrets.get('findings') == [], ', '.join(secrets.get('findings') or []) or 'not reported')

    release = obs.get('release') or {}
    binary, expected = expected_binary(manifest, role, built_release)
    findings.check('binary_hash', bool(expected) and release.get(binary) == expected, str(release.get(binary)))
    if role == 'game':
        findings.check('config_hash', release.get('server_config.json') == source['server_config_sha256'],
                       str(release.get('server_config.json')))
    findings.check('sampler_present', bool(release.get('sample_host.py')))
    return findings.problems


def clock_problems(role, measured):
    """The controller's bracketed reading of a guest's wall clock. This is a coarse sanity check with its uncertainty stated.

    It fails when the bracket proves the clocks disagree, or is too wide to say anything. ``ntp_synchronized`` is the
    guest's own claim, and later slices map run boundaries more finely.
    """
    findings = Findings(role)
    offset, uncertainty = (measured or {}).get('offset_s'), (measured or {}).get('uncertainty_s')
    known = isinstance(offset, (int, float)) and isinstance(uncertainty, (int, float))
    findings.check('clock_offset', known and abs(offset) - uncertainty <= MAX_CLOCK_ERROR_S, str(measured))
    findings.check('clock_uncertainty', known and uncertainty <= MAX_CLOCK_UNCERTAINTY_S, str(measured))
    return findings.problems


def build_problems(manifest, source_report, build_report):
    """The clean-source and locked-build reports from the builder, against the frozen revision and digests."""
    findings = Findings('build')
    source = manifest['source']
    fetched, built = source_report or {}, build_report or {}
    findings.check('source_fetched', fetched.get('ok') is True)
    findings.check('source_sha', fetched.get('head') == source['benchmark_sha'], str(fetched.get('head')))
    findings.check('source_clean', fetched.get('clean') is True)
    findings.check('cargo_lock', fetched.get('cargo_lock_sha256') == source['cargo_lock_sha256'])
    findings.check('server_config', fetched.get('server_config_sha256') == source['server_config_sha256'])
    findings.check('content', fetched.get('content_sha256') == source['content_sha256'])
    findings.check('build_ok', built.get('ok') is True and built.get('rc') == 0)
    findings.check('clean_after_build', built.get('clean_after_build') is True)
    expected = str(source['rust_toolchain']).split('-')[0]
    findings.check('rustc_version', ('rustc ' + expected + ' ') in (str(built.get('rustc')) + ' '), str(built.get('rustc')))
    findings.check('rustc_host', ('host: ' + source['target_triple']) in str(built.get('rustc')))
    findings.check('build_flags', built.get('flags') == source['build_flags'])
    release = built.get('release') or {}
    for check, role in (('binary_game', 'game'), ('binary_bot', 'bot')):
        name, expected = expected_binary(manifest, role, release)
        findings.check(check, bool(expected) and release.get(name) == expected, str(release.get(name)))
    return findings.problems


def sampler_problems(role, report):
    findings = Findings(role)
    report = report or {}
    samples = report.get('samples')
    findings.check('sampler_samples', isinstance(samples, int) and samples >= MIN_SAMPLES, str(samples))
    findings.check('sampler_alive', report.get('alive_until_stopped') is True)
    findings.check('sampler_clock', report.get('monotonic_advancing') is True)
    return findings.problems


def enforcement_problems(probe):
    """A real packet against the firewall: the bot's address is not an SSH source, so its attempt must simply vanish.

    A refusal would mean the packet reached the host, so only a timeout proves the rule is in force at the provider.
    """
    findings = Findings('firewall')
    findings.check('ssh_from_bot_blocked', (probe or {}).get('outcome') == 'timeout', str((probe or {}).get('outcome')))
    return findings.problems


def smoke_problems(game_started, bot_report, game_stopped):
    """A real ENet exchange across the public route, then proof that nothing from it is left behind."""
    findings = Findings('enet_smoke')
    started, bot, stopped = game_started or {}, bot_report or {}, game_stopped or {}
    findings.check('game_running', started.get('running') is True)
    listeners = started.get('listeners') or []
    findings.check('game_port_bound', any(l.get('protocol') == 'udp' and l.get('port') == GAME_PORT for l in listeners))
    metrics = [l for l in listeners if l.get('port') == METRICS_PORT]
    findings.check('metrics_bound', bool(metrics))
    findings.check('metrics_loopback_only', bool(metrics) and all(l.get('address') in LOOPBACK for l in metrics))
    findings.check('metrics_answer', started.get('metrics_loopback_ok') is True)
    findings.check('bot_report', bot.get('report') is True)
    requested = bot.get('requested_bots')
    findings.check('bots_connected', isinstance(requested, int) and requested > 0 and bot.get('connected_bots') == requested,
                   str(bot.get('connected_bots')))
    for field in ('disconnected_bots', 'total_errors', 'total_decode_failures', 'total_send_failures', 'total_panics'):
        findings.check(field, bot.get(field) == 0, str(bot.get(field)))
    findings.check('traffic_both_ways', (bot.get('total_packets_sent') or 0) > 0 and (bot.get('total_packets_received') or 0) > 0)
    findings.check('game_stopped', stopped.get('exited_on_signal') is True and stopped.get('processes') == 0)
    left = stopped.get('listeners')
    findings.check('ports_released', isinstance(left, list) and not any(l.get('port') in (GAME_PORT, METRICS_PORT) for l in left))
    return findings.problems
