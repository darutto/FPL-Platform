"""
fpl_grounded_assistant.web_fetch
=================================
P2.7: Atomic web_fetch tool — fetch football/FPL news from allowlisted domains.

Security architecture
---------------------
Three-layer protection against prompt-injection, SSRF, and off-topic abuse:

    Layer A — URL allowlist (THIS MODULE): hardcoded domain + path-prefix
              filter.  Only allowlisted URLs proceed; others return
              status="refused" before any network call.
    Layer B — Topic refusal (system-prompt SOURCE_SELECTION_PROMPT, P1.b):
              OFF_TOPIC queries are refused by the LLM before any tool call.
    Layer C — Defensive framing (TOOL_OUTPUT_TRUST line, P1.f.1): the LLM
              is instructed to treat tool output as untrusted data, mitigating
              prompt-injection via attacker-controlled HTML.

This module owns Layer A only.  Layers B and C are already live.

Allowlist semantics
-------------------
``_ALLOWED_DOMAINS`` is a frozenset of exact hostnames (case-insensitive).
No subdomain wildcard expansion — every hostname must appear explicitly.

``_ALLOWED_PATH_PREFIXES`` maps hostname → list of required path prefixes.
A URL's path must start with at least one prefix to pass.  Domains absent
from this dict have no path restriction (any path is allowed).

SSRF guard
----------
After URL parsing, BEFORE any fetch, the hostname is checked:
1. If the hostname is already an IP literal → check directly.
2. If it is a domain → resolve via socket.gethostbyname() → check the IP.
3. Private/loopback/link-local/ULA ranges are refused.
DNS resolution failure also results in refusal (url_invalid).

Fetch behaviour
---------------
- stdlib ``urllib.request`` only — no new dependencies.
- 5-second timeout (non-negotiable, no parameter override).
- User-Agent: ``FPL-Grounded-Assistant/0.1 (architectural-pivot)``
- Only text/* and application/json Content-Types accepted.
- Response body capped at 100 KB (buffered read with limit).
- text_excerpt: first 4000 chars of decoded body; truncated=True if cut.
- Encoding: UTF-8 with errors='replace'.
- No caching — content can change minute-to-minute.

Test injection
--------------
Supply ``fetch_fn`` (signature: url → str) to bypass the actual urllib call.
All validation (allowlist, SSRF) still runs even with a custom fetch_fn.

Registration
------------
Registers ``web_fetch`` in ``TOOL_REGISTRY`` as a side-effect of import.
``__init__.py`` imports this module so ``run_tool("web_fetch", ...)`` works.
"""
from __future__ import annotations

import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from fpl_tool_runner import TOOL_REGISTRY
from fpl_tool_runner.specs import ToolSpec


# ---------------------------------------------------------------------------
# Layer A constants (hardcoded — changing requires a code review)
# ---------------------------------------------------------------------------

#: Exact hostname allowlist (case-insensitive exact match required).
#: Expanding is easy; contracting is hard — keep this STRICT.
_ALLOWED_DOMAINS: frozenset[str] = frozenset({
    "premierleague.com",
    "www.premierleague.com",
    "fantasy.premierleague.com",
    "www.bbc.com",
    "www.bbc.co.uk",
    "theathletic.com",
    "www.theathletic.com",
    "fbref.com",
    "www.fbref.com",
    "transfermarkt.co.uk",
    "www.transfermarkt.co.uk",
})

#: Per-domain required path prefixes.  A URL's path must start with at least
#: one listed prefix.  Domains absent from this dict allow any path.
_ALLOWED_PATH_PREFIXES: dict[str, list[str]] = {
    "www.bbc.com":    ["/sport/football"],
    "www.bbc.co.uk":  ["/sport/football"],
    "theathletic.com":      ["/football"],
    "www.theathletic.com":  ["/football"],
}

#: Fetch timeout in seconds — hard limit, no override parameter.
_FETCH_TIMEOUT_SECONDS: int = 5

#: Maximum bytes to read from the response body.
_MAX_BODY_BYTES: int = 100 * 1024  # 100 KB

#: Maximum characters for text_excerpt in the return value.
_MAX_EXCERPT_CHARS: int = 4000

