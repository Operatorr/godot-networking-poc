"""Read-only verification of loose or explicitly archived closed-run backups."""
import hashlib
import json
import pathlib
import stat
import tarfile

SCHEMA = 'closed-measurement-archive-v1'
PROOF = 'measurement-archive-v1.json'
ARCHIVE = 'measurement-current.tar.gz'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def real_file(path):
    if not path.is_file() or path.is_symlink() or path.resolve() != path:
        raise ValueError('Expected a real regular file: '+str(path))


def relative_name(name):
    value = pathlib.PurePosixPath(name)
    if value.is_absolute() or '..' in value.parts or str(value) != name or name == '.':
        raise ValueError('Noncanonical relative file name')
    return name


def manifest(original):
    path = original/'measurement-sha256.txt'
    real_file(path)
    result = {}
    for line in path.read_text().splitlines():
        sha, name = line.split(None, 1)
        if name.startswith('./'):
            name = name[2:]
        relative_name(name)
        if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha) or name in result:
            raise ValueError('Invalid or duplicate manifest entry')
        result[name] = sha
    if not result:
        raise ValueError('Empty preservation manifest')
    return result


def inventory(directory):
    """Preserve original inode/owner/mode metadata as evidence, alongside bytes."""
    if not directory.is_dir() or directory.is_symlink() or directory.resolve() != directory:
        raise ValueError('Expected real measurement directory')
    files, directories = {}, {}
    for path in [directory, *sorted(directory.rglob('*'))]:
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Linked measurement entry')
        value = path.stat()
        row = dict(device=value.st_dev, inode=value.st_ino, uid=value.st_uid,
                   gid=value.st_gid, mode=stat.S_IMODE(value.st_mode))
        name = str(path.relative_to(directory))
        if path.is_file():
            relative_name(name)
            if value.st_nlink != 1:
                raise ValueError('Hard-linked measurement file')
            files[name] = row | dict(bytes=value.st_size, sha256=digest(path))
        elif path.is_dir():
            directories[name] = row
        else:
            raise ValueError('Special measurement entry')
    return dict(files=files, directories=directories)


def verify_archive(original, proof):
    """Stream every member; never extract paths or trust an archive's own hash list."""
    if proof['schema'] != SCHEMA or proof['namespace'] != original.parent.name:
        raise ValueError('Wrong archive proof identity')
    archive = original/ARCHIVE
    real_file(archive)
    if archive.stat().st_size != proof['archive_bytes'] or digest(archive) != proof['archive_sha256']:
        raise ValueError('Archive identity mismatch')
    if digest(original/'measurement-sha256.txt') != proof['manifest_sha256']:
        raise ValueError('Frozen manifest changed')
    expected = proof['inventory']
    files, directories = expected['files'], expected['directories']
    if len(files) > 4096 or sum(row['bytes'] for row in files.values()) > 1024**3:
        raise ValueError('Archive exceeds bounded verification scope')
    if manifest(original) != {name:row['sha256'] for name,row in files.items()}:
        raise ValueError('Archive proof disagrees with frozen byte manifest')
    seen_files, seen_directories = set(), set()
    with tarfile.open(archive, 'r|gz') as stream:
        for member in stream:
            path = pathlib.PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or
                    str(path) != member.name.rstrip('/') or path.parts[0] != 'measurement-current'):
                raise ValueError('Unsafe archive path')
            name = str(pathlib.PurePosixPath(*path.parts[1:]))
            if member.isfile():
                if name not in files or name in seen_files:
                    raise ValueError('Unexpected or duplicate archived file')
                row = files[name]
                if member.size != row['bytes']:
                    raise ValueError('Archived file size changed')
                with stream.extractfile(member) as payload:
                    if hashlib.file_digest(payload, 'sha256').hexdigest() != row['sha256']:
                        raise ValueError('Archived file bytes changed')
                seen_files.add(name)
            elif member.isdir():
                if name not in directories or name in seen_directories:
                    raise ValueError('Unexpected or duplicate archived directory')
                row = directories[name]
                seen_directories.add(name)
            else:
                raise ValueError('Linked or special archive member')
            if (member.uid, member.gid, member.mode) != (row['uid'], row['gid'], row['mode']):
                raise ValueError('Archived ownership or mode changed')
    if seen_files != set(files) or seen_directories != set(directories):
        raise ValueError('Missing archived entries')
    return dict(mode=SCHEMA, files=len(files), bytes=sum(row['bytes'] for row in files.values()),
                archive_sha256=proof['archive_sha256'], original_inodes_live=False,
                original_inode_metadata_preserved=True)


def verify(original):
    original = pathlib.Path(original)
    marker = original/'measurement-verified'
    real_file(marker)
    if marker.read_bytes() != b'':
        raise ValueError('Preservation marker changed')
    proof_path, loose = original/PROOF, original/'measurement-current'
    if proof_path.exists():
        real_file(proof_path)
        if loose.exists() or loose.is_symlink():
            raise ValueError('Ambiguous loose and archived preservation')
        return verify_archive(original, json.loads(proof_path.read_text()))
    if (original/ARCHIVE).exists():
        raise ValueError('Archive lacks explicit proof')
    observed = inventory(loose)
    if manifest(original) != {name:row['sha256'] for name,row in observed['files'].items()}:
        raise ValueError('Loose measurement differs from frozen manifest')
    return dict(mode='loose', files=len(observed['files']),
                bytes=sum(row['bytes'] for row in observed['files'].values()), original_inodes_live=True)


def verify_all(root):
    result = {}
    for original in sorted(pathlib.Path(root).glob('clean-*/original')):
        if (original/'measurement-verified').exists():
            result[original.parent.name] = verify(original)
    if not result:
        raise ValueError('No preserved original measurements')
    return result
