"""Environment-based settings for public / production web deployment."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass


def _env(name: str, legacy: str = "") -> str:
    """Read env var; optional legacy name (Clickless → OfficeLego)."""
    val = os.environ.get(name, "").strip()
    if val or not legacy:
        return val
    return os.environ.get(legacy, "").strip()


def _env_bool(name: str, default: bool = False, *, legacy: str = "") -> bool:
    val = _env(name, legacy).lower()
    if not val:
        return default
    return val in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class WebSettings:
    host: str
    port: int
    auth_token: str
    public_mode: bool
    base_url: str

    @property
    def auth_required(self) -> bool:
        return bool(self.auth_token)


def load_web_settings(
    *,
    host: str | None = None,
    port: int | None = None,
    auth_token: str | None = None,
    public_mode: bool | None = None,
    base_url: str | None = None,
) -> WebSettings:
    """Load settings from env, with optional CLI overrides."""
    public = (
        public_mode
        if public_mode is not None
        else _env_bool("OFFICELEGO_PUBLIC", legacy="CLICKLESS_PUBLIC")
    )
    token = (auth_token or _env("OFFICELEGO_AUTH_TOKEN", "CLICKLESS_AUTH_TOKEN")).strip()
    if public and not token:
        token = secrets.token_urlsafe(24)
        print(
            "OFFICELEGO_PUBLIC is on but no OFFICELEGO_AUTH_TOKEN — generated token:\n"
            f"  {token}\n"
            "Save it and set OFFICELEGO_AUTH_TOKEN before restarting.",
            flush=True,
        )

    resolved_host = (
        host
        or _env("OFFICELEGO_HOST", "CLICKLESS_HOST")
        or ("0.0.0.0" if public else "127.0.0.1")
    ).strip()

    port_str = _env("OFFICELEGO_PORT", "CLICKLESS_PORT") or "5757"
    resolved_port = port or int(port_str)
    resolved_base = (
        base_url or _env("OFFICELEGO_BASE_URL", "CLICKLESS_BASE_URL") or ""
    ).strip().rstrip("/")

    return WebSettings(
        host=resolved_host,
        port=resolved_port,
        auth_token=token,
        public_mode=public,
        base_url=resolved_base,
    )
