import base64
import os

os.environ.setdefault("ENCRYPTION_KEY", base64.b64encode(b"x" * 32).decode("ascii"))

from app.security import decrypt_text, encrypt_text, hash_token


def test_encrypt_decrypt_round_trip():
    plaintext = "Sensitive AI memory"
    encrypted = encrypt_text(plaintext)

    assert encrypted != plaintext
    assert decrypt_text(encrypted) == plaintext


def test_encryption_uses_fresh_nonce():
    first = encrypt_text("same memory")
    second = encrypt_text("same memory")

    assert first != second


def test_hash_token_is_deterministic_and_one_way():
    token = "mb_example_secret_token"
    digest = hash_token(token)

    assert digest == hash_token(token)
    assert digest != token
    assert len(digest) == 64
