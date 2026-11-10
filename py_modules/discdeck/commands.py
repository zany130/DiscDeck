"""Subprocess wrapper that refuses mutating commands."""

from __future__ import annotations

import subprocess
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

    def __call__(self, argv: list[str], timeout: float = 5, env: dict[str, str] | None = None) -> CommandResult:
        self.policy(argv)
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", "not found")
        except subprocess.TimeoutExpired as exc:
            return CommandResult(argv, 124, exc.stdout or "", exc.stderr or "timeout")
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


class ScriptedRunner:
    """Test double. Records calls and never invokes the operating system."""

    def __init__(self, responses: dict[tuple[str, ...], CommandResult] | None = None, policy: Callable[[list[str]], None] = assert_readonly_argv) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []
        self.policy = policy

    def __call__(self, argv: list[str], timeout: float = 5, env: dict[str, str] | None = None) -> CommandResult:
        del env
        self.policy(argv)
        self.calls.append(list(argv))
        match = self.responses.get(tuple(argv))
        if match is None:
            return CommandResult(list(argv), 127, "", "not found")
        return match
