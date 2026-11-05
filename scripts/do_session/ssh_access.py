"""Key-only, host-verified SSH to session guests, and the first contact that pins each host key.

Every connection uses strict checking against one session known_hosts file; no weaker host policy exists in this
module, and a changed address or host key fails. An unknown host key becomes pinned only after the guest proves it received this Droplet's user data, through the nonce binding in
``guest_bootstrap``. An impostor can offer a key, but it cannot compute that binding or reuse our signature,
because an SSH signature is tied to its own connection.

The private key stays where the operator keeps it: this module checks its mode and passes its path to ``ssh``. It
never opens the file. Nothing is forwarded, so a guest never gains the use of it. Remote arguments are quoted, and
output is bounded and redacted before anything else sees it.
"""
import base64
import contextlib
import dataclasses
import hmac
import hashlib
import json
import os
import pathlib
import shlex
import stat
import subprocess
import tempfile
import time

import cleanup_provider
import guest_bootstrap

CONNECT_TIMEOUT_S = 10
KEYSCAN_TIMEOUT_S = 10
MAX_OUTPUT_CHARS = 4 * 1024 * 1024
POLL_S = 1.0
MIN_POLL_S = 0.01
KILL_REAP_S = 2.0       # a killed child that will not be reaped by then is left to the kernel, not waited on
SSH_UNREACHABLE = 255


class HostNotReady(Exception):
    """Not answering, or cloud-init has not published the binding yet. Waiting within the budget is allowed."""


class HostVerificationFailed(Exception):
    """A key was offered that nothing ties to this Droplet. It is never pinned, and the session stops."""


class GuestCommandFailed(Exception):
    def __init__(self, role, step, detail):
        super().__init__('%s %s: %s' % (role, step, detail))
        self.role = role
        self.step = step
        self.detail = detail


@dataclasses.dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


def expected_binding(nonce, host_key_blob):
    return hmac.new(nonce.encode('utf-8'), host_key_blob.encode('utf-8'), hashlib.sha256).hexdigest()


def binding_matches(nonce, host_key_blob, document):
    """The published HMAC must match this nonce and this key. Anything malformed is simply no match."""
    try:
        parsed = json.loads(document)
    except (TypeError, ValueError):
        return False
    if not isinstance(parsed, dict) or not isinstance(parsed.get('hmac'), str) or parsed.get('algorithm') != 'hmac-sha256':
        return False
    return hmac.compare_digest(parsed['hmac'], expected_binding(nonce, host_key_blob))


def require_restricted_key(path):
    """Metadata only: the private key's contents are never read by this code."""
    info = os.stat(os.path.expanduser(str(path)))
    if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) & 0o077:
        raise ValueError('the SSH private key must be a regular file with mode 0600')


def bounded_command(popen, argv, timeout_s, on_wait, sleep, monotonic, poll_s):
    """Poll rather than block, so a build can run for minutes while the controller lease is kept alive.

    ``timeout_s`` becomes one absolute cutoff before the child exists. It is checked again after every callback, each sleep is cut to
    what is left, and a result first seen at or past the cutoff is refused even if the child had exited in time: nobody can show that
    it had, and a caller with a deadline may not act on it. This is a best effort on an ordinary kernel, not a real-time promise,
    but the overrun is now one scheduling delay and one reap rather than a whole poll.
    """
    deadline = monotonic() + timeout_s
    # Regular temporary files cannot fill a pipe and block the child before it exits.
    # They also keep output out of memory while lease callbacks continue to run.
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)

        def oversized():
            return any(os.fstat(stream.fileno()).st_size > MAX_OUTPUT_CHARS for stream in (stdout, stderr))

        def killed(reason):
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.communicate(timeout=KILL_REAP_S)
            return CommandResult(None, '', reason)
        try:
            while True:
                exited = process.poll() is not None
                if monotonic() >= deadline:
                    return killed('timed out after %s s' % timeout_s)
                if exited:
                    break
                if oversized():
                    return killed('command output limit exceeded')
                if on_wait is not None:
                    on_wait()
                remaining = deadline - monotonic()
                if remaining > 0:
                    # Halved, so a child that ends in time is seen in time, and never slept past.
                    sleep(min(poll_s, remaining if remaining <= MIN_POLL_S else max(remaining / 2, MIN_POLL_S)))
        except BaseException:
            # No local ssh process outlives lease loss or cancellation.
            killed('cancelled')
            raise
        process.communicate()
        if oversized():
            return CommandResult(None, '', 'command output limit exceeded')
        stdout.seek(0)
        stderr.seek(0)
        out, err = stdout.read(MAX_OUTPUT_CHARS), stderr.read(MAX_OUTPUT_CHARS)
        return CommandResult(process.returncode, out.decode('utf-8', 'replace'),
                             cleanup_provider.redact(err.decode('utf-8', 'replace')))


