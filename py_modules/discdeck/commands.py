"""Subprocess wrapper that refuses mutating commands."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from discdeck.security import assert_readonly_argv


@dataclass(frozen=True)
class CommandResult:
    argv: list[str]
    code: int
    stdout: str
    stderr: str


class CommandRunner:
    def __call__(self, argv: list[str], timeout: float = 5) -> CommandResult:
        assert_readonly_argv(argv)
        try:
            completed = subprocess.run(
                argv,
                shell=False,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except FileNotFoundError:
            return CommandResult(argv, 127, "", "not found")
        except subprocess.TimeoutExpired as exc:
            return CommandResult(argv, 124, exc.stdout or "", exc.stderr or "timeout")
        return CommandResult(argv, completed.returncode, completed.stdout, completed.stderr)


class ScriptedRunner:
    """Test double. Records calls and never invokes the operating system."""

    def __init__(self, responses: dict[tuple[str, ...], CommandResult] | None = None) -> None:
        self.responses = responses or {}
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], timeout: float = 5) -> CommandResult:
        assert_readonly_argv(argv)
        self.calls.append(list(argv))
        match = self.responses.get(tuple(argv))
        if match is None:
            return CommandResult(list(argv), 127, "", "not found")
        return match
