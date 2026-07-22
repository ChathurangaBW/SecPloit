from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.policy import Policy, PolicyError


def make_policy() -> Policy:
    config = Settings(
        target_allowlist="127.0.0.1,app.lab.internal,*.range.local",
        command_allowlist="curl,nmap,dig,grep,cat",
        database_path=Path("data/test.db"),
        workspace_root=Path("data/test-workspaces"),
    )
    return Policy(config)


def test_accepts_exact_and_wildcard_targets() -> None:
    policy = make_policy()

    assert policy.validate_target("https://app.lab.internal").host == "app.lab.internal"
    assert policy.validate_target("node.range.local").host == "node.range.local"


def test_rejects_out_of_scope_target() -> None:
    policy = make_policy()

    with pytest.raises(PolicyError, match="outside TARGET_ALLOWLIST"):
        policy.validate_target("example.com")


def test_network_command_must_reference_job_target() -> None:
    policy = make_policy()
    target = policy.validate_target("app.lab.internal")

    with pytest.raises(PolicyError, match="reference the job target"):
        policy.validate_command("nmap -sV example.com", target)


def test_rejects_shell_chaining() -> None:
    policy = make_policy()
    target = policy.validate_target("app.lab.internal")

    with pytest.raises(PolicyError, match="Shell construct"):
        policy.validate_command("curl https://app.lab.internal && id", target)


def test_rejects_write_oriented_curl() -> None:
    policy = make_policy()
    target = policy.validate_target("app.lab.internal")

    with pytest.raises(PolicyError, match="blocked"):
        policy.validate_command(
            "curl -X POST https://app.lab.internal/login",
            target,
        )


def test_accepts_read_only_commands() -> None:
    policy = make_policy()
    target = policy.validate_target("app.lab.internal")

    assert policy.validate_command(
        "curl -I https://app.lab.internal",
        target,
    ) == ["curl", "-I", "https://app.lab.internal"]

    assert policy.validate_command(
        "nmap -sV app.lab.internal",
        target,
    ) == ["nmap", "-sV", "app.lab.internal"]