class GuestAccess:
    """What every access path shares: the pinning decision. Subclasses supply the three network steps."""
    UNIT_MODE = 'systemd'       # how the guest bounds a run's processes; only local fixtures run without systemd units

    def __init__(self):
        self.pins = {}

    def _scan_host_key(self, address):
        """(key type, base64 blob) offered by this address, or None when nothing answered."""
        raise NotImplementedError

    def _read_binding(self, role, address, host_key):
        """The published binding document, read over a connection that requires exactly ``host_key``."""
        raise NotImplementedError

    def _pin(self, role, address, host_key):
        raise NotImplementedError

    def pin_host(self, role, address, nonce):
        """Verify first contact and pin. Returns the pinned key's fingerprint for the provenance record."""
        offered = self._scan_host_key(address)
        if offered is None:
            raise HostNotReady(role + ' offered no host key yet')
        if offered[0] != 'ssh-ed25519':
            raise HostVerificationFailed(role + ' offered a %s host key' % offered[0])
        document = self._read_binding(role, address, offered)
        if document is None:
            raise HostNotReady(role + ' has not published its binding yet')
        if not binding_matches(nonce, offered[1], document):
            raise HostVerificationFailed(role + ' host key is not bound to this Droplet')
        self._pin(role, address, offered)
        self.pins[role] = address
        digest = hashlib.sha256(base64.b64decode(offered[1])).digest()
        return dict(address=address, host_key_type=offered[0], host_key_sha256='SHA256:' + base64.b64encode(digest).decode('ascii').rstrip('='))

    def _pinned_addresses(self):
        return set(self.pins.values())

    def restore_pins(self, addresses):
        """A later controller inherits pins and never makes one: its first-contact nonces are gone with the earlier process."""
        pinned = self._pinned_addresses()
        for role, address in addresses.items():
            if address not in pinned:
                raise HostVerificationFailed('%s at %s has no pinned host key' % (role, address))
            self.pins[role] = address

    def run(self, role, argv, timeout_s, on_wait=None):
        raise NotImplementedError

    def put(self, role, local_path, remote_path, timeout_s, on_wait=None):
        raise NotImplementedError

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        raise NotImplementedError


class SshAccess(GuestAccess):
    def __init__(self, private_key_path, session_dir, user=guest_bootstrap.GUEST_USER, popen=subprocess.Popen, sleep=time.sleep,
                 monotonic=time.monotonic):
        super().__init__()
        require_restricted_key(private_key_path)
        self.private_key_path = os.path.expanduser(str(private_key_path))
        self.session_dir = pathlib.Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.known_hosts = self.session_dir / 'known_hosts'
        self.user = user
        self.popen = popen
        self.sleep = sleep
        self.monotonic = monotonic

    def options(self, known_hosts=None):
        known = str(known_hosts or self.known_hosts)
        return ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + known,
                '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'UpdateHostKeys=no', '-o', 'HostKeyAlgorithms=ssh-ed25519',
                '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no', '-o', 'PubkeyAuthentication=yes',
                '-o', 'PreferredAuthentications=publickey', '-o', 'IdentitiesOnly=yes', '-o', 'IdentityAgent=none',
                '-o', 'ForwardAgent=no', '-o', 'ForwardX11=no', '-o', 'ClearAllForwardings=yes',
                '-o', 'ConnectTimeout=' + str(CONNECT_TIMEOUT_S), '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=4',
                '-i', self.private_key_path]

    def _execute(self, argv, timeout_s, on_wait):
        return bounded_command(self.popen, argv, timeout_s, on_wait, self.sleep, self.monotonic, POLL_S)

    def _scan_host_key(self, address):
        result = self._execute(['ssh-keyscan', '-T', str(KEYSCAN_TIMEOUT_S), '-t', 'ed25519', address], KEYSCAN_TIMEOUT_S + 5, None)
        for line in result.stdout.splitlines():
            fields = line.split()
            if len(fields) >= 3 and not line.startswith('#') and fields[0] == address:
                return fields[1], fields[2]
        return None

    def _read_binding(self, role, address, host_key):
        candidate = self.session_dir / ('known_hosts.' + role + '.candidate')
        candidate.write_text('%s %s %s\n' % (address, host_key[0], host_key[1]))
        result = self._execute(['ssh'] + self.options(candidate) + [self.user + '@' + address, 'cat', guest_bootstrap.BINDING_PATH],
                               CONNECT_TIMEOUT_S + 20, None)
        candidate.unlink()
        return result.stdout if result.returncode == 0 else None

    def _pin(self, role, address, host_key):
        with self.known_hosts.open('a', encoding='utf-8') as handle:
            handle.write('%s %s %s\n' % (address, host_key[0], host_key[1]))
        os.chmod(str(self.known_hosts), 0o600)

    def _pinned_addresses(self):
        try:
            lines = self.known_hosts.read_text().splitlines()
        except OSError:
            return set()
        return {line.split()[0] for line in lines if line.split()}

    def _address(self, role):
        if role not in self.pins:
            raise GuestCommandFailed(role, 'connect', 'no pinned host key: first contact must pass before any command')
        return self.pins[role]

    def run(self, role, argv, timeout_s, on_wait=None):
        remote = ' '.join(shlex.quote(str(part)) for part in argv)
        return self._execute(['ssh'] + self.options() + [self.user + '@' + self._address(role), remote], timeout_s, on_wait)

    def put(self, role, local_path, remote_path, timeout_s, on_wait=None):
        target = self.user + '@' + self._address(role) + ':' + str(remote_path)
        return self._execute(['scp', '-q'] + self.options() + [str(local_path), target], timeout_s, on_wait)

    def get(self, role, remote_path, local_path, timeout_s, on_wait=None):
        source = self.user + '@' + self._address(role) + ':' + str(remote_path)
        return self._execute(['scp', '-q'] + self.options() + [source, str(local_path)], timeout_s, on_wait)
