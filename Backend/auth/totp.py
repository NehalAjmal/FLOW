import base64
import hashlib
import hmac
import secrets
import struct
import time
from typing import Optional


def generate_totp_secret(length: int = 32) -> str:
    """Generate a random Base32 secret string (standard RFC 3548/4648 base32 without padding)."""
    raw_bytes = secrets.token_bytes(20)
    return base64.b32encode(raw_bytes).decode("utf-8").replace("=", "")


def generate_totp_code(
    secret: str,
    time_step: int = 30,
    digits: int = 6,
    for_time: Optional[float] = None
) -> str:
    """
    Generate an RFC 6238 TOTP code for the given secret.
    Default: 30-second window, 6 digits, HMAC-SHA1.
    """
    if for_time is None:
        for_time = time.time()

    # Standard Base32 decode with padding restoration
    secret_cleaned = secret.strip().replace(" ", "").upper()
    missing_padding = len(secret_cleaned) % 8
    if missing_padding:
        secret_cleaned += "=" * (8 - missing_padding)

    key = base64.b32decode(secret_cleaned, casefold=True)
    counter = int(for_time // time_step)
    counter_bytes = struct.pack(">Q", counter)

    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code_int = struct.unpack(">I", h[offset:offset+4])[0] & 0x7FFFFFFF
    code = str(code_int % (10 ** digits)).zfill(digits)
    return code


def verify_totp_code(
    secret: str,
    code: str,
    time_step: int = 30,
    window: int = 1,
    for_time: Optional[float] = None
) -> bool:
    """
    Verify a TOTP code within a drift window (±window steps, default ±30s).
    """
    if not secret or not code:
        return False

    code = code.strip()
    if for_time is None:
        for_time = time.time()

    current_step = int(for_time // time_step)
    for step_offset in range(-window, window + 1):
        step_time = (current_step + step_offset) * time_step
        expected_code = generate_totp_code(secret, time_step=time_step, digits=len(code), for_time=step_time)
        if hmac.compare_digest(expected_code, code):
            return True
    return False


def get_otpauth_url(secret: str, email: str, issuer: str = "FLOW") -> str:
    """Generate otpauth:// URL for authenticator apps (Google Authenticator, Authy)."""
    return f"otpauth://totp/{issuer}:{email}?secret={secret}&issuer={issuer}"
