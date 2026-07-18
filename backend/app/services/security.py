import hashlib
import hmac
import secrets

from .. import config


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 240_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password, stored):
    try:
        _, salt, _ = stored.split("$", 2)
    except ValueError:
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def sign_token(token):
    sig = hmac.new(config.APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    return f"{token}.{sig}"


def unsign_token(value):
    if not value or "." not in value:
        return None
    token, sig = value.rsplit(".", 1)
    expected = hmac.new(config.APP_SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    return token if hmac.compare_digest(sig, expected) else None
