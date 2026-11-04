"""Cloud-init user data for one role of a cold-booted session. Its limits are the point of this module.

Public keys only. No provider token, private key, operator address or source allowlist may appear here: source
filtering lives in the provider firewall, so a changed operator address never touches a guest. ``validate`` is
called on every rendering, and a failure stops the session before its Droplet create.

First SSH contact verifies the host without placing any private key in user data. The controller sends one random
per-Droplet nonce over the authenticated API. The guest binds its fresh Ed25519 host key to that nonce with an HMAC,
deletes the nonce file and publishes only the HMAC. Only something that received the user data can produce a binding
for a given host key. The nonce authorizes nothing and is never written to controller storage (see ``ssh_access``).

YAML is a superset of JSON, so the document is JSON behind ``#cloud-config``: one renderer and no quoting edge cases.
"""
import json
import pathlib

import manifest as manifest_mod
import provider_preflight

PUBLIC_KEY_PATH = pathlib.Path(__file__).parents[2] / 'deployment' / 'hetzner' / 'ssh' / 'omega_loadtest_ed25519.pub'
MAX_USER_DATA_BYTES = 64 * 1024
GUEST_USER = 'deploy'
BINDING_PATH = '/run/omega-host-binding.json'
NONCE_PATH = '/etc/omega-host-binding.nonce'
HOST_KEY_PATH = '/etc/ssh/ssh_host_ed25519_key.pub'
RESULTS_DIR = '/home/deploy/omega-results'
NOFILE_LIMIT = 65536
BASE_PACKAGES = ('ca-certificates', 'iproute2', 'jq', 'python3', 'systemd-timesyncd')
BUILDER_PACKAGES = ('build-essential', 'curl', 'git', 'libssl-dev', 'pkg-config')
PACKAGES = dict(game=BASE_PACKAGES, bot=BASE_PACKAGES + BUILDER_PACKAGES)

SSHD_POLICY = """# Omega DO session: key-only access. Sorted first, because sshd keeps the first value it reads.
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
AuthenticationMethods publickey
"""
BINDING_SCRIPT = """#!/usr/bin/python3
import hashlib, hmac, json, os
key = open(%r).read().split()[1]
nonce = open(%r).read().strip()
digest = hmac.new(nonce.encode(), key.encode(), hashlib.sha256).hexdigest()
temporary = %r + '.tmp'
with open(temporary, 'w') as handle:
    json.dump(dict(schema='omega.do-session.host-binding/1', algorithm='hmac-sha256', hmac=digest), handle)
os.chmod(temporary, 0o644)
os.replace(temporary, %r)
os.unlink(%r)
""" % (HOST_KEY_PATH, NONCE_PATH, BINDING_PATH, BINDING_PATH, NONCE_PATH)
BINDING_INSTALL_PATH = '/usr/local/sbin/omega-host-binding'


class BootstrapRefused(ValueError):
    """This user data must not be sent. No request was made."""


def render_user_data(manifest, role, public_key, binding_nonce):
    """Return the exact user data text for one role, already validated."""
    config = {
        'users': [dict(name=GUEST_USER, gecos='Omega load testing', groups=['sudo'], shell='/bin/bash', lock_passwd=True,
                       sudo='ALL=(ALL) NOPASSWD:ALL', ssh_authorized_keys=[public_key.strip()])],
        'ssh_pwauth': False,
        'disable_root': True,
        'package_update': True,
        'package_upgrade': False,
        'packages': list(PACKAGES[role]),
        'write_files': [
            dict(path='/etc/ssh/sshd_config.d/00-omega-session.conf', permissions='0644', owner='root:root', content=SSHD_POLICY),
            dict(path='/etc/security/limits.d/90-omega-session.conf', permissions='0644', owner='root:root',
                 content='* soft nofile %d\n* hard nofile %d\n' % (NOFILE_LIMIT, NOFILE_LIMIT)),
            dict(path=BINDING_INSTALL_PATH, permissions='0700', owner='root:root', content=BINDING_SCRIPT),
            dict(path=NONCE_PATH, permissions='0600', owner='root:root', content=binding_nonce + '\n'),
        ],
        'runcmd': [
            ['systemctl', 'try-reload-or-restart', 'ssh'],
            ['systemctl', 'enable', '--now', 'systemd-timesyncd'],
            ['install', '-d', '-o', GUEST_USER, '-g', GUEST_USER, '-m', '0750', RESULTS_DIR],
            [BINDING_INSTALL_PATH],
        ],
    }
    text = '#cloud-config\n' + json.dumps(config, indent=1, sort_keys=True) + '\n'
    validate(text, manifest, public_key)
    return text


def validate(text, manifest, public_key):
    """Refuse user data that is oversized, holds credentials, or carries an unexpected key or a source address."""
    if len(text.encode('utf-8')) > MAX_USER_DATA_BYTES:
        raise BootstrapRefused('user data exceeds the 64 KiB provider limit')
    if manifest_mod.scan_for_secrets(text):
        raise BootstrapRefused('user data contains a credential value')
    fields = public_key.split()
    if len(fields) < 2 or fields[0] != 'ssh-ed25519':
        raise BootstrapRefused('only an Ed25519 public key may be uploaded')
    if provider_preflight.ssh_fingerprint(public_key) != manifest['ssh_key']['fingerprint_sha256']:
        raise BootstrapRefused('public key does not have the frozen fingerprint')
    allowlists = manifest['access_allowlists']
    for source in list(allowlists.get('ssh_sources') or []) + list(allowlists.get('operator_udp_sources') or []):
        if str(source).split('/')[0] in text:
            raise BootstrapRefused('user data must not contain an operator address')
