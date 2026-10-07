"""Measure Linux directory watches and open handles across pointer replacement."""

from __future__ import annotations

import ctypes
import errno
import json
import os
import struct
import tempfile
from pathlib import Path


def events(fd: int) -> list[dict[str, object]]:
    found = []
    try:
        data = os.read(fd, 65536)
    except BlockingIOError:
        return found
    offset = 0
    while offset < len(data):
        wd, mask, cookie, length = struct.unpack_from("iIII", data, offset)
        offset += 16
        name = data[offset:offset + length].rstrip(b"\0").decode(errors="replace")
        offset += length
        found.append({"watch": wd, "mask": hex(mask), "cookie": cookie, "name": name})
    return found


def main() -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), "inotify_init1")
    with tempfile.TemporaryDirectory(prefix="copyroom-fs-activation-") as temp:
        root = Path(temp)
        old = root / "old"
        new = root / "new"
        old.mkdir()
        new.mkdir()
        (old / "file.txt").write_text("old\n")
        (new / "file.txt").write_text("new\n")
        active = root / "active"
        active.symlink_to(old)
        parent_watch = libc.inotify_add_watch(fd, os.fsencode(root), 0x00000FFF)
        old_watch = libc.inotify_add_watch(fd, os.fsencode(active), 0x00000FFF)
        with (active / "file.txt").open("rb") as open_old:
            events(fd)
            replacement = root / "active.next"
            replacement.symlink_to(new)
            os.replace(replacement, active)
            after_replace = events(fd)
            (active / "file.txt").write_text("new changed\n")
            after_write = events(fd)
            old_handle = open_old.read().decode()
        failure = None
        try:
            os.replace(new, old)
        except OSError as exc:
            failure = {"errno": exc.errno, "name": errno.errorcode.get(exc.errno)}
        print(json.dumps({
            "platform": os.uname().sysname,
            "parent_watch": parent_watch,
            "old_directory_watch": old_watch,
            "events_after_replace": after_replace,
            "events_after_new_write": after_write,
            "old_open_handle": old_handle,
            "old_path": (old / "file.txt").read_text(),
            "active_path": (active / "file.txt").read_text(),
            "replace_nonempty_directory": failure,
        }, indent=2, sort_keys=True))
    os.close(fd)


if __name__ == "__main__":
    main()
