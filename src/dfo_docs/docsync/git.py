"""The git runner and command environment shared by `prs` and `state`.

`Git` runs one git command in a checkout with a fixed environment. `command_env` builds
that environment: the process environment plus, when a token is given, a credential
helper for github.com that reads the token from `DFO_BOT_TOKEN`, so the token never
reaches a config file or a remote URL.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

# The environment variable the credential helper reads the token from, and the one
# `prs.propose_edits` reads the push token from when none is passed. CI sets it to a
# dfo-bot installation token; local runs leave it unset and use the user's own git and
# gh credentials.
TOKEN_ENV = "DFO_BOT_TOKEN"

_TOKEN_HELPER = (
    '!f() { test "$1" = get || return 0; echo username=x-access-token; '
    f'echo "password=${TOKEN_ENV}"; }}; f'
)


class CommandError(RuntimeError):
    """A git or gh command failed; carries the command and its stderr."""

    def __init__(self, command: Sequence[str], stderr: str) -> None:
        self.command = tuple(command)
        self.stderr = stderr.strip()
        super().__init__(f"{' '.join(self.command)} failed: {self.stderr}")


class GitError(CommandError):
    """A git command failed."""


@dataclass(frozen=True)
class Git:
    """Runs git commands in `root` with the environment `env`."""

    root: Path
    env: Mapping[str, str]

    def run_unchecked(
        self, *args: str, stdin: str | None = None, env: Mapping[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run `git <args>`; the caller reads the exit status."""
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            env={**self.env, **(env or {})},
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

    def run(
        self, *args: str, stdin: str | None = None, env: Mapping[str, str] | None = None
    ) -> str:
        """Run `git <args>` and return its stdout.

        Args:
            args: The git arguments.
            stdin: Text to feed the command.
            env: Variables added to the environment for this command only.

        Raises:
            GitError: the command exited non-zero; carries its stderr.
        """
        result = self.run_unchecked(*args, stdin=stdin, env=env)
        if result.returncode != 0:
            raise GitError(["git", *args], result.stderr)
        return result.stdout


def command_env(token: str | None) -> dict[str, str]:
    """The environment for git and gh, carrying `token` when one is given.

    The token goes in `DFO_BOT_TOKEN` and `GH_TOKEN`. GIT_CONFIG_COUNT entries, appended
    after any the caller already set, first clear the helpers git reads from config
    files and then add one for github.com that answers `get` from `DFO_BOT_TOKEN`.
    """
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    if token is None:
        return env

    count = int(env.get("GIT_CONFIG_COUNT", "0") or "0")
    entries = [
        ("credential.helper", ""),
        ("credential.https://github.com.helper", _TOKEN_HELPER),
    ]
    for offset, (key, value) in enumerate(entries):
        env[f"GIT_CONFIG_KEY_{count + offset}"] = key
        env[f"GIT_CONFIG_VALUE_{count + offset}"] = value
    env["GIT_CONFIG_COUNT"] = str(count + len(entries))
    env[TOKEN_ENV] = token
    env["GH_TOKEN"] = token
    return env
