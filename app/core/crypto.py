"""Application-level authenticated encryption for small secrets we must
persist (OAuth refresh tokens today). NOT a general-purpose crypto module —
this exists solely so a refresh token never touches Postgres in plaintext.

Design (deliberately small — this is for a handful of users, not a KMS):
- AES-256-GCM (AEAD): confidentiality + integrity in one primitive, no
  separate MAC to get wrong.
- One key, held only as the `INTEGRATION_ENCRYPTION_KEY` env var (Railway
  secret in production). Never written to the database, logs, or any
  candidate-visible file.
- Each ciphertext is bound to its row via Additional Authenticated Data
  (AAD) — typically f"{user_id}:{provider}" — so a ciphertext copied from
  one row into another fails to decrypt instead of silently "working" for
  the wrong candidate.
- Stored form is a single base64 blob: nonce(12) || ciphertext || tag(16),
  so there's exactly one column to manage per secret, not three.
"""

import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_LEN = 12


class EncryptionKeyMissing(RuntimeError):
    """Raised when a secret needs to be encrypted/decrypted but no key is configured."""


def _load_key(key_b64: str) -> bytes:
    if not key_b64:
        raise EncryptionKeyMissing("INTEGRATION_ENCRYPTION_KEY is not configured")
    try:
        key = base64.b64decode(key_b64, validate=True)
    except Exception as error:
        raise EncryptionKeyMissing("INTEGRATION_ENCRYPTION_KEY is not valid base64") from error
    if len(key) != 32:
        raise EncryptionKeyMissing("INTEGRATION_ENCRYPTION_KEY must decode to exactly 32 bytes (AES-256)")
    return key


def generate_key() -> str:
    """Generate a fresh base64-encoded 256-bit key (for `railway variables set`, not for runtime use)."""
    return base64.b64encode(os.urandom(32)).decode("ascii")


def encrypt_secret(key_b64: str, plaintext: str, *, aad: str) -> str:
    key = _load_key(key_b64)
    nonce = os.urandom(_NONCE_LEN)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return base64.b64encode(nonce + ciphertext).decode("ascii")


def decrypt_secret(key_b64: str, blob: str, *, aad: str) -> str:
    key = _load_key(key_b64)
    raw = base64.b64decode(blob)
    nonce, ciphertext = raw[:_NONCE_LEN], raw[_NONCE_LEN:]
    plaintext = AESGCM(key).decrypt(nonce, ciphertext, aad.encode("utf-8"))
    return plaintext.decode("utf-8")
