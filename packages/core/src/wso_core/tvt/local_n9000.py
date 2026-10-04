"""Private bounded N9000 greeting/login wire codec, without transport or authority.

Source: SuperLive Plus1.18.1 gg0/wz0/ok2/lz0/jz0/og0/ServerNVMSHeader,
cw3.X9/ya/Z9 and statically recovered libOpensslSDK RSA helpers. This module
does not issue configuration, arbitrary commands, live requests or credentials
over a network. Callers own transport deadlines, generations and channel joins.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import struct
from collections.abc import Callable
from dataclasses import dataclass
from typing import NoReturn, SupportsIndex

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

_MAGIC = 825307441
_MAX_PACKET = 1 << 20
_ZERO_GUID = bytes(16)
# 2561 has no APK body parser:92 is the root-observed strict opaque bound.
# 2562/2563 read exactly40/36 bytes in ml2.a/il2.a. Never generalize the
# dispatcher default return into admission of arbitrary commands or lengths.
_STARTUP_BODY_LENGTHS = {2561: 92, 2562: 40, 2563: 36}


class CodecError(ValueError):
    """Fixed diagnostics; input bytes, proofs and keys never enter messages."""


class UnsupportedBranch(CodecError):
    def __init__(self, branch: str) -> None:
        self.branch = branch
        super().__init__("unsupported N9000 branch")


class LoginRejected(CodecError):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__("N9000 login rejected")


class _Private:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: private>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private N9000 value cannot be serialized")


def _integer(value: int, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise CodecError("invalid N9000 numeric field")


def _fixed(value: bytes, length: int) -> bytes:
    if type(value) is not bytes or len(value) != length:
        raise CodecError("invalid N9000 fixed field")
    return value


def _utf8_field(value: str, *, allow_empty: bool) -> bytes:
    # Explicit conservative C-string policy: max63 UTF8 bytes plus NUL; APK
    # arrays have64 bytes but do not prove acceptance of unterminated64-byte text.
    if not isinstance(value, str) or "\x00" in value:
        raise CodecError("invalid N9000 credential")
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeError:
        raise CodecError("invalid N9000 credential encoding") from None
    if len(raw) > 63 or (not raw and not allow_empty):
        raise CodecError("invalid N9000 credential length")
    return raw


class Credentials(_Private):
    """Immutable private ordinary device credentials, without normalization."""

    __slots__ = ("_md5", "_password", "_username")
    _username: bytes
    _password: bytes
    _md5: str

    def __init__(
        self, username: str, password: str, *, allow_empty_password: bool = False
    ) -> None:
        if type(allow_empty_password) is not bool:
            raise CodecError("invalid empty credential policy")
        user = _utf8_field(username, allow_empty=False)
        secret = _utf8_field(password, allow_empty=allow_empty_password)
        object.__setattr__(self, "_username", user)
        object.__setattr__(self, "_password", secret)
        object.__setattr__(
            self, "_md5", hashlib.md5(secret).hexdigest().upper() if secret else ""
        )

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private N9000 credentials are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private N9000 credentials are immutable")

    @property
    def md5_text(self) -> str:
        """Private uppercase MD5 material; never an account token."""
        return self._md5


@dataclass(frozen=True, slots=True, repr=False)
class PrivateWire(_Private):
    data: bytes

    def __post_init__(self) -> None:
        if type(self.data) is not bytes or not 24 <= len(self.data) <= 65536:
            raise CodecError("invalid private N9000 wire bytes")


@dataclass(frozen=True, slots=True, repr=False)
class Greeting(_Private):
    version: int
    security: int
    challenge: int
    capability: int
    customer_id: int
    device_version: bytes

    def __post_init__(self) -> None:
        _integer(self.version, 0, 0x7FFFFFFF)
        if type(self.security) is not int or self.security not in (0, 1, 2):
            raise UnsupportedBranch("security_mode")
        _integer(self.challenge, 0, 0xFFFFFF)
        _integer(self.capability, 0, 127)
        _integer(self.customer_id, 0, 0xFFFFFFFF)
        _fixed(self.device_version, 8)


def parse_greeting(raw: bytes) -> Greeting:
    """Parse exactly64 greeting bytes. Customer isolation policy is external."""
    _fixed(raw, 64)
    return Greeting(
        version=struct.unpack_from("<i", raw, 12)[0],
        security=raw[44],
        challenge=int.from_bytes(raw[45:48], "little"),
        capability=raw[52],
        customer_id=struct.unpack_from("<I", raw, 56)[0],
        device_version=raw[32:40],
    )


@dataclass(frozen=True, slots=True, repr=False)
class Packet(_Private):
    command: int
    sequence: int
    flags: int
    encoding: int
    body: bytes
    peer_version: int = 3

    def __post_init__(self) -> None:
        _integer(self.command, 0, 0x2FFFFFFF)
        _integer(self.sequence, 0, 0x7FFFFFFF)
        _integer(self.flags, 0, 1)
        _integer(self.encoding, 0, 1)
        _integer(self.peer_version, 1, 32767)
        if self.command & 0x0FFFFFFF not in (257, 261, *_STARTUP_BODY_LENGTHS):
            raise UnsupportedBranch("non_login_command")
        if type(self.body) is not bytes or len(self.body) > _MAX_PACKET - 24:
            raise CodecError("invalid private N9000 packet body")


def _is_startup_header(
    command: int,
    sequence: int,
    flags: int,
    encoding: int,
    length: int,
) -> bool:
    return (
        command in _STARTUP_BODY_LENGTHS
        and sequence == 0
        and flags == 0
        and encoding == 0
        and length == _STARTUP_BODY_LENGTHS[command]
    )


def _check_inner_header(
    version: int,
    flags: int,
    encoding: int,
    command: int,
    sequence: int,
    length: int,
    *,
    greeting_bound: bool,
) -> None:
    # Q4 (greeting login layout) and R3 (peer short header) are independent.
    # The source receiver parses signed-short s without comparing it to m7's3.
    # Positive signed-short admission is our deliberate bounded helper policy.
    if (
        (not greeting_bound and version != 3)
        or not 1 <= version <= 32767
        or flags not in (0, 1)
        or encoding not in (0, 1)
    ):
        raise CodecError("invalid N9000 inner header")
    _integer(sequence, 0, 0x7FFFFFFF)
    if command & 0x0FFFFFFF in (257, 261) and command >> 28 in (0, 1, 2):
        return
    if greeting_bound and _is_startup_header(
        command, sequence, flags, encoding, length
    ):
        return
    raise UnsupportedBranch("non_login_command")


def _parse_inner(raw: bytes, *, greeting_bound: bool = False) -> Packet:
    if len(raw) < 16:
        raise CodecError("short N9000 inner header")
    version, flags, encoding, command, sequence, length = struct.unpack_from(
        "<HBBIII", raw
    )
    _check_inner_header(
        version,
        flags,
        encoding,
        command,
        sequence,
        length,
        greeting_bound=greeting_bound,
    )
    if length != len(raw) - 16:
        raise CodecError("inconsistent N9000 body length")
    return Packet(command, sequence, flags, encoding, raw[16:], version)


class N9000Stream(_Private):
    """One generation's bounded transport byte stream, after its greeting.

    feed accepts immutable/mutable bytes, owns copies, and returns private login
    packets and the exact bounded2561/2562/2563 startup notifications when bound.
    Heartbeats are consumed. og0 fragments must be contiguous, ordered
    and consistent. Any parse failure permanently invalidates this parser.
    """

    __slots__ = (
        "_assembly",
        "_buffer",
        "_failed",
        "_fragment",
        "_greeting",
        "_max_chunk",
        "_max_fragments",
        "_max_packet",
    )

    def __init__(
        self,
        *,
        greeting: Greeting | None = None,
        max_packet_bytes: int = 65536,
        max_chunk_bytes: int = 65536,
        max_fragments: int = 256,
    ) -> None:
        _integer(max_packet_bytes, 256, _MAX_PACKET)
        _integer(max_chunk_bytes, 1, _MAX_PACKET)
        _integer(max_fragments, 1, 4096)
        if greeting is not None and not isinstance(greeting, Greeting):
            raise CodecError("invalid N9000 stream greeting")
        self._greeting = greeting
        self._max_packet = max_packet_bytes
        self._max_chunk = max_chunk_bytes
        self._max_fragments = max_fragments
        self._buffer = bytearray()
        self._assembly = bytearray()
        self._fragment: tuple[int, int, int, int, int] | None = None
        self._failed = False

    def close(self) -> None:
        """Discard a disconnected generation's partial data and fence input."""
        self._failed = True
        self._buffer.clear()
        self._assembly.clear()
        self._fragment = None
        self._greeting = None

    def feed(self, chunk: bytes | bytearray) -> tuple[Packet, ...]:
        if self._failed:
            raise CodecError("N9000 stream is terminal")
        try:
            if type(chunk) not in (bytes, bytearray) or len(chunk) > self._max_chunk:
                raise CodecError("N9000 transport chunk exceeds bound")
            # Iterate bounded slices, so coalesced packets do not require a
            # buffer proportional to the caller's total stream length.
            packets: list[Packet] = []
            offset = 0
            while offset < len(chunk):
                room = self._max_packet + 32 - len(self._buffer)
                if room <= 0:
                    raise CodecError("N9000 receive buffer exceeds bound")
                count = min(room, len(chunk) - offset)
                self._buffer.extend(chunk[offset : offset + count])
                offset += count
                self._drain(packets)
            return tuple(packets)
        except CodecError:
            self.close()
            raise

    def _drain(self, packets: list[Packet]) -> None:
        while len(self._buffer) >= 8:
            magic, length = struct.unpack_from("<II", self._buffer)
            if magic != _MAGIC:
                raise CodecError("invalid N9000 magic")
            if length == 0:
                del self._buffer[:8]
                continue
            if length == 0xFFFFFFFF:
                if len(self._buffer) < 32:
                    return
                group, count, total, index, size, tag = struct.unpack_from(
                    "<6I", self._buffer, 8
                )
                if not (
                    1 <= count <= self._max_fragments
                    and 1 <= index <= count
                    and 16 <= total <= self._max_packet - 8
                    and 1 <= size <= total
                ):
                    raise CodecError("invalid N9000 fragment bounds")
                if index == 1:
                    if self._fragment is not None:
                        raise CodecError("interleaved N9000 fragments")
                    expected: tuple[int, int, int, int, int] | None = (
                        group,
                        count,
                        total,
                        1,
                        tag,
                    )
                else:
                    expected = self._fragment
                if expected != (group, count, total, index, tag):
                    raise CodecError("inconsistent N9000 fragment sequence")
                used = len(self._assembly)
                if used + size > total or (index == count) != (used + size == total):
                    raise CodecError("inconsistent N9000 fragment total")
                if len(self._buffer) < 32 + size:
                    return
                self._assembly.extend(self._buffer[32 : 32 + size])
                del self._buffer[: 32 + size]
                if index == count:
                    packets.append(
                        _parse_inner(
                            bytes(self._assembly),
                            greeting_bound=self._greeting is not None,
                        )
                    )
                    self._assembly.clear()
                    self._fragment = None
                else:
                    self._fragment = (group, count, total, index + 1, tag)
                continue
            if self._fragment is not None:
                raise CodecError("interleaved N9000 packet")
            if not 16 <= length <= self._max_packet - 8:
                raise CodecError("invalid N9000 outer length")
            # Validate known inner bounds before waiting for declared body bytes.
            if len(self._buffer) >= 24:
                version, flags, encoding, command, sequence, size = struct.unpack_from(
                    "<HBBIII", self._buffer, 8
                )
                if size != length - 16:
                    raise CodecError("inconsistent N9000 inner header")
                _check_inner_header(
                    version,
                    flags,
                    encoding,
                    command,
                    sequence,
                    size,
                    greeting_bound=self._greeting is not None,
                )
            if len(self._buffer) < 8 + length:
                return
            packets.append(
                _parse_inner(
                    bytes(self._buffer[8 : 8 + length]),
                    greeting_bound=self._greeting is not None,
                )
            )
            del self._buffer[: 8 + length]


