#!/usr/bin/env python3
"""Hold one AC-only macOS sleep assertion through the A-share session."""

from datetime import datetime, time
from pathlib import Path
import fcntl
import os
import subprocess
import sys
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo('Asia/Shanghai')
SESSION_START = time(9, 25)
SESSION_END = time(15, 35)


def session_seconds(now: datetime) -> int:
    """Return seconds remaining in the Shanghai weekday guard window."""
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('clock requires timezone')
    local = now.astimezone(SHANGHAI)
    if local.weekday() >= 5 or local.time() < SESSION_START or local.time() >= SESSION_END:
        return 0
    end = local.replace(hour=SESSION_END.hour, minute=SESSION_END.minute,
                        second=0, microsecond=0)
    return max(0, int((end - local).total_seconds()))


def _guard_paths(state_root: Path) -> tuple[Path, Path]:
    state_root = Path(state_root)
    if state_root.is_symlink():
        raise ValueError('state root symlink is not supported')
    guard = state_root / 'market-dashboard'
    if guard.is_symlink():
        raise ValueError('guard directory symlink is not supported')
    guard.mkdir(parents=True, exist_ok=True, mode=0o700)
    guard.chmod(0o700)
    lock = guard / 'awake.lock'
    if lock.is_symlink():
        raise ValueError('guard lock symlink is not supported')
    return guard, lock


def hold_awake(state_root: Path, *, now: datetime | None = None,
               runner=subprocess.run) -> str:
    """Hold an exclusive lock while macOS prevents AC-powered idle sleep."""
    seconds = session_seconds(now or datetime.now().astimezone())
    if seconds <= 0:
        return 'outside-session'
    _, lock_path = _guard_paths(Path(state_root))
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'already-held'
        runner(['/usr/bin/caffeinate', '-s', '-t', str(seconds)], check=False)
        return 'complete'
    finally:
        os.close(descriptor)


def ensure_guard(state_root: Path, *, now: datetime | None = None,
                 launcher=subprocess.Popen) -> str:
    """Start the detached lock holder once; competing holders exit safely."""
    if session_seconds(now or datetime.now().astimezone()) <= 0:
        return 'outside-session'
    _guard_paths(Path(state_root))
    launcher([sys.executable, str(Path(__file__).resolve()), 'hold', str(state_root)],
             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
             start_new_session=True, close_fds=True)
    return 'started'


def main(argv=None) -> int:
    values = list(argv if argv is not None else sys.argv[1:])
    if len(values) != 2 or values[0] not in {'ensure', 'hold'}:
        return 2
    try:
        if values[0] == 'ensure':
            ensure_guard(Path(values[1]))
        else:
            hold_awake(Path(values[1]))
    except (OSError, ValueError, subprocess.SubprocessError):
        print('market dashboard awake guard failed', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
