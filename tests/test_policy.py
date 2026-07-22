from __future__ import annotations

import pytest

from app.config import Settings
from app.policy import Policy, PolicyError


def policy() -> Policy:
    return Policy(
        Settings(
            OPENAI_API_KEY="test",
            SECPLOIT_TARGET_ALLOWLIST="juice-shop,dvwa,localhost,127.0.0.1,*.lab.internal",
        )
    )


@pytest.mark.parametrize(
    "target",
    [
        "http://juice-shop:3000",
        "dvwa",
        "localhost:8000",
        "127.0.0.1",
        "api.lab.internal",
    ],
)
def test_allows_range_targets(target: str) -> None:
    assert policy().validate_target(target).host


@pytest.mark.parametrize(
    "target",
    ["example.com", "8.8.8.8", "169.254.169.254", "lab.internal"],
)
def test_rejects_out_of_scope_targets(target: str) -> None:
    with pytest.raises(PolicyError):
        policy().validate_target(target)


@pytest.mark.parametrize(
    "command",
    [
        "docker ps",
        "cat /var/run/docker.sock",
        "nsenter -t 1 -m sh",
        "curl http://169.254.169.254/latest/meta-data",
        "mount /dev/sda /mnt",
        "shutdown -h now",
        "rm -rf /",
    ],
)
def test_blocks_host_escape_and_destructive_commands(command: str) -> None:
    with pytest.raises(PolicyError):
        policy().validate_command(command)


@pytest.mark.parametrize(
    "command",
    [
        "nmap -sV juice-shop",
        "python3 - <<'PY'\nprint('research')\nPY",
        "curl -sS http://dvwa | tee response.html",
        "semgrep scan --config auto /workspace/source",
        "gcc poc.c -o poc && ./poc",
    ],
)
def test_allows_general_range_research(command: str) -> None:
    assert policy().validate_command(command) == command
