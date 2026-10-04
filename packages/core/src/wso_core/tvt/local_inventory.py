"""Private N9000 inventory and fixed plaintext metadata reads; no device control."""

from __future__ import annotations

import re
import struct
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import NoReturn, SupportsIndex
from xml.parsers import expat

from .local_n9000 import CodecError, LoginResult, PrivateWire, UnsupportedBranch


class Availability(Enum):
    IDENTITY_AVAILABLE = "identity_available"
    SERIAL_UNVERIFIED = "serial_unverified"
    CHANNELS_UNAVAILABLE = "channels_unavailable"
    UNSUPPORTED_TAIL = "unsupported_tail"


class ReadQuery(Enum):
    BASIC = "queryBasicCfg"
    CHANNELS = "queryNodeList"
    USER = "doLogin"
    PERMISSIONS = "queryAuthGroup"


@dataclass(frozen=True, slots=True)
class InventoryLimits:
    """Helper policy bounds, not recovered APK validation guarantees."""

    max_tail_bytes: int = 65512
    max_channels: int = 256
    max_extensions: int = 64
    max_xml_bytes: int = 65512
    max_xml_depth: int = 16
    max_xml_nodes: int = 2048
    max_text_bytes: int = 512
    max_queries: int = 16

    def __post_init__(self) -> None:
        ceilings = (65512, 4096, 1024, 65512, 64, 16384, 4096, 256)
        values = (
            self.max_tail_bytes,
            self.max_channels,
            self.max_extensions,
            self.max_xml_bytes,
            self.max_xml_depth,
            self.max_xml_nodes,
            self.max_text_bytes,
            self.max_queries,
        )
        for value, ceiling in zip(values, ceilings, strict=True):
            _integer(value, 1, ceiling)


class _Private:
    __slots__ = ()

    def __repr__(self) -> str:
        return f"<{type(self).__name__}: private>"

    def __reduce_ex__(self, protocol: SupportsIndex) -> NoReturn:
        raise TypeError("private inventory cannot be serialized")


class _Immutable(_Private):
    __slots__ = ()

    def __setattr__(self, name: str, value: object) -> NoReturn:
        raise AttributeError("private inventory record is immutable")

    def __delattr__(self, name: str) -> NoReturn:
        raise AttributeError("private inventory record is immutable")


class ChannelRecord(_Immutable):
    __slots__ = ("guid", "kind", "name", "position", "raw_index", "window_index")
    guid: bytes
    kind: str
    window_index: int
    raw_index: int
    position: int
    name: str | None

    def __init__(
        self,
        guid: bytes,
        kind: str,
        window_index: int,
        raw_index: int,
        position: int,
        name: str | None = None,
    ) -> None:
        _guid(guid)
        if kind not in ("analog", "digital", "recorder"):
            raise CodecError("invalid private channel record")
        _integer(window_index, -128, 65535)
        _integer(raw_index, -128, 65535)
        _integer(position, 0, 4096)
        _record_text(name)
        for key, value in zip(
            ("guid", "kind", "window_index", "raw_index", "position", "name"),
            (guid, kind, window_index, raw_index, position, name),
            strict=True,
        ):
            object.__setattr__(self, key, value)


class UserMetadata(_Immutable):
    __slots__ = (
        "admin_name",
        "auth_group_id",
        "default_admin",
        "system_auth",
        "user_id",
    )
    user_id: str
    auth_group_id: str | None
    admin_name: str | None
    default_admin: bool
    system_auth: tuple[tuple[str, bool], ...] | None

    def __init__(
        self,
        user_id: str,
        auth_group_id: str | None,
        admin_name: str | None,
        default_admin: bool,
        system_auth: tuple[tuple[str, bool], ...] | None,
    ) -> None:
        _identifier(user_id)
        if auth_group_id is not None:
            _identifier(auth_group_id)
        if type(default_admin) is not bool:
            raise CodecError("invalid private user record")
        _record_text(admin_name)
        _claims(system_auth)
        for key, value in zip(
            ("user_id", "auth_group_id", "admin_name", "default_admin", "system_auth"),
            (user_id, auth_group_id, admin_name, default_admin, system_auth),
            strict=True,
        ):
            object.__setattr__(self, key, value)


