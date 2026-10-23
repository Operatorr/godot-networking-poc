"""Conservative, additive R2 storage allowance; never authorizes cleanup or a lower guard."""
import json
import pathlib
import shlex
import subprocess

GUARD = 8 * 1024**3
LIVE = 96 * 1024**2
JOURNAL = 24 * 1024**2
# tar contains game/ only (live + journal), not original/. Includes gzip expansion.
ARCHIVE = 122 * 1024**2
MARGIN = 32 * 1024**2


def budget(free_bytes, preservation_bytes, staging_bytes):
    if any(type(v) is not int or v < 0 for v in (free_bytes, preservation_bytes, staging_bytes)):
        raise ValueError('Nonnegative exact byte measurements required')
    allowances = dict(original_measurement_copy=preservation_bytes, staging_source_binary_copies=staging_bytes,
                      live_game_payload=LIVE, journal=JOURNAL, role_only_archive=ARCHIVE, margin=MARGIN)
    total = sum(allowances.values())
    return dict(free_bytes=free_bytes, unchanged_guard_bytes=GUARD, allowances=allowances,
                combined_bytes=total, remaining_above_guard_after_allowance=free_bytes-GUARD-total,
                passed=free_bytes-GUARD >= total)


def sparse_checkout_allowance(revision, bundle_bytes, binary_bytes):
    tree = subprocess.check_output(['git', 'ls-tree', '-rlz', revision])
    selected = [r for r in tree.split(b'\0') if r and
                (r.split(b'\t', 1)[1].startswith(b'rust/') or b'/' not in r.split(b'\t', 1)[1])]
    blobs = sum(((int(r.split(b'\t')[0].split()[-1])+4095)//4096)*4096 for r in selected)
    # Complete source blobs, real binary copies, uploaded bundle plus fetched objects,
    # and 16 MiB for directories/index/refs/source staging/collector executable.
    return blobs + binary_bytes + 2*bundle_bytes + 16*1024**2


def probe_command(original_binary, additional_staging_bytes):
    code = '''import json,os,pathlib,subprocess
p=pathlib.Path('/var/lib/omega-measure/current');fs=list(p.rglob('*'))
assert p.is_dir() and not p.is_symlink()
assert all(not f.is_symlink() and (f.is_file() or f.is_dir()) for f in fs)
allocated=int(subprocess.check_output(['du','-s','-B1',str(p)]).split()[0])
copy_bytes=sum(((f.stat().st_size+4095)//4096)*4096 if f.is_file() else 4096 for f in fs)+4096
v=os.statvfs('/home/deploy')
print(json.dumps(dict(free_bytes=v.f_bavail*v.f_frsize,
 preservation_bytes=max(allocated,copy_bytes),original_allocated_bytes=allocated,
 original_logical_bytes=sum(f.stat().st_size for f in fs if f.is_file()),
 staging_bytes=EXTRA+((pathlib.Path(BINARY).stat().st_size+4095)//4096)*4096)))
'''.replace('EXTRA', repr(additional_staging_bytes)).replace('BINARY', repr(original_binary))
    return 'python3 -c '+shlex.quote(code)


def check(ssh, original_binary, additional_staging_bytes, output):
    measurement = json.loads(ssh('game', probe_command(original_binary, additional_staging_bytes)))
    result = budget(**{k:measurement[k] for k in ('free_bytes', 'preservation_bytes', 'staging_bytes')})
    result['measurement'] = measurement
    with pathlib.Path(output).open('x') as stream:
        json.dump(result, stream, indent=2)
    if not result['passed']:
        raise RuntimeError('Combined diagnostic storage allowance cannot fit above unchanged 8 GiB guard')
    return result
