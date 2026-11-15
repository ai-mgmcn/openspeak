"""Small file helpers: process checks, removing and replacing files, owner-only writes."""

import contextlib
import os


def pid_alive(pid):
    """Whether a process with this pid is running, ours or anyone's."""
    try:
        os.kill(pid, 0)  # signal 0 sends nothing: only the existence check
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # someone else's process
    return True


def remove(path):
    """Delete a file; one that's already gone is fine."""
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


replace = os.replace


def private_dir(path):
    """Make a directory (and any above it that's missing) only its owner can enter."""
    os.makedirs(path, mode=0o700, exist_ok=True)
    os.chmod(path, 0o700)  # one made by an older version, or before the umask applied


def write_private(path, text):
    """Write a text file only its owner can read (keys, transcripts, reports)."""
    # Written beside it and moved over: someone reading it meanwhile gets the old file or the new, never half.
    tmp = f"{path}.{os.getpid()}.tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
    replace(tmp, path)