class RsaKeyPair(_Private):
    """Source RSA1024/exponent65537, PKCS1 public PEM and v1.5 decryption."""

    __slots__ = ("_private", "_public")
    _private: rsa.RSAPrivateKey
    _public: bytes

    def __init__(self, key: rsa.RSAPrivateKey) -> None:
        if (
            not isinstance(key, rsa.RSAPrivateKey)
            or key.key_size != 1024
            or key.public_key().public_numbers().e != 65537
        ):
            raise UnsupportedBranch("rsa_parameters")
        object.__setattr__(self, "_private", key)
        object.__setattr__(
            self,
            "_public",
            key.public_key().public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.PKCS1
            ),
        )

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private N9000 key is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private N9000 key is immutable")

    @classmethod
    def generate(cls) -> RsaKeyPair:
        return cls(rsa.generate_private_key(public_exponent=65537, key_size=1024))

    @classmethod
    def from_private_pem(cls, pem: bytes) -> RsaKeyPair:
        if type(pem) is not bytes or not 1 <= len(pem) <= 4096:
            raise CodecError("invalid private RSA input")
        try:
            key = serialization.load_pem_private_key(pem, password=None)
        except (ValueError, TypeError):
            raise CodecError("invalid private RSA input") from None
        if not isinstance(key, rsa.RSAPrivateKey):
            raise UnsupportedBranch("rsa_key_type")
        return cls(key)

    @property
    def public_pem(self) -> bytes:
        return self._public

    def _decrypt(self, ciphertext: bytes) -> bytes:
        _fixed(ciphertext, 128)
        try:
            plain = self._private.decrypt(ciphertext, padding.PKCS1v15())
        except ValueError:
            raise CodecError("N9000 RSA key extraction failed") from None
        # JNI/cw3 turns the output into default UTF8 text. Reject malformed text
        # instead of Android replacement-character decoding. No guessed hex/key
        # width: AES key interpretation remains a later codec's responsibility.
        try:
            plain.decode("utf-8", "strict")
        except UnicodeError:
            raise CodecError("invalid N9000 transport key encoding") from None
        if not 1 <= len(plain) <= 117 or b"\x00" in plain:
            raise CodecError("invalid N9000 transport key")
        return plain


