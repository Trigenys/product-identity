import base64
import hashlib
import hmac


def verify_webhook_hmac(
    raw_body: bytes,
    *,
    provided_hmac: str,
    client_secrets: list[str],
) -> bool:
    if not provided_hmac:
        return False

    for secret in client_secrets:
        if not secret:
            continue
        computed = base64.b64encode(
            hmac.new(
                secret.encode("utf-8"),
                raw_body,
                hashlib.sha256,
            ).digest()
        ).decode("ascii")
        if hmac.compare_digest(computed, provided_hmac):
            return True

    return False
