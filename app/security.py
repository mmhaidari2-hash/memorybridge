import base64
import binascii
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def get_aes_key() -> bytes:
    raw_key = os.getenv("ENCRYPTION_KEY")
    if not raw_key:
        raise RuntimeError("ENCRYPTION_KEY is required")

    try:
        key = base64.b64decode(raw_key, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise RuntimeError("ENCRYPTION_KEY must be valid base64") from exc

    if len(key) != 32:
        raise RuntimeError("ENCRYPTION_KEY must decode to exactly 32 bytes")

    return key


def encrypt_text(plain_text: str) -> str:
    aesgcm = AESGCM(get_aes_key())
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_text(encrypted_b64: str) -> str:
    aesgcm = AESGCM(get_aes_key())
    data = base64.b64decode(encrypted_b64, validate=True)

    if len(data) < 13:
        raise ValueError("Encrypted payload is invalid")

    nonce = data[:12]
    ciphertext = data[12:]
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode("utf-8")
