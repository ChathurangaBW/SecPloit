from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from app.config import Settings, settings


class PolicyError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedTarget:
    original: str
    host: str
    port: int | None
    scheme: str | None


class Policy:
    """Infrastructure-backed private-range policy."""

    FORBIDDEN_PATTERNS = (
        r"(?:^|\s)(?:docker|podman|kubectl|ctr|crictl)\b",
        r"/var/run/docker\.sock",
        r"(?:^|\s)(?:mount|umount|nsenter|unshare|chroot)\b",
        r"(?:^|\s)(?:shutdown|reboot|poweroff|halt)\b",
        r"(?:^|\s)(?:systemctl|service)\b",
        r"(?:^|\s)(?:iptables|ip6tables|nft)\b",
        r"(?:^|\s)(?:useradd|adduser|usermod|passwd|visudo)\b",
        r"(?:^|\s)(?:apt|apt-get|apk|dnf|yum|pacman)\b",
        r"(?:^|\s)(?:ssh|scp|sftp|rsync)\b",
        r"169\.254\.169\.254",
        r"metadata\.google\.internal",
        r"/proc/(?:1|self)/(?:root|fd|mem)",
        r"/sys/kernel",
        r"(?:^|\s)dd\s+if=",
        r"(?:^|\s)mkfs(?:\.|\s)",
        r":\(\)\s*\{\s*:\|:&\s*\};:",
    )

    DESTRUCTIVE_PATTERNS = (
        r"\brm\s+(?:-[^\s]*r[^\s]*f|-[^\s]*f[^\s]*r)\s+/(?:\s|$)",
        r"\bwipefs\b",
        r"\bshred\b",
        r"\bkill\s+-9\s+1\b",
    )

    def __init__(self, config: Settings = settings) -> None:
        self.config = config
        self._forbidden = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.FORBIDDEN_PATTERNS
        ]
        self._destructive = [
            re.compile(pattern, re.IGNORECASE) for pattern in self.DESTRUCTIVE_PATTERNS
        ]

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
            raise PolicyError(f"Target '{host}' is outside SECPLOIT_TARGET_ALLOWLIST")

        if self._is_public_ip(host):
            raise PolicyError("Public IP targets are disabled in the bundled range profile")

        return ValidatedTarget(
            original=value,
            host=host,
            port=parsed.port,
            scheme=parsed.scheme or None,
        )

    def validate_command(self, command: str) -> str:
        value = command.strip()
        if not value:
            raise PolicyError("Command is empty")
        if "\x00" in value:
            raise PolicyError("NUL bytes are not allowed")
        if len(value) > 12000:
            raise PolicyError("Command exceeds the 12,000 character limit")

        for pattern in self._forbidden:
            if pattern.search(value):
                raise PolicyError(f"Host-escape or administration pattern blocked: {pattern.pattern}")
        for pattern in self._destructive:
            if pattern.search(value):
                raise PolicyError(f"Destructive command pattern blocked: {pattern.pattern}")
        return value

    def _host_is_allowed(self, host: str) -> bool:
        for rule in self.config.allowed_targets:
            if rule.startswith("*."):
                suffix = rule[1:]
                if host.endswith(suffix) and host != suffix.lstrip("."):
                    return True
            elif host == rule:
                return True
        return False

    @staticmethod
    def _is_public_ip(host: str) -> bool:
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return False
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_reserved
        )
