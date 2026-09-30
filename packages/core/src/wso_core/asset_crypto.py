"""Authenticated asset envelope encryption; no plaintext escapes before verification."""

from __future__ import annotations

import ctypes
import hashlib
import os
import stat
import threading
import weakref
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any, Literal, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from wso_core.storage import (
    CHUNK_BYTES,
    AssetAAD,
    AssetKeyProvider,
    EncryptionFinal,
    Envelope,
    IOBudget,
    PreparedEncryption,
    ReadManifest,
    StorageFailure,
    VerifiedPlaintext,
    WrappedKey,
    key_id_valid,
)

CryptoCode = Literal["KEY_UNAVAILABLE", "INTEGRITY", "LIMIT", "DEADLINE"]


class AssetCryptoFailure(Exception):
    def __init__(self, code: CryptoCode) -> None:
        self.code = code
        super().__init__(code)


def encode_asset_aad(aad: AssetAAD) -> bytes:
    purpose = {"IMPORT_PHOTO": 1, "IMPORT_CROP": 2, "EVIDENCE": 3}[aad.purpose]
    return (
        b"WSOASSET-AAD-v1\0"
        + aad.tenant_id.bytes
        + aad.asset_id.bytes
        + aad.attempt_id.bytes
        + (b"\0" if aad.store_id is None else b"\1" + aad.store_id.bytes)
        + (b"\0" if aad.parent_asset_id is None else b"\1" + aad.parent_asset_id.bytes)
        + bytes([purpose])
        + aad.byte_size.to_bytes(8, "big")
        + bytes([1 if aad.content_type == "image/jpeg" else 2])
        + bytes.fromhex(aad.checksum_sha256)
    )


def encode_wrap_aad(aad: AssetAAD, key_id: str) -> bytes:
    key_id_valid(key_id)
    encoded = key_id.encode("ascii")
    return (
        b"WSOASSET-WRAP-v1\0" + encode_asset_aad(aad) + bytes([len(encoded)]) + encoded
    )


