"""Encrypt API keys at rest (ADR-0012).

Users paste their own provider keys into the Settings screen. They are stored
in the ``app_setting`` table encrypted with Fernet (AES-128-CBC + HMAC). The
Fernet key is derived from ``SECRET_KEY`` in the environment; when that is not
set, a random key is generated once and kept in ``data/.secret_key`` so a
single-machine install works with zero configuration. Losing the key only
means re-entering API keys.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import secrets
from functools import lru_cache
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

PREFIX = "enc:v1:"


def _key_file() -> Path:
    return settings.upload_dir.parent / ".secret_key"


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    secret = os.environ.get("SECRET_KEY") or getattr(settings, "secret_key", None)
    if not secret:
        path = _key_file()
        try:
            if path.exists():
                secret = path.read_text(encoding="utf-8").strip()
            if not secret:
                secret = secrets.token_urlsafe(48)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(secret, encoding="utf-8")
                logger.info("generated local secret key at %s", path)
        except OSError as exc:  # read-only filesystem: fall back to a process key
            logger.warning("cannot persist secret key (%s); keys will not survive restarts", exc)
            secret = secrets.token_urlsafe(48)
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt(value: str) -> str:
    if not value:
        return ""
    return PREFIX + _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith(PREFIX):
        return value  # legacy plain value
    try:
        return _fernet().decrypt(value[len(PREFIX) :].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("stored API key cannot be decrypted (SECRET_KEY changed?)")
        return ""


def mask(value: str | None) -> str | None:
    """'sk-abc...xyz' -> 'sk-a••••xyz' for display; None when unset."""
    if not value:
        return None
    if len(value) <= 8:
        return "••••"
    return f"{value[:4]}••••{value[-3:]}"
