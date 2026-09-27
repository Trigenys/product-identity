from cryptography.fernet import Fernet, InvalidToken


class TokenEncryptionError(ValueError):
    pass


class TokenCipher:
    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except Exception as exc:
            raise TokenEncryptionError(
                "Shopify token encryption key must be a valid Fernet key"
            ) from exc

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenEncryptionError("Encrypted Shopify token could not be decrypted") from exc