class PermissionMetadata(_Immutable):
    __slots__ = ("guid", "symbols")
    guid: bytes
    symbols: frozenset[str]

    def __init__(self, guid: bytes, symbols: frozenset[str]) -> None:
        _guid(guid)
        if type(symbols) is not frozenset or not symbols <= {"ptz", "spr", "ad", "lp"}:
            raise CodecError("invalid private permission record")
        object.__setattr__(self, "guid", guid)
        object.__setattr__(self, "symbols", symbols)


class InventoryEvidence(_Immutable):
    __slots__ = (
        "channels",
        "channels_complete",
        "generation",
        "key_extracted",
        "permission_system",
        "permissions",
        "permissions_complete",
        "proof_verified",
        "serial",
        "serial_matched",
        "tail_supported",
        "user",
    )
    serial: str | None
    serial_matched: bool
    channels: tuple[ChannelRecord, ...]
    channels_complete: bool
    tail_supported: bool
    proof_verified: bool
    key_extracted: bool
    user: UserMetadata | None
    permissions: tuple[PermissionMetadata, ...]
    permissions_complete: bool
    generation: int
    permission_system: tuple[tuple[str, bool], ...] | None

    def __init__(
        self,
        serial: str | None,
        serial_matched: bool,
        channels: tuple[ChannelRecord, ...],
        channels_complete: bool,
        tail_supported: bool,
        proof_verified: bool,
        key_extracted: bool,
        user: UserMetadata | None = None,
        permissions: tuple[PermissionMetadata, ...] = (),
        permissions_complete: bool = False,
        *,
        generation: int,
        permission_system: tuple[tuple[str, bool], ...] | None = None,
    ) -> None:
        _integer(generation, 1, 0x7FFFFFFFFFFFFFFF)
        if (
            type(channels) is not tuple
            or len(channels) > 4096
            or any(type(channel) is not ChannelRecord for channel in channels)
            or type(permissions) is not tuple
            or len(permissions) > 4096
            or any(
                type(permission) is not PermissionMetadata for permission in permissions
            )
            or (user is not None and type(user) is not UserMetadata)
            or any(
                type(value) is not bool
                for value in (
                    serial_matched,
                    channels_complete,
                    tail_supported,
                    proof_verified,
                    key_extracted,
                    permissions_complete,
                )
            )
        ):
            raise CodecError("invalid immutable private inventory evidence")
        if serial is not None:
            _serial(serial)
        if serial_matched and serial is None:
            raise CodecError("invalid private serial evidence")
        _claims(permission_system)
        values = (
            serial,
            serial_matched,
            channels,
            channels_complete,
            tail_supported,
            proof_verified,
            key_extracted,
            user,
            permissions,
            permissions_complete,
            generation,
            permission_system,
        )
        for key, value in zip(
            (
                "serial",
                "serial_matched",
                "channels",
                "channels_complete",
                "tail_supported",
                "proof_verified",
                "key_extracted",
                "user",
                "permissions",
                "permissions_complete",
                "generation",
                "permission_system",
            ),
            values,
            strict=True,
        ):
            object.__setattr__(self, key, value)

    @property
    def availability(self) -> Availability:
        if not self.tail_supported:
            return Availability.UNSUPPORTED_TAIL
        if not self.serial_matched:
            return Availability.SERIAL_UNVERIFIED
        if not self.channels_complete:
            return Availability.CHANNELS_UNAVAILABLE
        return Availability.IDENTITY_AVAILABLE

    @property
    def authorized(self) -> bool:
        return False

    @property
    def live(self) -> bool:
        return False