@dataclass(frozen=True, slots=True, repr=False)
class LoginResult(_Private):
    device_guid: bytes
    session_guid: bytes
    key_material: bytes
    channel_tail: bytes
    reply_proof: bytes
    proof_verified: bool
    key_extracted: bool
    serial_validated: bool = False
    authorized: bool = False
    live: bool = False
    peer_version: int = 3


def _nonce() -> str:
    return "".join(secrets.choice("123456789") for _ in range(8))


def _user_field(user: bytes, greeting: Greeting) -> bytes:
    value = bytearray(user.ljust(64, b"\x00"))
    if greeting.security >= 2:
        mask = str(greeting.challenge).encode("ascii")
        for index, byte in enumerate(value):
            key = mask[index % len(mask)]
            if byte and byte != key:
                value[index] = byte ^ key
    return bytes(value)


class LoginHandshake(_Private):
    """One private credential attempt; result alone confers no authority."""

    __slots__ = (
        "_address",
        "_client_type",
        "_command",
        "_credentials",
        "_generation",
        "_greeting",
        "_guid",
        "_nonce_factory",
        "_nonce_value",
        "_rsa",
        "_rsa_factory",
        "_sequence",
        "_state",
    )

    def __init__(
        self,
        *,
        generation: int,
        sequence: int,
        credentials: Credentials,
        client_guid: bytes = _ZERO_GUID,
        client_address: bytes = bytes(4),
        client_type: int = 0,
        nonce_factory: Callable[[], str] = _nonce,
        rsa_factory: Callable[[], RsaKeyPair] = RsaKeyPair.generate,
        credential_mode: str = "ordinary",
    ) -> None:
        _integer(generation, 1, 0x7FFFFFFFFFFFFFFF)
        _integer(sequence, 0, 0x7FFFFFFF)
        _integer(client_type, 0, 0x7FFFFFFF)
        if not isinstance(credentials, Credentials):
            raise CodecError("invalid private N9000 credentials")
        if credential_mode != "ordinary":
            raise UnsupportedBranch("dynamic_share")
        self._generation, self._sequence = generation, sequence
        self._credentials: Credentials | None = credentials
        self._guid, self._address = _fixed(client_guid, 16), _fixed(client_address, 4)
        self._client_type = client_type
        self._nonce_factory, self._rsa_factory = nonce_factory, rsa_factory
        self._state = "new"
        self._greeting: Greeting | None = None
        self._nonce_value = 0
        self._rsa: RsaKeyPair | None = None
        self._command = 0

    @property
    def state(self) -> str:
        return self._state

    def close(self) -> None:
        """Fence the attempt and release private references; no wire command."""
        self._state = "terminal"
        self._credentials = None
        self._rsa = None
        self._greeting = None
        self._nonce_value = 0

    def build_request(self, greeting: Greeting) -> PrivateWire:
        if self._state != "new":
            raise CodecError("N9000 login attempt cannot be repeated")
        try:
            if not isinstance(greeting, Greeting):
                raise CodecError("invalid N9000 greeting")
            credentials = self._credentials
            if credentials is None:
                raise CodecError("N9000 attempt has no credential")
            self._greeting = greeting
            if greeting.security:
                try:
                    nonce = self._nonce_factory()
                except Exception:  # noqa: BLE001 -- private provider exception boundary
                    raise CodecError("N9000 private provider failed") from None
                if (
                    type(nonce) is not str
                    or len(nonce) != 8
                    or any(char not in "123456789" for char in nonce)
                ):
                    raise CodecError("invalid secure N9000 client nonce")
                self._nonce_value = int(nonce)
            username = _user_field(credentials._username, greeting)
            address = bytes(4) + self._address + bytes(16)
            prefix = struct.pack("<I", 3) + self._guid * 2
            common = (
                address
                + bytes(8)
                + struct.pack("<III", 0, self._client_type, self._nonce_value)
            )
            if greeting.version < 11:
                self._command = 257
                secret = (
                    hashlib.sha1(
                        (credentials.md5_text + f"{greeting.challenge:08d}").encode(
                            "ascii"
                        )
                    ).digest()
                    if greeting.security
                    else credentials._password
                )
                body = (
                    prefix + username + secret.ljust(64, b"\x00") + common + bytes(28)
                )
            else:
                self._command = 261
                try:
                    key = self._rsa_factory()
                except Exception:  # noqa: BLE001 -- private provider exception boundary
                    raise CodecError("N9000 private provider failed") from None
                if not isinstance(key, RsaKeyPair):
                    raise CodecError("invalid N9000 RSA provider")
                self._rsa = key
                secret = (
                    hashlib.sha512(
                        (credentials.md5_text + "#" + str(greeting.challenge)).encode(
                            "ascii"
                        )
                    ).digest()
                    if greeting.security
                    else credentials._password
                )
                body = (
                    prefix
                    + common
                    + struct.pack("<I", 1)
                    + username
                    + secret.ljust(64, b"\x00")
                    + struct.pack("<BBHI", 1, 1, 1, len(key.public_pem))
                    + key.public_pem
                )
            raw = (
                struct.pack(
                    "<IIHBBIII",
                    _MAGIC,
                    16 + len(body),
                    3,
                    0,
                    1,
                    self._command,
                    self._sequence,
                    len(body),
                )
                + body
            )
            self._state = "awaiting_reply"
            return PrivateWire(raw)
        except CodecError:
            self.close()
            raise
        except Exception:  # noqa: BLE001 -- private injected provider error boundary
            self.close()
            raise CodecError("N9000 private provider failed") from None

    def accept_reply(self, packet: Packet, *, generation: int) -> LoginResult | None:
        if self._state != "awaiting_reply":
            raise CodecError("N9000 attempt is not awaiting reply")
        try:
            if (
                type(generation) is not int
                or generation != self._generation
                or not isinstance(packet, Packet)
                or type(packet.body) is not bytes
                or len(packet.body) > 65512
            ):
                raise CodecError("N9000 reply does not match attempt")
            body = packet.body
            if packet.command in _STARTUP_BODY_LENGTHS:
                if not _is_startup_header(
                    packet.command,
                    packet.sequence,
                    packet.flags,
                    packet.encoding,
                    len(body),
                ):
                    raise CodecError("invalid N9000 unsolicited packet")
                # 2561 follows source default return; ml2/il2 are state events,
                # not login replies. No body interpretation, app callbacks,
                # channel/config effects or R3 negotiation is performed here.
                return None
            if (
                packet.sequence != self._sequence
                or packet.command & 0x0FFFFFFF != self._command
                or packet.command >> 28 not in (1, 2)
            ):
                raise CodecError("N9000 reply does not match attempt")
            if packet.command >> 28 == 2:
                if len(body) != 268 or struct.unpack_from("<H", body, 20)[0] > 246:
                    raise CodecError("invalid N9000 rejection body")
                raise LoginRejected(struct.unpack_from("<I", body)[0])
            greeting, credentials = self._greeting, self._credentials
            if greeting is None or credentials is None:
                raise CodecError("invalid N9000 attempt state")
            width = 132 if self._command == 257 else 292
            if len(body) < width:
                raise CodecError("short N9000 login reply")
            # jz0.b / ServerNVMSHeader.h.b at16 is a source-parsed int that
            # every inspected success consumer ignores. It is not evidence of
            # rejection; action2 uses oz0.a at0 in the separate failure path.
            verified = False
            if self._command == 257:
                proof, key, session = body[48:68], body[68:84], body[84:100]
                if greeting.security:
                    expected = hashlib.sha1(
                        (credentials.md5_text + str(self._nonce_value)).encode("ascii")
                    ).digest()
                    if not hmac.compare_digest(expected, proof):
                        raise CodecError("N9000 server proof mismatch")
                    verified = True
            else:
                if self._rsa is None:
                    raise CodecError("missing private N9000 RSA key")
                proof, session = body[52:116], body[244:260]
                key = self._rsa._decrypt(body[116:244])
                # cw3.Z9 ignores the newer digest. Key decryption is not a
                # verified server credential proof and cannot confer authority.
            result = LoginResult(
                body[:16],
                session,
                key,
                body[width:],
                proof,
                verified,
                True,
                peer_version=packet.peer_version,
            )
            self.close()
            return result
        except CodecError:
            self.close()
            raise
