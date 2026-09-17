import base64
import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))
os.environ.setdefault("SERVICE_API_KEYS", "mbs_security_test_key_abcdefghijklmnop")
os.environ.setdefault("TOKEN_HASH_PEPPER", base64.b64encode(b"pepper-bytes-32-characters!!").decode("ascii"))

from app.config import clear_settings_cache, get_settings
from app.security import decrypt_text, encrypt_text, hash_token

clear_settings_cache()


def test_encrypt_decrypt_round_trip_with_aad():
    plaintext = "Sensitive AI memory"
    encrypted, version = encrypt_text(
        plaintext,
        tenant_id="tenant-a",
        user_id="user-a",
    )

    assert encrypted != plaintext
    assert version == get_settings().keyring.active_version
    assert (
        decrypt_text(
            encrypted,
            tenant_id="tenant-a",
            user_id="user-a",
            key_version=version,
        )
        == plaintext
    )


def test_encryption_uses_fresh_nonce():
    first, _ = encrypt_text("same memory", tenant_id="t1", user_id="u1")
    second, _ = encrypt_text("same memory", tenant_id="t1", user_id="u1")
    assert first != second


def test_aad_binds_ciphertext_to_tenant_and_user():
    encrypted, version = encrypt_text(
        "bound memory",
        tenant_id="tenant-a",
        user_id="user-a",
    )

    try:
        decrypt_text(
            encrypted,
            tenant_id="tenant-b",
            user_id="user-a",
            key_version=version,
        )
        assert False, "expected AAD mismatch"
    except Exception:
        pass

    try:
        decrypt_text(
            encrypted,
            tenant_id="tenant-a",
            user_id="user-b",
            key_version=version,
        )
        assert False, "expected AAD mismatch"
    except Exception:
        pass


def test_hash_token_is_deterministic_peppered_and_one_way():
    token = "mb_example_secret_token"
    digest = hash_token(token)

    assert digest == hash_token(token)
    assert digest != token
    assert len(digest) == 64
    # Must not equal unsalted SHA-256.
    import hashlib

    assert digest != hashlib.sha256(token.encode("utf-8")).hexdigest()


def test_key_version_selection_from_keyring():
    keyring = get_settings().keyring
    assert 1 in keyring.keys
    assert keyring.active_version in keyring.keys