class InventoryRejected(CodecError):
    def __init__(self, code: int) -> None:
        self.code = code
        super().__init__("private inventory reply rejected")


def _integer(value: int, low: int, high: int) -> None:
    if type(value) is not int or not low <= value <= high:
        raise CodecError("invalid private inventory numeric field")


def _serial(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9]{1,63}", value):
        raise CodecError("invalid private inventory serial")
    return value.upper()


def _returned_serial(raw: bytes) -> str | None:
    valid = True
    value = ""
    try:
        value = raw.decode("utf-8", "strict")
    except UnicodeError:
        valid = False
    if not valid:
        raise CodecError("invalid private inventory serial encoding")
    value = value.strip("".join(chr(index) for index in range(33)))
    return _serial(value) if value else None


def _guid(value: bytes) -> bytes:
    if type(value) is not bytes or len(value) != 16 or value == bytes(16):
        raise CodecError("invalid private inventory GUID")
    return value


def _guid_text(value: str) -> bytes:
    if re.fullmatch(r"\{[0-9a-fA-F-]{36}\}", value):
        value = value[1:-1]
    if not re.fullmatch(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", value):
        raise CodecError("invalid private inventory GUID text")
    return _guid(uuid.UUID(value).bytes_le)


def _ordered(channels: list[ChannelRecord]) -> tuple[ChannelRecord, ...]:
    if (
        len({c.guid for c in channels}) != len(channels)
        or len({c.window_index for c in channels}) != len(channels)
        or len({c.raw_index for c in channels}) != len(channels)
    ):
        raise CodecError("duplicate private inventory identity")
    return tuple(
        ChannelRecord(c.guid, c.kind, c.window_index, c.raw_index, index, c.name)
        for index, c in enumerate(
            sorted(channels, key=lambda channel: channel.window_index), 1
        )
    )


def _tail(
    login: LoginResult, expected: str, limits: InventoryLimits, generation: int
) -> InventoryEvidence:
    raw = login.channel_tail
    if type(raw) is not bytes or len(raw) > limits.max_tail_bytes:
        raise CodecError("private inventory tail bound exceeded")
    offset = extensions = 0
    serial: str | None = None
    seen_serial = seen_channels = False
    supported = True
    channels: list[ChannelRecord] = []
    while offset < len(raw):
        if len(raw) - offset < 8 or extensions >= limits.max_extensions:
            raise CodecError("invalid private inventory extension header")
        kind, _auxiliary, width, count = struct.unpack_from("<hhhh", raw, offset)
        offset += 8
        extensions += 1
        if width < 0 or count < 0 or width * count > len(raw) - offset:
            raise CodecError("invalid private inventory extension length")
        end = offset + width * count
        # Exact APK C7/t7 consume a/c/d only; signed16 b is opaque and discarded.
        if kind == 1:
            if seen_channels or count > limits.max_channels:
                raise CodecError("invalid private inventory channel count")
            seen_channels = True
            if width != 20:
                supported = False
            else:
                for index in range(count):
                    start = offset + width * index
                    channel_type, window, raw_index, reserved = struct.unpack_from(
                        "<bbbb", raw, start
                    )
                    if channel_type not in (0, 1, 2) or reserved:
                        supported = False
                    else:
                        channels.append(
                            ChannelRecord(
                                _guid(raw[start + 4 : start + 20]),
                                ("analog", "digital", "recorder")[channel_type],
                                window,
                                raw_index,
                                0,
                            )
                        )
        elif kind == 2:
            if seen_serial or count != 1 or width > 64:
                raise CodecError("invalid private inventory serial extension")
            seen_serial = True
            serial = _returned_serial(raw[offset:end])
        else:
            supported = False
        offset = end
    if serial is not None and serial != expected:
        raise CodecError("private inventory serial mismatch")
    ordered = _ordered(channels)
    return InventoryEvidence(
        serial,
        serial is not None,
        ordered if supported else (),
        seen_channels and supported,
        supported,
        login.proof_verified,
        login.key_extracted,
        generation=generation,
    )


def _xml(raw: bytes, limits: InventoryLimits) -> ET.Element:
    if type(raw) is not bytes or not 0 < len(raw) <= limits.max_xml_bytes:
        raise CodecError("private inventory XML bound exceeded")
    # Z9/security0 rb: bounded opaque bytes precede the first XML declaration.
    # They are discarded without assigning structure or decoding supplier bytes.
    marker = raw.find(b"<?xml")
    if marker >= 0:
        raw = raw[marker:]
    raw = raw.strip(bytes(range(33)))  # Java String.trim edge characters.
    if not raw or b"\x00" in raw:
        raise CodecError("invalid private inventory XML")
    valid = True
    text = ""
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        valid = False
    if not valid:
        raise CodecError("invalid private inventory XML encoding")
    builder = ET.TreeBuilder()
    parser = expat.ParserCreate("UTF-8")
    depth = nodes = 0
    text_sizes: list[int] = []

    def start(tag: str, attrs: dict[str, str]) -> None:
        nonlocal depth, nodes
        if (
            depth >= limits.max_xml_depth
            or nodes >= limits.max_xml_nodes
            or len(attrs) > 8
            or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.-]*", tag)
            or any(
                len(value.encode("utf-8")) > limits.max_text_bytes
                for value in attrs.values()
            )
        ):
            raise CodecError("private inventory XML structure bound exceeded")
        depth += 1
        nodes += 1
        text_sizes.append(0)
        builder.start(tag, attrs)

    def end(tag: str) -> None:
        nonlocal depth
        builder.end(tag)
        depth -= 1
        text_sizes.pop()

    def data(value: str) -> None:
        if text_sizes:
            text_sizes[-1] += len(value.encode("utf-8"))
            if text_sizes[-1] > limits.max_text_bytes:
                raise CodecError("private inventory XML text bound exceeded")
        builder.data(value)

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = data

    def forbidden(*args: object) -> NoReturn:
        raise CodecError("private inventory external declarations forbidden")

    parser.StartDoctypeDeclHandler = forbidden
    parser.EntityDeclHandler = forbidden
    parser.ExternalEntityRefHandler = forbidden
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    failed = False
    element: ET.Element | None = None
    try:
        parser.Parse(text.encode("utf-8"), True)
        element = builder.close()
    except (expat.ExpatError, CodecError, ValueError):
        failed = True
    if failed or element is None:
        raise CodecError("invalid private inventory XML")
    return element


