import os
import base64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

RAW_KEY = os.getenv("ENCRYPTION_KEY", "uNq8zS1B6pE0g0X5L8fG1kQ9w3r7v2x5Y8z0A1B2C3D=")

def get_aes_key():
    try:
        return base64.b64decode(RAW_KEY)
    except Exception:
        return RAW_KEY.encode().zfill(32)[:32]

def encrypt_text(plain_text: str) -> str:
    key = get_aes_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode(), None)
    return base64.b64encode(nonce + ciphertext).decode()

def decrypt_text(encrypted_b64: str) -> str:
    key = get_aes_key()
    aesgcm = AESGCM(key)
    data = base64.b64decode(encrypted_b64)
    nonce = data[:12]
    ciphertext = data[12:]
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return decrypted.decode()
