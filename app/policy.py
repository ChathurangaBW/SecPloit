from __future__ import annotations

import ipaddress
import os
import shlex
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import Settings, settings


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedTarget:
    original: str
    host: str


class Policy:
    NETWORK_COMMANDS = {
        "curl",
        "nmap",
        "dig",
        "nslookup",
        "whois",
        "openssl",
    }

    FORBIDDEN_SHELL_TOKENS = (
        "\n",
        "\r",
        ";",
        "&&",
        "||",
        "`",
        "$(",
        "${",
        "<(",
        ">(",
        "\x00",
    )

    CURL_WRITE_LONG_FLAGS = {
        "--data",
        "--data-ascii",
        "--data-binary",
        "--data-raw",
        "--form",
        "--upload-file",
    }

    INTRUSIVE_NMAP_TERMS = {
        "brute",
        "dos",
        "exploit",
        "external",
        "fuzzer",
        "intrusive",
        "malware",
    }

    def __init__(self, config: Settings = settings) -> None:
        self.config = config

    def validate_target(self, target: str) -> ValidatedTarget:
        value = target.strip()
        if not value:
            raise PolicyError("Target is empty")

        parsed = urlparse(value if "://" in value else f"//{value}")
        host = parsed.hostname
        if not host:
            raise PolicyError("Target must contain a hostname or IP address")

        host = host.lower().rstrip(".")
        if not self._host_is_allowed(host):
            raise PolicyError(
                f"Target '{host}' is outside TARGET_ALLOWLIST"
            )

        return ValidatedTarget(original=value, host=host)

    def _host_is_allowed(self, host: str) -> bool:
        for rule in self.config.allowed_targets:
            if rule.startswith("*."):
                suffix = rule[1:]
                if host.endswith(suffix) and host != suffix.lstrip("."):
                    return True
            elif host == rule:
                return True
        return False

    def validate_command(self, command: str, target: ValidatedTarget) -> list[str]:
        if not command.strip():
            raise PolicyError("Command is empty")

        for token in self.FORBIDDEN_SHELL_TOKENS:
            if token in command:
                raise PolicyError(f"Shell construct is not allowed: {token!r}")

        try:
            arguments = shlex.split(command, posix=True)
        except ValueError as exc:
            raise PolicyError(f"Invalid command syntax: {exc}") from exc

        if not arguments:
            raise PolicyError("Command is empty")

        executable = os.path.basename(arguments[0])
        if executable not in self.config.allowed_commands:
            raise PolicyError(f"Command '{executable}' is not allowlisted")

        if executable in self.NETWORK_COMMANDS:
            self._require_target_reference(arguments, target)

        if executable == "curl":
            self._validate_curl(arguments)

        if executable == "nmap":
            self._validate_nmap(arguments)

        return arguments

    def _require_target_reference(
        self,
        arguments: list[str],
        target: ValidatedTarget,
    ) -> None:
        for argument in arguments[1:]:
            normalized = argument.strip("[]").rstrip(".")

            if normalized == target.host or normalized.startswith(f"{target.host}:"):
                return

            if "://" in argument:
                parsed = urlparse(argument)
                if parsed.hostname and parsed.hostname.lower().rstrip(".") == target.host:
                    return

            try:
                ip = ipaddress.ip_address(normalized)
                if str(ip) == target.host:
                    return
            except ValueError:
                pass

        raise PolicyError(
            "Network command must reference the job target literally"
        )

    def _validate_curl(self, arguments: list[str]) -> None:
        for argument in arguments:
            lowered = argument.lower()
            if argument in {"-d", "-F", "-T"} or lowered in self.CURL_WRITE_LONG_FLAGS:
                raise PolicyError(
                    f"Write-oriented curl option is blocked: {argument}"
                )

        for index, argument in enumerate(arguments[:-1]):
            if argument in {"-X", "--request"}:
                method = arguments[index + 1].upper()
                if method not in {"GET", "HEAD", "OPTIONS"}:
                    raise PolicyError(f"HTTP method is blocked: {method}")

    def _validate_nmap(self, arguments: list[str]) -> None:
        flattened = " ".join(arguments).lower()
        for term in self.INTRUSIVE_NMAP_TERMS:
            if term in flattened:
                raise PolicyError(
                    f"Intrusive Nmap script category is blocked: {term}"
                )
