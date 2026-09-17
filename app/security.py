"""Cryptographic helpers: versioned AES-256-GCM, peppered token hashing."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from typing import Optional, Tuple

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings


def hash_token(token: str) -> str:
    if not token:
        raise ValueError("Token must not be empty")
    pepper = get_settings().token_hash_pepper
    return hmac.new(pepper, token.encode("utf-8"), hashlib.sha256).hexdigest()


def _aad(tenant_id: str, user_id: str) -> bytes:
    if not tenant_id or not user_id:
        raise ValueError("tenant_id and user_id are required for encryption AAD")
    return f"mb:v1:{tenant_id}:{user_id}".encode("utf-8")


def encrypt_text(plain_text: str, *, tenant_id: str, user_id: str) -> Tuple[str, int]:
    """Encrypt with the active key version. Returns (ciphertext_b64, key_version)."""
    keyring = get_settings().keyring
    version = keyring.active_version
    key = keyring.get(version)
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), _aad(tenant_id, user_id))
    packed = base64.b64encode(nonce + ciphertext).decode("ascii")
    return packed, version


def decrypt_text(
    encrypted_b64: str,
    *,
    tenant_id: str,
    user_id: str,
    key_version: Optional[int] = None,
) -> str:
    keyring = get_settings().keyring
    version = key_version if key_version is not None else keyring.active_version
    key = keyring.get(version)
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted_b64, validate=True)

    if len(data) < 13:
        raise ValueError("Encrypted payload is invalid")

    nonce = data[:12]
    ciphertext = data[12:]
    decrypted = aesgcm.decrypt(nonce, ciphertext, _aad(tenant_id, user_id))
    return decrypted.decode("utf-8")
