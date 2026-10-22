"""Publish an owned experiment file without exposing a partial transfer to readers."""
import shlex


def publish_file(copy, ssh, role, local_path, remote_path):
    """Use a sibling temporary file: the final rename is within one filesystem.

    The caller owns the experiment namespace and serializes publications. A failed
    copy leaves the old destination (or absence) intact and its partial evidence
    available for diagnosis; publication errors propagate to the controller.
    """
    temporary = str(remote_path) + '.partial'
    copy(role, local_path, temporary)
    ssh(role, 'mv -- ' + shlex.quote(temporary) + ' ' + shlex.quote(str(remote_path)))