#: User-Agent header sent with every request.
_USER_AGENT: str = "FPL-Grounded-Assistant/0.1 (architectural-pivot)"

#: Accepted Content-Type prefixes.  Binary/PDF responses are refused.
_ACCEPTED_CONTENT_TYPE_PREFIXES: tuple[str, ...] = (
    "text/",
    "application/json",
)

#: Private/loopback IPv4 networks that must never be fetched (SSRF guard).
_PRIVATE_IPV4_NETWORKS: tuple[ipaddress.IPv4Network, ...] = (
    ipaddress.IPv4Network("127.0.0.0/8"),
    ipaddress.IPv4Network("10.0.0.0/8"),
    ipaddress.IPv4Network("172.16.0.0/12"),
    ipaddress.IPv4Network("192.168.0.0/16"),
    ipaddress.IPv4Network("169.254.0.0/16"),  # link-local / AWS metadata
    ipaddress.IPv4Network("0.0.0.0/8"),
)

#: Private/loopback IPv6 networks (SSRF guard).
_PRIVATE_IPV6_NETWORKS: tuple[ipaddress.IPv6Network, ...] = (
    ipaddress.IPv6Network("::1/128"),        # loopback
    ipaddress.IPv6Network("fe80::/10"),      # link-local
    ipaddress.IPv6Network("fd00::/8"),       # ULA (unique local)
    ipaddress.IPv6Network("fc00::/7"),       # ULA (broader)
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _is_private_ip(ip_str: str) -> bool:
    """Return True if *ip_str* is a private/local/loopback address."""
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return False  # cannot parse → let the caller decide

    if isinstance(addr, ipaddress.IPv4Address):
        return any(addr in net for net in _PRIVATE_IPV4_NETWORKS)
    # IPv6
    return any(addr in net for net in _PRIVATE_IPV6_NETWORKS)


def _check_ssrf(hostname: str) -> "str | None":
    """Resolve *hostname* and check for private/local addresses.

    Returns None if safe, or an error message string if blocked.
    Handles IP literals directly (no DNS lookup needed).
    """
    # Check if the hostname is already an IP literal.
    try:
        ipaddress.ip_address(hostname)
        # It IS an IP literal — check it directly.
        if _is_private_ip(hostname):
            return "URL resolves to private/local network; blocked."
        return None
    except ValueError:
        pass  # not an IP literal — proceed with DNS resolution

    # DNS resolution
    try:
        resolved_ip = socket.gethostbyname(hostname)
    except OSError as exc:
        return f"Could not resolve hostname '{hostname}': {exc}"

    if _is_private_ip(resolved_ip):
        return "URL resolves to private/local network; blocked."
    return None


def _check_path_allowed(hostname: str, path: str) -> bool:
    """Return True if *path* is allowed for *hostname*.

    Domains not in ``_ALLOWED_PATH_PREFIXES`` allow any path.
    Domains in the map require the path to start with at least one prefix.
    """
    prefixes = _ALLOWED_PATH_PREFIXES.get(hostname)
    if prefixes is None:
        return True  # no path restriction for this domain
    return any(path.startswith(prefix) for prefix in prefixes)


def _sorted_allowed_domains() -> list[str]:
    """Return sorted list of allowed domains (for error messages)."""
    return sorted(_ALLOWED_DOMAINS)


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def web_fetch(
    url: str,
    fetch_fn: "Callable[[str], str] | None" = None,
) -> dict[str, Any]:
    """Fetch a URL and return its content. STRICT URL allowlist enforced.

    Args:
        url: full URL to fetch. Must match an allowlisted domain pattern.
        fetch_fn: optional injected fetcher for tests (signature: url → str).
                  When supplied, the urllib fetch is skipped but ALL validation
                  (allowlist, SSRF) still runs.

    Returns one of:

        # Allowlist hit, fetch successful:
        {
            "status": "ok",
            "url": <str>,                  # the fetched URL
            "domain": <str>,               # extracted hostname
            "content_type": <str>,         # e.g. "text/html"
            "content_length": <int>,       # bytes received
            "text_excerpt": <str>,         # first 4000 chars of body
            "truncated": <bool>
        }

        # URL refused by allowlist:
        {
            "status": "refused",
            "url": <str>,
            "code": "url_not_allowlisted",
            "message": "URL domain '<domain>' is not in the allowlist. ...",
            "allowed_domains": [<str>, ...]
        }

        # Malformed URL:
        {
            "status": "refused",
            "url": <str>,
            "code": "url_invalid",
            "message": "Could not parse URL: <reason>"
        }

        # SSRF attempt blocked:
        {
            "status": "refused",
            "url": <str>,
            "code": "private_address_blocked",
            "message": "URL resolves to private/local network; blocked."
        }

        # Fetch failed (network, timeout, non-2xx):
        {
            "status": "error",
            "url": <str>,
            "code": "fetch_failed",
            "message": "<reason>",
            "http_status": <int | None>
        }
    """
    # ------------------------------------------------------------------
    # Step 1: URL parse + scheme check
    # ------------------------------------------------------------------
    if not url or not isinstance(url, str):
        return {
            "status":  "refused",
            "url":     url or "",
            "code":    "url_invalid",
            "message": "Could not parse URL: empty or non-string value.",
        }

    try:
        parsed = urllib.parse.urlparse(url)
    except Exception as exc:
        return {
            "status":  "refused",
            "url":     url,
            "code":    "url_invalid",
            "message": f"Could not parse URL: {exc}",
        }

    # Scheme must be http or https
    if parsed.scheme not in ("http", "https"):
        return {
            "status":  "refused",
            "url":     url,
            "code":    "url_invalid",
            "message": (
                f"Could not parse URL: scheme '{parsed.scheme}' is not allowed "
                "(only http and https are permitted)."
            ),
        }

    # Hostname must be present
    hostname = (parsed.hostname or "").lower().strip()
    if not hostname:
        return {
            "status":  "refused",
            "url":     url,
            "code":    "url_invalid",
            "message": "Could not parse URL: no hostname found.",
        }

    path = parsed.path or "/"

    # ------------------------------------------------------------------
    # Step 2: SSRF guard — check BEFORE allowlist (catch IP literals first)
    # ------------------------------------------------------------------
    ssrf_error = _check_ssrf(hostname)
    if ssrf_error:
        # Check if it's a DNS failure vs SSRF block
        if "private/local" in ssrf_error:
            return {
                "status":  "refused",
                "url":     url,
                "code":    "private_address_blocked",
                "message": ssrf_error,
            }
        else:
            # DNS resolution failure → url_invalid
            return {
                "status":  "refused",
                "url":     url,
                "code":    "url_invalid",
                "message": f"Could not parse URL: {ssrf_error}",
            }

    # ------------------------------------------------------------------
    # Step 3: Domain allowlist check (exact match, case-insensitive)
    # ------------------------------------------------------------------
    if hostname not in _ALLOWED_DOMAINS:
        return {
            "status":          "refused",
            "url":             url,
            "code":            "url_not_allowlisted",
            "message":         (
                f"URL domain '{hostname}' is not in the allowlist. "
                f"Allowed domains: {', '.join(_sorted_allowed_domains())}."
            ),
            "allowed_domains": _sorted_allowed_domains(),
        }

    # ------------------------------------------------------------------
    # Step 4: Per-domain path filter
    # ------------------------------------------------------------------
    if not _check_path_allowed(hostname, path):
        prefixes = _ALLOWED_PATH_PREFIXES[hostname]
        return {
            "status":          "refused",
            "url":             url,
            "code":            "url_not_allowlisted",
            "message":         (
                f"URL domain '{hostname}' is not in the allowlist. "
                f"Allowed domains: {', '.join(_sorted_allowed_domains())}."
            ),
            "allowed_domains": _sorted_allowed_domains(),
        }

    # ------------------------------------------------------------------
    # Step 5: Fetch (injected or real)
    # ------------------------------------------------------------------
    if fetch_fn is not None:
        # Test injection path — no real network call
        try:
            body_text = fetch_fn(url)
        except Exception as exc:
            return {
                "status":      "error",
                "url":         url,
                "code":        "fetch_failed",
                "message":     f"Injected fetch_fn raised: {exc}",
                "http_status": None,
            }
        content_type   = "text/html"
        content_length = len(body_text.encode("utf-8", errors="replace"))
    else:
        # Real urllib fetch
        req = urllib.request.Request(
            url,
            headers={"User-Agent": _USER_AGENT},
        )
        try:
            with urllib.request.urlopen(req, timeout=_FETCH_TIMEOUT_SECONDS) as resp:
                raw_content_type = resp.headers.get("Content-Type", "text/html") or "text/html"
                # Normalise: strip charset suffix, lower-case
                content_type = raw_content_type.split(";")[0].strip().lower()

                # Refuse binary / non-text content types
                if not any(content_type.startswith(p) for p in _ACCEPTED_CONTENT_TYPE_PREFIXES):
                    return {
                        "status":      "error",
                        "url":         url,
                        "code":        "fetch_failed",
                        "message":     (
                            f"Content-Type '{content_type}' is not accepted. "
                            "Only text/* and application/json are permitted."
                        ),
                        "http_status": resp.status,
                    }

                raw_bytes    = resp.read(_MAX_BODY_BYTES)
                body_text    = raw_bytes.decode("utf-8", errors="replace")
                content_length = len(raw_bytes)

        except urllib.error.HTTPError as exc:
            return {
                "status":      "error",
                "url":         url,
                "code":        "fetch_failed",
                "message":     f"HTTP {exc.code}: {exc.reason}",
                "http_status": exc.code,
            }
        except Exception as exc:
            return {
                "status":      "error",
                "url":         url,
                "code":        "fetch_failed",
                "message":     str(exc),
                "http_status": None,
            }

    # ------------------------------------------------------------------
    # Step 6: Truncate excerpt
    # ------------------------------------------------------------------
    if len(body_text) > _MAX_EXCERPT_CHARS:
        text_excerpt = body_text[:_MAX_EXCERPT_CHARS]
        truncated    = True
    else:
        text_excerpt = body_text
        truncated    = False

    return {
        "status":         "ok",
        "url":            url,
        "domain":         hostname,
        "content_type":   content_type,
        "content_length": content_length,
        "text_excerpt":   text_excerpt,
        "truncated":      truncated,
    }


# ---------------------------------------------------------------------------
# Tool-runner spec and handler
# ---------------------------------------------------------------------------

WEB_FETCH_SPEC = ToolSpec(
    name="web_fetch",
    description=(
        "Fetch football/FPL news from allowlisted domains (BBC sport/football, "
        "Athletic football, Premier League, Fantasy PL, FBref, Transfermarkt). "
        "status=refused for off-topic URLs or SSRF attempts. Use sparingly — no cache."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {
                "type":        "string",
                "description": (
                    "Full URL to fetch. Must be on an allowlisted football/FPL domain. "
                    "status=refused returned for any non-allowlisted domain or private IP."
                ),
            },
        },
        "required":             ["url"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "status":         {"type": "string"},
            "url":            {"type": "string"},
            "domain":         {"type": "string"},
            "content_type":   {"type": "string"},
            "content_length": {"type": "integer"},
            "text_excerpt":   {"type": "string"},
            "truncated":      {"type": "boolean"},
        },
    },
)


def _web_fetch_handler(
    args:      dict[str, Any],
    bootstrap: dict[str, Any],
) -> dict[str, Any]:
    """Tool-runner handler — delegates to ``web_fetch()``."""
    try:
        url = args.get("url")
        if not url:
            return {
                "status":  "refused",
                "url":     "",
                "code":    "url_invalid",
                "message": "Could not parse URL: 'url' argument is missing or empty.",
            }
        return web_fetch(url=url)
    except Exception as exc:  # noqa: BLE001
        return {
            "status":      "error",
            "url":         args.get("url", ""),
            "code":        "fetch_failed",
            "message":     f"web_fetch raised an unexpected error: {exc}",
            "http_status": None,
        }


# Register with the shared tool registry so run_tool("web_fetch", ...) works.
TOOL_REGISTRY.register(WEB_FETCH_SPEC, _web_fetch_handler)