def _children(element: ET.Element, allowed: set[str]) -> dict[str, ET.Element]:
    result: dict[str, ET.Element] = {}
    for child in element:
        if child.tag not in allowed:
            continue  # Source consumers ignore catalog/supplemental fields.
        if child.tag in result:
            raise CodecError("invalid private inventory XML fields")
        result[child.tag] = child
    return result


def _scalar(element: ET.Element) -> str:
    if len(element):
        raise CodecError("invalid private inventory XML scalar")
    return (element.text or "").strip()


def _identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.{}-]{1,64}", value):
        raise CodecError("invalid private inventory metadata identifier")
    return value


def _record_text(value: str | None) -> None:
    if value is None:
        return
    if type(value) is not str or "\x00" in value:
        raise CodecError("invalid private inventory text")
    valid = True
    raw = b""
    try:
        raw = value.encode("utf-8", "strict")
    except UnicodeError:
        valid = False
    if not valid or len(raw) > 4096:
        raise CodecError("invalid private inventory text")


def _claims(value: tuple[tuple[str, bool], ...] | None) -> None:
    if value is None:
        return
    if type(value) is not tuple or len(value) > 11:
        raise CodecError("invalid private inventory claims")
    seen: set[str] = set()
    for pair in value:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not str
            or type(pair[1]) is not bool
            or pair[0] not in _SYSTEM_FIELDS
            or pair[0] in seen
        ):
            raise CodecError("invalid private inventory claims")
        seen.add(pair[0])


