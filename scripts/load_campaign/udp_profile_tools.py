#!/usr/bin/env python3
"""Owned, private-evidence prerequisite provisioning for the frozen profile."""
import json
import os
import pathlib
import re
import subprocess
import time

import run

LOCAL = run.ROOT / 'deployment/hetzner/results/udp-profile-20261021'
PACKAGES = ['linux-perf=7.0.0-38.38', 'libdebuginfod-common=0.194-4',
            'libdebuginfod1t64=0.194-4']


def remote(role, label, command, timeout=180):
    path = LOCAL / (role + '-' + label + '.json')
    if path.exists():
        raise RuntimeError(role + ': evidence label already used; refusing command replay')
    host = run.HOSTS[role]
    result = subprocess.run(['ssh', '-i', str(run.KEY), *run.SSH_OPTIONS,
                             host['ssh_user'] + '@' + host['ipv4'], command],
                            text=True, capture_output=True, timeout=timeout)
    record = dict(utc_ns=time.time_ns(), command=command, rc=result.returncode,
                  stdout=result.stdout, stderr=result.stderr)
    with path.open('x') as stream:
        json.dump(record, stream, indent=2)
    if result.returncode:
        raise RuntimeError(role + ': ' + label + ' failed; private evidence retained')
    return result.stdout


def provision():
    os.umask(0o077)
    LOCAL.mkdir(exist_ok=True, parents=True)
    for role in ('game', 'bots'):
        remote(role, 'package-before', "dpkg-query -W -f='${binary:Package} ${Version} ${Status}\\n'; "
               "systemctl show apt-daily.timer apt-daily-upgrade.timer -p Id -p ActiveState -p UnitFileState; "
               "uname -r; cat /proc/sys/kernel/perf_event_paranoid")
        remote(role, 'package-owner', 'set -e; '
               'sudo -n fuser /var/lib/dpkg/lock-frontend /var/lib/dpkg/lock /var/cache/apt/archives/lock '
               '&& exit 9 || test $? = 1; '
               'test "$(systemctl is-active apt-daily.service)" = inactive; '
               'test "$(systemctl is-active apt-daily-upgrade.service)" = inactive')
        simulation = remote(role, 'package-final-simulation',
                            'apt-get --simulate --no-install-recommends --no-upgrade install ' + ' '.join(PACKAGES))
        installed = re.findall(r'^Inst (\S+)', simulation, re.M)
        if set(installed) != {p.split('=')[0] for p in PACKAGES} or not re.search(
                r'0 upgraded, 3 newly installed, 0 to remove', simulation):
            raise RuntimeError(role + ': unexpected apt plan')
        remote(role, 'package-provenance', 'apt-cache show ' + ' '.join(PACKAGES))
        remote(role, 'package-install',
               'sudo -n env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l '
               'apt-get -y --no-install-recommends --no-upgrade '
               '-o DPkg::Lock::Timeout=0 install ' + ' '.join(PACKAGES))
        remote(role, 'package-after', "dpkg-query -W -f='${binary:Package} ${Version} ${Status}\\n'; "
               'perf version --build-options; sha256sum /usr/bin/perf; '
               'uname -r; cat /proc/sys/kernel/perf_event_paranoid; '
               'systemctl show apt-daily.timer apt-daily-upgrade.timer -p Id -p ActiveState -p UnitFileState')
        print(role + ': minimal perf package installation recorded', flush=True)


if __name__ == '__main__':
    provision()
