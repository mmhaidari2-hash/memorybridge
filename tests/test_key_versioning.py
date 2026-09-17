import base64
import os

import pytest


@pytest.fixture()
def versioned_keyring_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv(
        "ENCRYPTION_KEYS",
        "1:"
        + base64.b64encode(b"1" * 32).decode("ascii")
        + ",2:"
        + base64.b64encode(b"2" * 32).decode("ascii"),
    )
    monkeypatch.setenv("ENCRYPTION_ACTIVE_VERSION", "2")
    monkeypatch.delenv("ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("SERVICE_API_KEYS", "mbs_keyring_test_key_abcdefghijkl")
    monkeypatch.setenv("TOKEN_HASH_PEPPER", base64.b64encode(b"k" * 32).decode("ascii"))

    from app.config import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()


def test_active_version_used_for_new_writes_and_old_version_still_decrypts(versioned_keyring_env):
    from app.config import get_settings
    from app.security import decrypt_text, encrypt_text
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    import os as pyos

    settings = get_settings()
    assert settings.keyring.active_version == 2

    packed, version = encrypt_text("v2 memory", tenant_id="t", user_id="u")
    assert version == 2
    assert decrypt_text(packed, tenant_id="t", user_id="u", key_version=2) == "v2 memory"

    key = settings.keyring.get(1)
    nonce = pyos.urandom(12)
    aad = b"mb:v1:t:u"
    ct = AESGCM(key).encrypt(nonce, b"legacy memory", aad)
    legacy = base64.b64encode(nonce + ct).decode("ascii")
    assert decrypt_text(legacy, tenant_id="t", user_id="u", key_version=1) == "legacy memory"