_CHANNEL_CONTENT = (
    '<nodeType type="nodeType">chls</nodeType><requireField><name/><ip/>'
    "<chlIndex/><chlType/><winIndex/><presetCount/><cruiseCount/></requireField>"
)
_SYSTEM_FIELDS = {
    "remoteSysCfgAndMaintain",
    "alarmMgr",
    "net",
    "rec",
    "remoteChlMgr",
    "diskMgr",
    "scheduleMgr",
    "securityMgr",
    "facePersonnalInfoMgr",
    "previewAndSnap",
    "playback",
}
_DEFAULT_LIMITS = InventoryLimits()


class InventorySession(_Private):
    """Trusted same-attempt login binding; current actor permits metadata only."""

    __slots__ = (
        "_authority",
        "_expected",
        "_generation",
        "_inventory",
        "_limits",
        "_login",
        "_peer_version",
        "_pending",
        "_security",
        "_sequences",
        "_state",
        "_username",
    )

    def __init__(
        self,
        *,
        login: LoginResult,
        generation: int,
        expected_serial: str,
        username: str,
        security: int,
        read_authority: Callable[[int], bool],
        peer_version: int = 3,
        limits: InventoryLimits = _DEFAULT_LIMITS,
    ) -> None:
        _integer(generation, 1, 0x7FFFFFFFFFFFFFFF)
        _integer(security, 0, 2)
        _integer(peer_version, 1, 32767)
        if (
            type(login) is not LoginResult
            or type(limits) is not InventoryLimits
            or not callable(read_authority)
        ):
            raise CodecError("invalid private inventory context")
        if (
            any(
                type(value) is not bool
                for value in (
                    login.proof_verified,
                    login.key_extracted,
                    login.serial_validated,
                    login.authorized,
                    login.live,
                )
            )
            or login.authorized
            or login.live
            or not login.key_extracted
            or type(login.key_material) is not bytes
            or not 1 <= len(login.key_material) <= 117
            or type(login.device_guid) is not bytes
            or len(login.device_guid) != 16
            or type(login.session_guid) is not bytes
            or len(login.session_guid) != 16
            or type(login.reply_proof) is not bytes
            or len(login.reply_proof) not in (20, 64)
        ):
            raise CodecError("invalid private inventory login evidence")
        if type(username) is not str or not username or "\x00" in username:
            raise CodecError("invalid private inventory username")
        valid = True
        user = b""
        try:
            user = username.encode("utf-8", "strict")
        except UnicodeError:
            valid = False
        if not valid or len(user) > 63:
            raise CodecError("invalid private inventory username")
        self._login: LoginResult | None = login
        self._generation, self._expected = generation, _serial(expected_serial)
        self._username, self._security, self._peer_version = (
            user,
            security,
            peer_version,
        )
        self._authority, self._limits = read_authority, limits
        self._inventory = _tail(login, self._expected, limits, generation)
        self._state = "ready"
        self._pending: tuple[ReadQuery, int] | None = None
        self._sequences: set[int] = set()

    @property
    def inventory(self) -> InventoryEvidence:
        return self._inventory

    @property
    def state(self) -> str:
        return self._state

    def close(self) -> None:
        self._state = "terminal"
        self._login = None
        self._pending = None
        self._username = b""
        self._authority = lambda generation: False

    def _guard(self, generation: int) -> None:
        if (
            type(generation) is not int
            or generation != self._generation
            or self._state == "terminal"
        ):
            self.close()
            raise CodecError("private inventory generation is not current")
        failed = False
        permitted: object = False
        try:
            permitted = self._authority(generation)
        except Exception:  # noqa: BLE001 - private supplier failure must be fully sanitized
            failed = True
        if failed or permitted is not True:
            self.close()
            raise CodecError("private inventory metadata authority denied")

    def build_query(
        self, query: ReadQuery, *, sequence: int, generation: int
    ) -> PrivateWire:
        self._guard(generation)
        try:
            _integer(sequence, 0, 0x7FFFFFFF)
            if (
                type(query) is not ReadQuery
                or self._state != "ready"
                or sequence in self._sequences
                or len(self._sequences) >= self._limits.max_queries
            ):
                raise CodecError("private inventory query is not available")
            if not self._inventory.tail_supported:
                raise UnsupportedBranch("inventory_tail")
            if self._security:
                raise UnsupportedBranch("encrypted_xml")
            if query is not ReadQuery.BASIC and not self._inventory.serial_matched:
                raise CodecError("private inventory serial is unverified")
            content = ""
            if query is ReadQuery.CHANNELS:
                content = _CHANNEL_CONTENT
            elif query is ReadQuery.PERMISSIONS:
                if not self._inventory.channels_complete:
                    raise UnsupportedBranch("permission_channels_missing")
                user = self._inventory.user
                if user is None or user.auth_group_id is None:
                    raise UnsupportedBranch("permission_group_missing")
                content = (
                    "<condition><authGroupId>"
                    + user.auth_group_id
                    + "</authGroupId></condition><requireField><chlAuth/><systemAuth/></requireField>"
                )
            xml = (
                "<?xml version='1.0' encoding='utf-8'?><request version='1.0' "
                "systemType='NVMS-9000' clientType='MOBILE' url='"
                + query.value
                + "'>"
                + content
                + "</request>"
            ).encode("utf-8")
            body = (
                self._username.ljust(64, b"\0")
                + query.value.encode("ascii").ljust(64, b"\0")
                + xml
            )
            if len(body) > 65512:
                raise CodecError("private inventory query bound exceeded")
            self._pending = (query, sequence)
            self._sequences.add(sequence)
            self._state = "awaiting_reply"
            return PrivateWire(
                struct.pack(
                    "<IIHBBIII",
                    825307441,
                    16 + len(body),
                    3,
                    0,
                    1,
                    2331,
                    sequence,
                    len(body),
                )
                + body
            )
        except CodecError:
            self.close()
            raise

    def accept_reply(self, wire: bytes, *, generation: int) -> InventoryEvidence:
        self._guard(generation)
        error: CodecError | None = None
        evidence: InventoryEvidence | None = None
        try:
            if self._state != "awaiting_reply" or self._pending is None:
                raise CodecError("private inventory is not awaiting reply")
            if type(wire) is not bytes or not 24 <= len(wire) <= 65536:
                raise CodecError("invalid private inventory framed reply")
            magic, outer, version, flags, encoding, command, sequence, size = (
                struct.unpack_from("<IIHBBIII", wire)
            )
            if magic == 825307441 and outer == 0xFFFFFFFF:
                raise UnsupportedBranch("metadata_fragmentation")
            query, expected_sequence = self._pending
            if (
                magic != 825307441
                or outer != len(wire) - 8
                or size != len(wire) - 24
                or version not in (3, self._peer_version)
                or flags != 0
                or encoding not in (0, 1)
                or command & 0x0FFFFFFF != 2331
                or command >> 28 not in (1, 2)
                or sequence != expected_sequence
            ):
                raise CodecError("private inventory reply does not match query")
            body = wire[24:]
            if command >> 28 == 2:
                if len(body) != 268 or struct.unpack_from("<H", body, 20)[0] > 246:
                    raise CodecError("invalid private inventory failure body")
                raise InventoryRejected(struct.unpack_from("<I", body)[0])
            root = _xml(body, self._limits)
            # Source b9 dispatches pending W2/sequence, not XML root/attribute IDs.
            fields = _children(root, {"status", "content", "errorCode"})
            if "status" not in fields or _scalar(fields["status"]) != "success":
                code = 0
                if "errorCode" in fields:
                    value = _scalar(fields["errorCode"])
                    if not re.fullmatch(r"[0-9]{1,10}", value):
                        raise CodecError("invalid private inventory rejection code")
                    code = int(value)
                    _integer(code, 0, 0xFFFFFFFF)
                raise InventoryRejected(code)
            if "content" not in fields:
                raise CodecError("missing private inventory XML content")
            evidence = self._apply(query, fields["content"])
        except CodecError as failure:
            # Raise outside the handler so XML/supplier context is not retained.
            error = failure
        if error is not None:
            self.close()
            error.__traceback__ = None
            raise error from None
        assert evidence is not None
        self._guard(generation)
        self._inventory = evidence
        self._pending = None
        self._state = "ready"
        return evidence

    def _apply(self, query: ReadQuery, content: ET.Element) -> InventoryEvidence:
        old = self._inventory
        serial, matched = old.serial, old.serial_matched
        channels, complete = old.channels, old.channels_complete
        user, permissions, permissions_complete = (
            old.user,
            old.permissions,
            old.permissions_complete,
        )
        permission_system = old.permission_system
        if query is ReadQuery.BASIC:
            # b8 consumes selected fields; this minimal evidence retains SN only.
            fields = _children(content, {"sn"})
            returned = (
                _serial(_scalar(fields["sn"]))
                if "sn" in fields and _scalar(fields["sn"])
                else None
            )
            if returned is not None and returned != self._expected:
                raise CodecError("private inventory serial mismatch")
            serial, matched = returned, returned is not None
            if not matched:
                user, permissions, permissions_complete, permission_system = (
                    None,
                    (),
                    False,
                    None,
                )
        elif query is ReadQuery.CHANNELS:
            channels = self._channel_xml(content)
            # Selected E9/8193 -> D8 supplies details, not no-tail roster proof.
            complete = old.channels_complete
            permissions, permissions_complete, permission_system = (), False, None
        elif query is ReadQuery.USER:
            fields = _children(
                content,
                {
                    "userId",
                    "authGroupId",
                    "adminName",
                    "modifyPassword",
                    "systemAuth",
                    "userType",
                },
            )
            uid = (
                _identifier(_scalar(fields["userId"]))
                if "userId" in fields and _scalar(fields["userId"])
                else None
            )
            group = (
                _identifier(_scalar(fields["authGroupId"]))
                if "authGroupId" in fields and _scalar(fields["authGroupId"])
                else None
            )
            admin = _scalar(fields["adminName"]) if "adminName" in fields else None
            system_auth = (
                self._system(fields["systemAuth"]) if "systemAuth" in fields else None
            )
            if "modifyPassword" in fields and _scalar(fields["modifyPassword"]) not in (
                "true",
                "false",
            ):
                raise CodecError("invalid private user metadata")
            user = (
                UserMetadata(
                    uid,
                    group,
                    admin,
                    "userType" in fields
                    and _scalar(fields["userType"]) == "default_admin",
                    system_auth,
                )
                if uid is not None
                else None
            )
            permissions, permissions_complete, permission_system = (), False, None
        else:
            if user is None or user.auth_group_id is None:
                raise CodecError("missing private permission-group identity")
            # Q7 uses descendant selectors. Restrict them to this admitted
            # content, excluding the unconsumed sibling types catalog.
            fields = {}
            for name in ("chlAuth", "systemAuth"):
                matches = list(content.iter(name))
                if len(matches) > 1:
                    raise CodecError("duplicate private permission metadata")
                if matches:
                    fields[name] = matches[0]
            if "chlAuth" not in fields:
                raise CodecError("missing private channel permissions")
            node = fields["chlAuth"]
            items = [item for item in node if item.tag == "item"]
            if len(items) > self._limits.max_channels:
                raise CodecError("private permission count bound exceeded")
            parsed: list[PermissionMetadata] = []
            known = {c.guid for c in channels}
            for item in items:
                if "id" not in item.attrib:
                    raise CodecError("invalid private permission item")
                guid = _guid_text(item.attrib["id"])
                if guid not in known or any(p.guid == guid for p in parsed):
                    raise CodecError("foreign or duplicate private permission GUID")
                auth = _children(item, {"auth"})
                if "auth" not in auth:
                    raise CodecError("missing private permission symbols")
                value = _scalar(auth["auth"])
                if not re.fullmatch(r"(?:@(?:ptz|spr|ad|lp))*", value):
                    raise UnsupportedBranch("permission_symbols")
                symbols = value.split("@")[1:]
                if len(set(symbols)) != len(symbols):
                    raise CodecError("duplicate private permission symbol")
                parsed.append(PermissionMetadata(guid, frozenset(symbols)))
            permission_system = (
                self._system(fields["systemAuth"]) if "systemAuth" in fields else None
            )
            permissions, permissions_complete = (
                tuple(parsed),
                permission_system is not None,
            )
        return InventoryEvidence(
            serial,
            matched,
            channels,
            complete,
            old.tail_supported,
            old.proof_verified,
            old.key_extracted,
            user,
            permissions,
            permissions_complete,
            generation=self._generation,
            permission_system=permission_system,
        )

    def _system(self, element: ET.Element) -> tuple[tuple[str, bool], ...]:
        values: list[tuple[str, bool]] = []
        for name, node in _children(element, _SYSTEM_FIELDS).items():
            value = _scalar(node)
            if value not in ("true", "false"):
                raise CodecError("invalid private system-permission metadata")
            values.append((name, value == "true"))
        return tuple(values)

    def _channel_xml(self, content: ET.Element) -> tuple[ChannelRecord, ...]:
        # D8 does not consume total/count/content IDs; bound actual item records.
        items = [item for item in content if item.tag == "item"]
        _integer(len(items), 0, self._limits.max_channels)
        records: list[ChannelRecord] = []
        old = {channel.guid: channel for channel in self._inventory.channels}
        seen: set[bytes] = set()
        for item in items:
            if "id" not in item.attrib:
                raise CodecError("invalid private inventory channel item")
            guid = _guid_text(item.attrib["id"])
            fields = _children(
                item,
                {
                    "name",
                    "ip",
                    "chlIndex",
                    "chlType",
                    "winIndex",
                },
            )
            previous = old.get(guid)
            if guid in seen or (self._inventory.channels_complete and previous is None):
                raise CodecError(
                    "foreign or duplicate private inventory channel identity"
                )
            seen.add(guid)
            if (
                previous is None
                and not {"chlIndex", "chlType", "winIndex"} <= fields.keys()
            ):
                raise CodecError("unverified private inventory channel item")
            kind = (
                _scalar(fields["chlType"])
                if "chlType" in fields
                else (previous.kind if previous is not None else "")
            )
            if kind not in ("analog", "digital", "recorder"):
                raise UnsupportedBranch("channel_type")
            indices: list[int] = []
            for key in ("winIndex", "chlIndex"):
                if key not in fields and previous is not None:
                    indices.append(
                        previous.window_index
                        if key == "winIndex"
                        else previous.raw_index
                    )
                    continue
                value = _scalar(fields[key])
                if not re.fullmatch(r"-?[0-9]{1,5}", value):
                    raise CodecError("invalid private inventory channel index")
                number = int(value)
                _integer(number, -128, 65535)
                indices.append(number)
            if self._inventory.channels_complete and (
                previous is None
                or (kind, *indices)
                != (
                    previous.kind,
                    previous.window_index,
                    previous.raw_index,
                )
            ):
                raise CodecError("foreign private inventory channel identity")
            name = (
                _scalar(fields["name"])
                if "name" in fields
                else (previous.name if previous is not None else None)
            )
            records.append(ChannelRecord(guid, kind, indices[0], indices[1], 0, name))
        if self._inventory.channels_complete:
            records.extend(
                channel for channel in old.values() if channel.guid not in seen
            )
        return _ordered(records)
