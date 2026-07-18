"""Input validation & SSRF guards.

Because /download ultimately makes an outbound HTTP request on the
server's behalf, we must not let a caller point it at internal
infrastructure (169.254.169.254, localhost, RFC1918 ranges, etc).
"""
import ipaddress
import socket
from urllib.parse import urlparse

from app.core.config import get_settings

settings = get_settings()


class UnsafeURLError(ValueError):
    pass


def _is_blocked_ip(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        # Can't resolve -> let it fail naturally downstream, not our job to block
        return False

    for family, _, _, _, sockaddr in infos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def assert_public_http_url(raw_url: str) -> str:
    """Raises UnsafeURLError if the URL is not a safe, public http(s) URL."""
    parsed = urlparse(raw_url)

    if parsed.scheme not in settings.ALLOWED_URL_SCHEMES:
        raise UnsafeURLError(f"Unsupported scheme: {parsed.scheme!r}")

    host = (parsed.hostname or "").lower()
    if not host:
        raise UnsafeURLError("URL is missing a host")

    if any(host == s.lstrip(".") or host.endswith(s) for s in settings.BLOCKED_HOST_SUFFIXES):
        raise UnsafeURLError(f"Host {host!r} is blocked")

    if _is_blocked_ip(host):
        raise UnsafeURLError(f"Host {host!r} resolves to a non-public address")

    return raw_url
