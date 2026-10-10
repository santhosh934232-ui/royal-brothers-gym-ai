"""Shared request-origin validation helpers."""

from urllib.parse import urlsplit


def _origin_key(value):
    try:
        parsed = urlsplit(value)
        scheme = parsed.scheme.lower()
        if (scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment):
            return None
        port = parsed.port
        if port is None:
            port = 443 if scheme == "https" else 80
        return scheme, parsed.hostname.lower(), port
    except (TypeError, ValueError):
        return None


def is_same_origin(supplied_origin, request_url):
    """Compare HTTP(S) origins by scheme, hostname and effective port."""
    supplied = _origin_key(supplied_origin)
    return supplied is not None and supplied == _origin_key(request_url)