def _windows_acl(descriptor: int) -> None:
    """Check the opened handle's owner and DACL, never a separate pathname."""
    import msvcrt
    from ctypes import wintypes

    class TokenUser(ctypes.Structure):
        _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

    class ACLSize(ctypes.Structure):
        _fields_ = [
            ("AceCount", wintypes.DWORD),
            ("AclBytesInUse", wintypes.DWORD),
            ("AclBytesFree", wintypes.DWORD),
        ]

    kernel = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    security = cast(Any, ctypes).WinDLL("advapi32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    security.OpenProcessToken.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    security.GetTokenInformation.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    security.GetSecurityInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    security.GetSecurityInfo.restype = wintypes.DWORD
    security.EqualSid.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    security.GetAclInformation.argtypes = [
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_int,
    ]
    security.GetAce.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    token = wintypes.HANDLE()
    owner, dacl, descriptor_info = (
        ctypes.c_void_p(),
        ctypes.c_void_p(),
        ctypes.c_void_p(),
    )
    try:
        if not security.OpenProcessToken(
            kernel.GetCurrentProcess(), 0x0008, ctypes.byref(token)
        ):
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        needed = wintypes.DWORD()
        security.GetTokenInformation(token, 1, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 65536:
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        buffer = ctypes.create_string_buffer(needed.value)
        if not security.GetTokenInformation(
            token, 1, buffer, needed, ctypes.byref(needed)
        ):
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        sid = ctypes.cast(buffer, ctypes.POINTER(TokenUser)).contents.Sid
        if (
            security.GetSecurityInfo(
                msvcrt.get_osfhandle(descriptor),
                1,
                0x0001 | 0x0004,
                ctypes.byref(owner),
                None,
                ctypes.byref(dacl),
                None,
                ctypes.byref(descriptor_info),
            )
            != 0
            or not owner.value
            or not dacl.value
            or not security.EqualSid(owner, sid)
        ):
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        count = ACLSize()
        if (
            not security.GetAclInformation(
                dacl, ctypes.byref(count), ctypes.sizeof(count), 2
            )
            or not count.AceCount
        ):
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        allowed = False
        for index in range(count.AceCount):
            ace = ctypes.c_void_p()
            if not security.GetAce(dacl, index, ctypes.byref(ace)) or ace.value is None:
                raise AssetCryptoFailure("KEY_UNAVAILABLE")
            ace_type = ctypes.c_ubyte.from_address(ace.value).value
            if ace_type == 1:
                continue  # Deny ACE grants no access.
            if ace_type != 0 or not security.EqualSid(
                ctypes.c_void_p(ace.value + 8), owner
            ):
                raise AssetCryptoFailure("KEY_UNAVAILABLE")
            allowed = True
        if not allowed:
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
    finally:
        if descriptor_info.value:
            kernel.LocalFree(descriptor_info)
        if token.value:
            kernel.CloseHandle(token)


def _load_key(path: Path) -> bytes:
    try:
        if not path.is_absolute() or path.is_symlink():
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            if os.name == "nt":
                _windows_acl(descriptor)
            before = os.fstat(descriptor)
            if not stat.S_ISREG(before.st_mode) or before.st_size != 32:
                raise AssetCryptoFailure("KEY_UNAVAILABLE")
            if os.name != "nt" and (
                before.st_uid != cast(Any, os).getuid()
                or stat.S_IMODE(before.st_mode) & 0o077
            ):
                raise AssetCryptoFailure("KEY_UNAVAILABLE")
            if os.name == "nt":
                # Refuse a pathname replacement after opening the checked handle.
                after = path.stat()
                if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
                    raise AssetCryptoFailure("KEY_UNAVAILABLE")
            value = os.read(descriptor, 33)
            if len(value) != 32:
                raise AssetCryptoFailure("KEY_UNAVAILABLE")
            return value
        finally:
            os.close(descriptor)
    except (OSError, ValueError, KeyError, TypeError):
        raise AssetCryptoFailure("KEY_UNAVAILABLE") from None


class LocalAssetKeyProvider:
    def __init__(self, *, active_key_id: str, key_files: Mapping[str, Path]) -> None:
        try:
            key_id_valid(active_key_id)
            if active_key_id not in key_files or not key_files:
                raise ValueError()
            self._keys: dict[str, bytes] = {}
            for identifier, path in key_files.items():
                key_id_valid(identifier)
                self._keys[identifier] = _load_key(path)
            self._active = active_key_id
        except (ValueError, TypeError):
            raise AssetCryptoFailure("KEY_UNAVAILABLE") from None

    def active_key_id(self) -> str:
        return self._active

    def wrap(self, key_id: str, dek: bytes, aad: bytes) -> WrappedKey:
        if key_id != self._active or type(dek) is not bytes or len(dek) != 32:
            raise AssetCryptoFailure("KEY_UNAVAILABLE")
        nonce = os.urandom(12)
        return WrappedKey(nonce, AESGCM(self._keys[key_id]).encrypt(nonce, dek, aad))

    def unwrap(self, key_id: str, envelope: WrappedKey, aad: bytes) -> bytes:
        try:
            result = AESGCM(self._keys[key_id]).decrypt(
                envelope.wrap_nonce, envelope.ciphertext, aad
            )
            if len(result) != 32:
                raise AssetCryptoFailure("INTEGRITY")
            return result
        except KeyError:
            raise AssetCryptoFailure("KEY_UNAVAILABLE") from None
        except (InvalidTag, ValueError):
            raise AssetCryptoFailure("INTEGRITY") from None


class _EncryptingUpload:
    def __init__(self, prepared: PreparedEncryption) -> None:
        self._aad = prepared.aad
        self._nonce = prepared.envelope.object_nonce
        self._cipher = Cipher(
            algorithms.AES(prepared.data_key), modes.GCM(self._nonce)
        ).encryptor()
        self._cipher.authenticate_additional_data(encode_asset_aad(self._aad))
        self._hash = hashlib.sha256()
        self._count = 0
        self._header = False
        self._closed = False

    def header(self) -> bytes:
        if self._closed or self._header:
            raise AssetCryptoFailure("INTEGRITY")
        self._header = True
        return b"WSOAST01" + self._nonce

    def update(self, plaintext: bytes) -> bytes:
        if self._closed or not self._header:
            raise AssetCryptoFailure("INTEGRITY")
        if (
            type(plaintext) is not bytes
            or len(plaintext) > CHUNK_BYTES
            or self._count + len(plaintext) > self._aad.byte_size
        ):
            self.close()
            raise AssetCryptoFailure("LIMIT")
        self._count += len(plaintext)
        self._hash.update(plaintext)
        return self._cipher.update(plaintext)

    def finish(self) -> EncryptionFinal:
        if self._closed or not self._header:
            raise AssetCryptoFailure("INTEGRITY")
        self._closed = True
        digest = self._hash.hexdigest()
        if self._count != self._aad.byte_size or digest != self._aad.checksum_sha256:
            raise AssetCryptoFailure("INTEGRITY")
        return EncryptionFinal(
            self._cipher.finalize() + self._cipher.tag, self._count, digest
        )

    def close(self) -> None:
        self._closed = True


class AssetCipher:
    def __init__(self, provider: AssetKeyProvider) -> None:
        self._provider = provider
        # Pending instances are removed on start. Retain no used DEKs indefinitely.
        self._pending: weakref.WeakValueDictionary[int, PreparedEncryption] = (
            weakref.WeakValueDictionary()
        )
        self._lock = threading.Lock()

    def prepare(self, aad: AssetAAD) -> PreparedEncryption:
        identifier = self._provider.active_key_id()
        key = os.urandom(32)
        wrapped = self._provider.wrap(identifier, key, encode_wrap_aad(aad, identifier))
        result = PreparedEncryption(
            aad, Envelope(identifier, wrapped, os.urandom(12)), key
        )
        with self._lock:
            self._pending[id(result)] = result
        return result

    def start(self, prepared: PreparedEncryption) -> _EncryptingUpload:
        with self._lock:
            if self._pending.pop(id(prepared), None) is not prepared:
                raise AssetCryptoFailure("INTEGRITY")
        return _EncryptingUpload(prepared)

    def decrypt_verified(
        self, manifest: ReadManifest, chunks: Iterable[bytes], *, budget: IOBudget
    ) -> VerifiedPlaintext:
        ciphertext = bytearray()
        plaintext = b""
        try:
            budget.remaining_seconds()
            for chunk in chunks:
                budget.remaining_seconds()
                if type(chunk) is not bytes or len(chunk) > CHUNK_BYTES:
                    raise AssetCryptoFailure("LIMIT")
                if len(ciphertext) + len(chunk) > manifest.aad.byte_size + 36:
                    raise AssetCryptoFailure("LIMIT")
                ciphertext.extend(chunk)
            if (
                len(ciphertext) != manifest.aad.byte_size + 36
                or bytes(ciphertext[:20])
                != b"WSOAST01" + manifest.envelope.object_nonce
            ):
                raise AssetCryptoFailure("INTEGRITY")
            key = self._provider.unwrap(
                manifest.envelope.key_id,
                manifest.envelope.wrapped_key,
                encode_wrap_aad(manifest.aad, manifest.envelope.key_id),
            )
            plaintext = AESGCM(key).decrypt(
                manifest.envelope.object_nonce,
                bytes(ciphertext[20:]),
                encode_asset_aad(manifest.aad),
            )
            budget.remaining_seconds()
            digest = hashlib.sha256(plaintext).hexdigest()
            if (
                len(plaintext) != manifest.aad.byte_size
                or digest != manifest.aad.checksum_sha256
            ):
                raise AssetCryptoFailure("INTEGRITY")
            budget.remaining_seconds()
            return VerifiedPlaintext(plaintext, len(plaintext), digest)
        except StorageFailure:
            raise AssetCryptoFailure("DEADLINE") from None
        except (InvalidTag, ValueError):
            raise AssetCryptoFailure("INTEGRITY") from None
        finally:
            ciphertext.clear()
            del plaintext
