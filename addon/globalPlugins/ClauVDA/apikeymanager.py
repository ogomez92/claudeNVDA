# ClauVDA NVDA Add-on - API Key Manager
# -*- coding: utf-8 -*-

import os
import ctypes
import ctypes.wintypes
from logHandler import log


# Providers supported by this add-on.
PROVIDER_ANTHROPIC = "anthropic"
PROVIDER_BEDROCK = "bedrock"

# Environment variable fallbacks for each provider.
_ENV_VARS = {
    PROVIDER_ANTHROPIC: ["ANTHROPIC_API_KEY"],
    PROVIDER_BEDROCK: ["AWS_BEARER_TOKEN_BEDROCK"],
}

# On-disk encrypted key file names per provider.
_KEY_FILES = {
    PROVIDER_ANTHROPIC: "anthropic.key.enc",
    PROVIDER_BEDROCK: "bedrock.key.enc",
}


class DPAPIError(Exception):
    """Exception raised when DPAPI operations fail."""
    pass


class DPAPI:
    """Windows Data Protection API wrapper for encrypting/decrypting data."""

    # DPAPI structures
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", ctypes.wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    def __init__(self):
        self._crypt32 = ctypes.windll.crypt32
        self._kernel32 = ctypes.windll.kernel32

    def encrypt(self, data: str) -> bytes:
        """
        Encrypt a string using Windows DPAPI.
        The encrypted data can only be decrypted by the same Windows user.
        """
        data_bytes = data.encode("utf-8")

        # Input blob
        input_blob = self.DATA_BLOB()
        input_blob.cbData = len(data_bytes)
        input_blob.pbData = ctypes.cast(
            ctypes.create_string_buffer(data_bytes, len(data_bytes)),
            ctypes.POINTER(ctypes.c_char)
        )

        # Output blob
        output_blob = self.DATA_BLOB()

        # Call CryptProtectData
        # Flags: CRYPTPROTECT_UI_FORBIDDEN (0x1) - don't show UI
        result = self._crypt32.CryptProtectData(
            ctypes.byref(input_blob),  # pDataIn
            None,  # szDataDescr (optional description)
            None,  # pOptionalEntropy (additional entropy)
            None,  # pvReserved
            None,  # pPromptStruct
            0x1,   # dwFlags - CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(output_blob)  # pDataOut
        )

        if not result:
            error_code = ctypes.get_last_error()
            raise DPAPIError(f"CryptProtectData failed with error code: {error_code}")

        # Copy encrypted data
        encrypted_data = ctypes.string_at(output_blob.pbData, output_blob.cbData)

        # Free the memory allocated by DPAPI
        self._kernel32.LocalFree(output_blob.pbData)

        return encrypted_data

    def decrypt(self, encrypted_data: bytes) -> str:
        """
        Decrypt data that was encrypted with Windows DPAPI.
        Must be decrypted by the same Windows user who encrypted it.
        """
        # Input blob
        input_blob = self.DATA_BLOB()
        input_blob.cbData = len(encrypted_data)
        input_blob.pbData = ctypes.cast(
            ctypes.create_string_buffer(encrypted_data, len(encrypted_data)),
            ctypes.POINTER(ctypes.c_char)
        )

        # Output blob
        output_blob = self.DATA_BLOB()

        # Call CryptUnprotectData
        result = self._crypt32.CryptUnprotectData(
            ctypes.byref(input_blob),  # pDataIn
            None,  # ppszDataDescr
            None,  # pOptionalEntropy
            None,  # pvReserved
            None,  # pPromptStruct
            0x1,   # dwFlags - CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(output_blob)  # pDataOut
        )

        if not result:
            error_code = ctypes.get_last_error()
            raise DPAPIError(f"CryptUnprotectData failed with error code: {error_code}")

        # Copy decrypted data
        decrypted_data = ctypes.string_at(output_blob.pbData, output_blob.cbData)

        # Free the memory allocated by DPAPI
        self._kernel32.LocalFree(output_blob.pbData)

        return decrypted_data.decode("utf-8")


class APIKeyManager:
    """Manages Claude / Bedrock credential storage with encryption.

    Each provider (Anthropic direct, Amazon Bedrock) has its own encrypted
    key file. The active provider is selected elsewhere (configspec).
    """

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._dpapi = DPAPI()

    def _key_file(self, provider: str) -> str:
        return os.path.join(self.data_dir, _KEY_FILES[provider])

    def get_api_key(self, provider: str) -> str | None:
        """Get the API key for the given provider.

        Priority: encrypted file > environment variable(s).
        """
        if provider not in _KEY_FILES:
            raise ValueError(f"Unknown provider: {provider}")

        key_file = self._key_file(provider)
        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    encrypted_data = f.read()
                    if encrypted_data:
                        key = self._dpapi.decrypt(encrypted_data)
                        if key:
                            return key
            except DPAPIError as e:
                log.error(f"Error decrypting {provider} key: {e}")
            except Exception as e:
                log.error(f"Error reading {provider} key file: {e}")

        for env_var in _ENV_VARS[provider]:
            key = os.environ.get(env_var, "").strip()
            if key:
                return key

        return None

    def save_api_key(self, provider: str, key: str) -> bool:
        """Save the API key for the given provider (encrypted with DPAPI)."""
        if provider not in _KEY_FILES:
            raise ValueError(f"Unknown provider: {provider}")
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            encrypted_data = self._dpapi.encrypt(key.strip())
            with open(self._key_file(provider), "wb") as f:
                f.write(encrypted_data)
            return True
        except DPAPIError as e:
            log.error(f"Error encrypting {provider} key: {e}")
            return False
        except Exception as e:
            log.error(f"Error saving {provider} key: {e}")
            return False

    def delete_api_key(self, provider: str) -> bool:
        """Delete the stored API key for the given provider."""
        if provider not in _KEY_FILES:
            raise ValueError(f"Unknown provider: {provider}")
        try:
            key_file = self._key_file(provider)
            if os.path.exists(key_file):
                os.remove(key_file)
            return True
        except Exception as e:
            log.error(f"Error deleting {provider} key: {e}")
            return False

    def is_ready(self, provider: str) -> bool:
        """Check if an API key is available for the provider."""
        return self.get_api_key(provider) is not None

    def get_key_source(self, provider: str) -> str:
        """Describe where the API key for the provider is coming from."""
        if provider not in _KEY_FILES:
            return "none"

        key_file = self._key_file(provider)
        if os.path.exists(key_file):
            try:
                with open(key_file, "rb") as f:
                    if f.read():
                        return "encrypted file"
            except Exception:
                pass

        for env_var in _ENV_VARS[provider]:
            if os.environ.get(env_var, "").strip():
                return f"environment ({env_var})"

        return "none"


# Global instance
_manager: APIKeyManager | None = None


def get_manager(data_dir: str) -> APIKeyManager:
    """Get or create the API key manager instance."""
    global _manager
    if _manager is None:
        _manager = APIKeyManager(data_dir)
    return _manager
