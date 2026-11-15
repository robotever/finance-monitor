#!/usr/bin/env python3
"""Atomically update the two allowlisted dashboard feature flags in a private dotenv."""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys
import tempfile


ALLOWED = {
    "MARKET_DASHBOARD_ROTATION_SHADOW",
    "MARKET_DASHBOARD_ROTATION_PUBLISH",
}


def fail(message: str) -> "NoReturn":
    raise SystemExit(message)


def main(arguments: list[str]) -> int:
    if len(arguments) < 2:
        fail("usage: set-market-dashboard-flags.py DOTENV KEY=0|1 [...]")
    target = Path(arguments[0])
    if target.is_symlink():
        fail("dotenv must not be a symlink")
    try:
        metadata = target.stat()
    except OSError as error:
        fail(f"dotenv is unavailable: {error.strerror}")
    if not stat.S_ISREG(metadata.st_mode):
        fail("dotenv must be a regular file")

    updates: dict[str, str] = {}
    for assignment in arguments[1:]:
        key, separator, value = assignment.partition("=")
        if not separator or key not in ALLOWED or value not in {"0", "1"}:
            fail("only allowlisted dashboard flags with value 0 or 1 may be changed")
        updates[key] = value

    original = target.read_text(encoding="utf-8")
    lines = original.splitlines()
    output: list[str] = []
    replaced: set[str] = set()
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            if key not in replaced:
                output.append(f"{key}={updates[key]}")
                replaced.add(key)
            continue
        output.append(line)
    for key in arguments[1:]:
        name = key.split("=", 1)[0]
        if name not in replaced:
            output.append(f"{name}={updates[name]}")
            replaced.add(name)
    rendered = "\n".join(output) + "\n"

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        os.chmod(target, 0o600)
        directory = os.open(target.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
