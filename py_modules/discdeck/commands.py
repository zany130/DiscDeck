"""Subprocess wrapper that refuses mutating commands."""

from __future__ import annotations

import os
import select
import subprocess
import time
from dataclasses import dataclass

from typing import Any, Callable

from discdeck.security import assert_readonly_argv


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    code: int
    stdout: str
    stderr: str


class CommandRunner:
    def __init__(self, policy: Any = assert_readonly_argv) -> None:
        self.policy = policy

    def __call__(
        self,
        argv: list[str],
        timeout: float = 5,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        pass_fds: tuple[int, ...] = (),
        pty: bool = False,
    ) -> CommandResult:
        self.policy(argv)
        if pty and not pass_fds:
            return _capture_pty(argv, timeout, env, cwd)
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                pass_fds=pass_fds,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", "not found")
        except OSError as exc:
            return CommandResult(argv, 127, "", str(exc)[:200])
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or "timeout"
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return CommandResult(argv, 124, stdout, stderr)
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


class ScriptedRunner:
    """Test double. Records calls and never invokes the operating system."""

    def __init__(self, responses: dict[tuple[str, ...], CommandResult] | None = None, policy: Callable[[list[str]], None] = assert_readonly_argv) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.passed_fds: list[tuple[int, ...]] = []
        self.cwds: list[str | None] = []
        self.envs: list[dict[str, str] | None] = []
        self.ptys: list[bool] = []
        self.policy = policy

    def __call__(
        self,
        argv: list[str],
        timeout: float = 5,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
        pass_fds: tuple[int, ...] = (),
        pty: bool = False,
    ) -> CommandResult:
        self.policy(argv)
        self.calls.append(list(argv))
        self.passed_fds.append(tuple(pass_fds))
        self.cwds.append(cwd)
        self.envs.append(env)
        self.ptys.append(pty)
        match = self.responses.get(tuple(argv))
        if match is None:
            return CommandResult(list(argv), 127, "", "not found")
        return match


def open_pty_pair() -> tuple[int, int] | None:
    """Open a terminal without importing the stdlib pty module.

    Decky's Python does not include the termios extension, and ``import pty``
    loads termios. libc openpty does not need that module.
    """
    try:
        import ctypes
        import ctypes.util
    except ImportError:
        return None
    names: list[str] = []
    for library in ("util", "c"):
        found = ctypes.util.find_library(library)
        if found and found not in names:
            names.append(found)
    for fallback in ("libutil.so.1", "libc.so.6"):
        if fallback not in names:
            names.append(fallback)
    for name in names:
        try:
            library = ctypes.CDLL(name, use_errno=True)
            opener = library.openpty
        except (OSError, AttributeError):
            continue
        master = ctypes.c_int()
        slave = ctypes.c_int()
        opener.argtypes = [
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        opener.restype = ctypes.c_int
        if opener(ctypes.byref(master), ctypes.byref(slave), None, None, None) != 0:
            continue
        return master.value, slave.value
    return None


def _capture_pty(argv: list[str], timeout: float, env: dict[str, str] | None, cwd: str | None) -> CommandResult:
    """Run one command on a terminal so a distrobox wrapper behaves as it does in a shell."""
    pair = open_pty_pair()
    if pair is None:
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as exc:
            return CommandResult(argv, 127, "", str(exc)[:200])
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout or ""
            stderr = exc.stderr or "timeout"
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", "replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", "replace")
            return CommandResult(argv, 124, stdout, stderr)
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)
    master, slave = pair
    try:
        try:
            process = subprocess.Popen(
                argv,
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=env,
                close_fds=True,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", "not found")
        except OSError as exc:
            return CommandResult(argv, 127, "", str(exc)[:200])
        finally:
            os.close(slave)
        output = bytearray()
        deadline = time.monotonic() + timeout
        while True:
            code = process.poll()
            remaining = 0.0 if code is not None else deadline - time.monotonic()
            if code is None and remaining <= 0:
                process.kill()
                process.wait(timeout=2)
                return CommandResult(argv, 124, output.decode("utf-8", "replace"), "timeout")
            readable, _, _ = select.select([master], [], [], remaining)
            if readable:
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    chunk = b""
                if chunk:
                    output.extend(chunk)
                    continue
            if code is not None:
                return CommandResult(argv, code, output.decode("utf-8", "replace"), "")
    finally:
        os.close(master)
