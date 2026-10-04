"""Synthetic source-independent vectors: no device, credential or SDK execution.

Literal fields follow the retained Java layouts; hash literals were independently
calculated with the JDK MessageDigest oracle frozen in the evidence packet.
"""

import dataclasses
import importlib.util
import pickle
import struct

import pytest


def test_codec_exists_before_any_supported_attempt():
    assert importlib.util.find_spec("wso_core.tvt.local_n9000") is not None


def codec():
    from wso_core.tvt import local_n9000

    return local_n9000


# Greeting version10, security2, LE 24-bit challenge123, capability5, customer7.
GREETING = bytes.fromhex(
    "01000000 02000000 03000000 0a000000 04000000 05000000 06000000"
    "07000000 0102030405060708 09000000 027b0000 00000000 05000000"
    "07000000 00000000"
)
GUID = bytes.fromhex("443322116655887799aabbccddeeff00")
HEADER = bytes.fromhex("31313131fc00000003000001010100002a000000ec000000")


def greeting(security=0, version=10, challenge=123):
    value = bytearray(GREETING)
    value[12:16] = version.to_bytes(4, "little")
    value[44] = security
    value[45:48] = challenge.to_bytes(3, "little")
    return bytes(value)


def attempt(security=0, version=10, password="p@ss", **kwargs):
    c = codec()
    h = c.LoginHandshake(
        generation=7,
        sequence=42,
        credentials=c.Credentials("uSer", password),
        client_guid=GUID,
        client_address=bytes.fromhex("c0000201"),
        nonce_factory=lambda: "12345678",
        **kwargs,
    )
    return h, h.build_request(c.parse_greeting(greeting(security, version)))


def packet(body, command=0x10000101, sequence=42, flags=0, encoding=1):
    # Independent fixture envelope; tests below also check literal envelope.
    return (
        struct.pack(
            "<IIHBBIII",
            825307441,
            16 + len(body),
            3,
            flags,
            encoding,
            command,
            sequence,
            len(body),
        )
        + body
    )


def reply(proof=bytes(20), source_b=0, tail=b"<synthetic/>"):
    return (
        GUID
        + source_b.to_bytes(4, "little")
        + bytes(28)
        + proof
        + bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        + bytes.fromhex("102030405060708090a0b0c0d0e0f000")
        + bytes(32)
        + tail
    )


def test_exact_legacy_request_envelope_and_offsets():
    # Catches changed endian, header, GUID ordering, field sizes and command.
    _, wire = attempt()
    expected = (
        HEADER
        + bytes.fromhex("03000000")
        + GUID * 2
        + b"uSer"
        + bytes(60)
        + b"p@ss"
        + bytes(60)
        + bytes(4)
        + bytes.fromhex("c0000201")
        + bytes(16)
        + bytes(6)
        + bytes(2)
        + bytes(12)
        + bytes(28)
    )
    assert wire.data == expected
    assert len(wire.data) == 260
    assert "p@ss" not in repr(wire)


def test_greeting_widths_and_security():
    c = codec()
    g = c.parse_greeting(GREETING)
    assert (g.version, g.security, g.challenge, g.capability, g.customer_id) == (
        10,
        2,
        123,
        5,
        7,
    )
    assert c.parse_greeting(greeting(challenge=0xFFFFFF)).challenge == 16777215
    for value in (GREETING[:-1], GREETING + b"x"):
        with pytest.raises(c.CodecError):
            c.parse_greeting(value)
    with pytest.raises(c.UnsupportedBranch):
        c.parse_greeting(greeting(security=3))


@pytest.mark.parametrize(
    "username,password,kwargs",
    [
        ("a\x00b", "x", {}),
        ("x", "\x00", {}),
        ("x", "", {}),
        ("", "x", {}),
        ("x" * 64, "x", {}),
        ("가" * 22, "x", {}),
        ("x", "x" * 64, {}),
        ("x", "\ud800", {}),
    ],
)
def test_credentials_reject_lossy_or_implicit_inputs(username, password, kwargs):
    c = codec()
    with pytest.raises(c.CodecError):
        c.Credentials(username, password, **kwargs)


def test_credentials_private_untrimmed_utf8_and_explicit_empty():
    c = codec()
    cred = c.Credentials(" 가 ", " a ")
    h = c.LoginHandshake(generation=1, sequence=1, credentials=cred)
    data = h.build_request(c.parse_greeting(greeting())).data
    assert data[60:65] == " 가 ".encode()
    assert data[124:127] == b" a "
    assert " a " not in repr(cred)
    with pytest.raises(TypeError):
        dataclasses.asdict(cred)
    with pytest.raises(TypeError):
        pickle.dumps(cred)
    empty = c.Credentials("x", "", allow_empty_password=True)
    assert empty.md5_text == ""
    assert c.Credentials("x", "abc").md5_text == "900150983CD24FB0D6963F7D28E17F72"
    c.Credentials("x" * 63, "x" * 63)


def test_security2_conditional_xor_and_source_nonce_proof():
    c = codec()
    h, wire = attempt(security=2, password="abc")
    # 123 mask cycles; XOR only nonzero bytes unequal to mask, no zero padding XOR.
    assert wire.data[60:124] == bytes.fromhex("44615643") + bytes(60)
    assert wire.data[124:144].hex() == "42ec04c640180ef62049335f31992f8c3243793c"
    assert wire.data[228:232] == bytes.fromhex("4e61bc00")
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    parsed = c.N9000Stream().feed(packet(reply(proof)))
    result = h.accept_reply(parsed[0], generation=7)
    assert result.proof_verified
    assert result.key_material == bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    assert result.channel_tail == b"<synthetic/>"
    assert not result.authorized
    assert not result.serial_validated
    assert not result.live


@pytest.mark.parametrize(
    "nonce",
    ["00000000", "12345670", "1234567", "123456789", "１２３４５６７８", 12345678],
)
def test_secure_nonce_boundary_rejects_non_source_nonce(nonce):
    c = codec()
    h = c.LoginHandshake(
        generation=1,
        sequence=1,
        credentials=c.Credentials("x", "abc"),
        nonce_factory=lambda: nonce,
    )
    with pytest.raises(c.CodecError):
        h.build_request(c.parse_greeting(greeting(security=1)))


def test_unsecured_success_action_is_not_authentication_or_authority():
    c = codec()
    h, _ = attempt()
    result = h.accept_reply(c.N9000Stream().feed(packet(reply()))[0], generation=7)
    assert not result.proof_verified
    assert not result.authorized
    with pytest.raises(c.CodecError):
        h.build_request(c.parse_greeting(greeting()))


@pytest.mark.parametrize(
    "change", ["proof", "generation", "sequence", "failure_action", "truncated"]
)
def test_reply_failure_terminates_attempt_and_never_retries(change):
    c = codec()
    h, _ = attempt(security=1, password="abc")
    body = reply()
    command = 0x10000101
    if change == "failure_action":
        body = bytes.fromhex("28000020") + GUID + bytes(2) + bytes(246)
        command = 0x20000101
    if change == "truncated":
        body = body[:131]
    value = c.N9000Stream().feed(
        packet(body, command=command, sequence=41 if change == "sequence" else 42)
    )[0]
    with pytest.raises(c.CodecError):
        h.accept_reply(value, generation=8 if change == "generation" else 7)
    assert h.state == "terminal"
    with pytest.raises(c.CodecError):
        h.accept_reply(value, generation=7)


def test_source_error_lockout_is_private_and_terminal():
    c = codec()
    h, _ = attempt()
    body = (
        bytes.fromhex("28000020") + GUID + bytes.fromhex("0300") + b"bad" + bytes(243)
    )
    with pytest.raises(c.LoginRejected) as caught:
        h.accept_reply(
            c.N9000Stream().feed(packet(body, command=0x20000101))[0], generation=7
        )
    assert caught.value.code == 0x20000028
    assert "bad" not in str(caught.value)
    assert h.state == "terminal"


def test_raw_stream_split_at_every_byte_and_coalesced_heartbeat():
    c = codec()
    raw = packet(reply())
    for split in range(1, len(raw)):
        parser = c.N9000Stream()
        assert parser.feed(raw[:split]) == ()
        parsed = parser.feed(raw[split:])
        assert len(parsed) == 1
        assert parsed[0].body == reply()
    parser = c.N9000Stream()
    assert len(parser.feed(bytes.fromhex("3131313100000000") + raw + raw)) == 2


def fragment(payload, index, count, total, group=9):
    return (
        struct.pack(
            "<8I", 825307441, 0xFFFFFFFF, group, count, total, index, len(payload), 0
        )
        + payload
    )


def test_source_fragments_bounded_ordered_and_inner_lengths_checked():
    c = codec()
    inner = packet(reply())[8:]
    raw = fragment(inner[:30], 1, 2, len(inner)) + fragment(
        inner[30:], 2, 2, len(inner)
    )
    parser = c.N9000Stream()
    out = ()
    for value in raw:
        out += parser.feed(bytes([value]))
    assert len(out) == 1
    assert out[0].body == reply()
    for invalid in (
        fragment(b"x", 2, 2, 50),
        fragment(b"x", 1, 0, 50),
        fragment(b"x", 1, 2, 5000000),
        fragment(inner, 1, 1, len(inner) + 1),
    ):
        with pytest.raises(c.CodecError):
            c.N9000Stream().feed(invalid)


@pytest.mark.parametrize(
    "raw",
    [
        bytes.fromhex("3030303110000000"),
        bytes.fromhex("313131310f000000"),
        bytes.fromhex("3131313100004000"),
        bytes.fromhex("313131311000000004000001010100002a00000000000000"),
        bytes.fromhex("313131311000000003000001010100002a00000001000000"),
        bytes.fromhex("313131311000000003000201010100002a00000000000000"),
        bytes.fromhex("313131311000000003000001010500002a00000000000000"),
    ],
)
def test_malformed_raw_headers_fail_closed_and_clear_buffer(raw):
    c = codec()
    parser = c.N9000Stream()
    with pytest.raises(c.CodecError):
        parser.feed(raw)
    with pytest.raises(c.CodecError):
        parser.feed(b"")


def test_input_chunk_bound_before_copy_and_no_input_mutation():
    c = codec()
    parser = c.N9000Stream(max_packet_bytes=512, max_chunk_bytes=512)
    with pytest.raises(c.CodecError):
        parser.feed(bytes(513))
    raw = bytearray(packet(reply()))
    original = bytes(raw)
    parser = c.N9000Stream()
    parsed = parser.feed(raw)[0]
    assert raw == original
    raw[-1] = 0
    assert parsed.body == reply()


# Invented one-off1024-bit JDK keypair, not an actual device or account key.
PRIVATE_DER = "MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGBAIA6bjGjVVoytRR5t1UlEWYbeigHC0QkyXs5U7Fy/vEwU/4AcMp/xPV2RfkWqv72ihPXYzDhYMEskhZbXRdv3Yb9L90Q1s9lzuKTJcAQM44DDesI5+kxthusyw/5p8jvKM0BUhlTvPtvD0J3oeEaEGGGhqRXjCrNF+1Qs7AZrOP9AgMBAAECgYAMZdneqcSoXmu8qZIMxPM8NJ7ofNndglMKu324k/5LUplkXyWIprbj5sYYMdVhpnOuPG6GPNxOgSE00Suchv/bmNXJY8273AVd2DcYneyjvAMkMds2X0ij6gRUG0gC0Xhj54yfljxf2LPuUZ3cBA3W6hiwE2AY/KlzfAVjprkozwJBALoxC4MvbrmxdGohl7H5hljVwdYJggA1i3/yIrf7wPG63jrLs538pP990pjvIkE8U213w1/DMEQC93UDFi0+ducCQQCwTfmWQRN56GOxbp7nQYm/4Ra3JRhpb8nxKl6ym5qvq2hdQmrYuEY7YROIJwOILIOWDeHLJ8O9zrez3BX4RsV7AkAjk/maMLccvp77JL4i4QZd9UKbzqdLuO+WHEOsGmwtBMMwQvpohv1UYMucM529D3T1pvvrUZXoeRSmBFf5f0UjAkA4eXHGqKfVeBRfJMEv8LVwSmjdV7ufIpj8cIcPDXsaZHy0yu6w5y5QHQOFrIGcIC4yZdX7Hoy8AzijG4/KDNl7AkEAl4CuhvXAmbBQOLycyxcauTemllmczA7TKJxGrFZVbujZ8xUEo6ob6bJcdhHlC5QKtpwgixpx8TGR22eNOVcFAA=="
PUBLIC_PKCS1 = (
    b"-----BEGIN RSA PUBLIC KEY-----\n"
    b"MIGJAoGBAIA6bjGjVVoytRR5t1UlEWYbeigHC0QkyXs5U7Fy/vEwU/4AcMp/xPV2\n"
    b"RfkWqv72ihPXYzDhYMEskhZbXRdv3Yb9L90Q1s9lzuKTJcAQM44DDesI5+kxthus\n"
    b"yw/5p8jvKM0BUhlTvPtvD0J3oeEaEGGGhqRXjCrNF+1Qs7AZrOP9AgMBAAE=\n"
    b"-----END RSA PUBLIC KEY-----\n"
)
CIPHERTEXT = bytes.fromhex(
    "5dd4e29e63bf03751a4949ce65e49a50b6a570b4f9793713936a92b5190f0abdc405100e"
    "e2d18f9b945b3076614bf19016827bdb7d2a98d17ffd5426ad2d01db8590625d26f2298d"
    "d45ed5759d684f5ec7411635c891936d0ef567b2dd6dafab43a3f65eb1b89e3e02c5302c"
    "b98c7d1fa45848ed0a467d1f3cef251dfdc4d548"
)


def rsa_pair():
    import base64

    pem = (
        b"-----BEGIN PRIVATE KEY-----\n"
        + base64.b64encode(base64.b64decode(PRIVATE_DER))
        + b"\n-----END PRIVATE KEY-----\n"
    )
    return codec().RsaKeyPair.from_private_pem(pem)


def test_newer_exact_layout_public_key_and_sha512_jdk_vector():
    c = codec()
    key = rsa_pair()
    assert key.public_pem == PUBLIC_PKCS1
    h, wire = attempt(security=2, version=11, password="abc", rsa_factory=lambda: key)
    expected_body = (
        bytes.fromhex("03000000")
        + GUID * 2
        + bytes(4)
        + bytes.fromhex("c0000201")
        + bytes(16)
        + bytes(6)
        + bytes(2)
        + bytes(8)
        + bytes.fromhex("4e61bc0001000000")
        + bytes.fromhex("44615643")
        + bytes(60)
        + bytes.fromhex(
            "398f53b39047bca8651b3c4d9bcb2ee06b794a5c89d22b25880413f721ef64e4e98f735e67d786e2fb55c26d70adabdd64d6ec4e1974225a0f7b8be839542bb8"
        )
        + bytes.fromhex("01010100fb000000")
        + PUBLIC_PKCS1
    )
    assert wire.data == packet(expected_body, command=261)
    body = GUID + bytes(4) + bytes(32) + bytes(64) + CIPHERTEXT + bytes(48) + b"tail"
    result = h.accept_reply(
        c.N9000Stream().feed(packet(body, command=0x10000105))[0], generation=7
    )
    assert result.key_material == b"00112233445566778899AABBCCDDEEFF"
    assert result.channel_tail == b"tail"
    assert result.key_extracted
    assert not result.proof_verified  # APK never compares newer h.d digest.
    assert not result.authorized


def test_newer_raw_password_branch_and_invalid_rsa_reply_terminal():
    c = codec()
    h, wire = attempt(version=11, rsa_factory=rsa_pair)
    assert wire.data[108:172] == b"uSer" + bytes(60)
    assert wire.data[172:236] == b"p@ss" + bytes(60)
    body = GUID + bytes(4) + bytes(32) + bytes(64) + bytes(128) + bytes(48)
    with pytest.raises(c.CodecError):
        h.accept_reply(
            c.N9000Stream().feed(packet(body, command=0x10000105))[0], generation=7
        )
    assert h.state == "terminal"


def test_unsupported_security_and_invalid_private_key_are_precise_private_errors():
    c = codec()
    with pytest.raises(c.UnsupportedBranch) as caught:
        c.parse_greeting(greeting(security=255))
    assert caught.value.branch == "security_mode"
    with pytest.raises(c.CodecError) as caught:
        c.RsaKeyPair.from_private_pem(b"invented-invalid-private-input")
    assert "invented-invalid" not in str(caught.value)


def test_greeting_customer_id_offset_ignores_four_transport_padding_bytes():
    c = codec()
    raw = GREETING[:-4] + bytes.fromhex("ffffffff")
    assert c.parse_greeting(raw).customer_id == 7


@pytest.mark.parametrize("offset,value", [(8, 4), (10, 2), (11, 2), (20, 1), (12, 9)])
def test_actual_magic_packet_validates_each_inner_header_field(offset, value):
    c = codec()
    raw = bytearray(packet(b""))
    raw[offset] = value
    with pytest.raises(c.CodecError):
        c.N9000Stream().feed(raw)


def test_xor_equal_mask_and_zero_challenge_are_source_conditional():
    c = codec()
    cred = c.Credentials("121", "abc")
    h = c.LoginHandshake(
        generation=1, sequence=1, credentials=cred, nonce_factory=lambda: "11111111"
    )
    raw = h.build_request(c.parse_greeting(greeting(security=2))).data
    assert raw[60:63] == bytes.fromhex("313202")
    h = c.LoginHandshake(
        generation=1,
        sequence=1,
        credentials=c.Credentials("0A", "abc"),
        nonce_factory=lambda: "11111111",
    )
    raw = h.build_request(c.parse_greeting(greeting(security=2, challenge=0))).data
    assert raw[60:62] == bytes.fromhex("3071")


def test_secret_provider_exception_is_sanitized_and_terminal():
    c = codec()

    def failing_provider():
        raise RuntimeError("invented-provider-private-marker")

    h = c.LoginHandshake(
        generation=1,
        sequence=1,
        credentials=c.Credentials("x", "abc"),
        nonce_factory=failing_provider,
    )
    with pytest.raises(c.CodecError) as caught:
        h.build_request(c.parse_greeting(greeting(security=1)))
    assert "private-marker" not in str(caught.value)
    assert h.state == "terminal"


def test_private_values_refuse_mutation_and_serialization():
    c = codec()
    cred = c.Credentials("user", "invented-private-password")
    with pytest.raises(AttributeError):
        del cred._password
    with pytest.raises(AttributeError):
        cred._password = b"changed"
    h, wire = attempt()
    g = c.parse_greeting(GREETING)
    p = c.N9000Stream().feed(packet(reply()))[0]
    result = h.accept_reply(p, generation=7)
    for private in (wire, g, p, result, rsa_pair()):
        with pytest.raises(TypeError):
            pickle.dumps(private)
        assert "p@ss" not in repr(private)
    with pytest.raises(c.CodecError):
        c.Packet(0x10000101, 42, 2, 1, reply())
    with pytest.raises(c.CodecError):
        c.PrivateWire(bytearray(b"not-immutable"))


def test_dynamic_share_is_explicitly_unsupported_before_key_generation():
    c = codec()
    with pytest.raises(c.UnsupportedBranch) as caught:
        c.LoginHandshake(
            generation=1,
            sequence=1,
            credentials=c.Credentials("x", "abc"),
            credential_mode="dynamic_share",
        )
    assert caught.value.branch == "dynamic_share"


def test_fragment_reordered_interleaved_and_inconsistent_totals_terminate():
    c = codec()
    inner = packet(reply())[8:]
    first = fragment(inner[:30], 1, 3, len(inner))
    for second in (
        fragment(inner[30:], 3, 3, len(inner)),
        fragment(inner[30:], 2, 2, len(inner)),
        fragment(inner[30:], 2, 3, len(inner), group=8),
        packet(reply()),
    ):
        parser = c.N9000Stream()
        assert parser.feed(first) == ()
        with pytest.raises(c.CodecError):
            parser.feed(second)


@pytest.mark.parametrize(
    "generation,sequence", [(0, 1), (True, 1), (1, -1), (1, 0x80000000)]
)
def test_generation_and_sequence_admission(generation, sequence):
    c = codec()
    with pytest.raises(c.CodecError):
        c.LoginHandshake(
            generation=generation,
            sequence=sequence,
            credentials=c.Credentials("x", "abc"),
        )


def test_transport_disconnect_fences_partial_stream():
    c = codec()
    parser = c.N9000Stream()
    raw = packet(reply())
    assert parser.feed(raw[:40]) == ()
    parser.close()
    with pytest.raises(c.CodecError):
        parser.feed(raw[40:])


def test_default_secure_nonce_and_generated_rsa_match_source_parameters():
    from cryptography.hazmat.primitives import serialization

    c = codec()
    h = c.LoginHandshake(
        generation=1, sequence=1, credentials=c.Credentials("x", "abc")
    )
    raw = h.build_request(c.parse_greeting(greeting(security=1))).data
    nonce = str(int.from_bytes(raw[228:232], "little"))
    assert len(nonce) == 8 and all(char in "123456789" for char in nonce)
    key = c.RsaKeyPair.generate()
    public = serialization.load_pem_public_key(key.public_pem)
    assert public.key_size == 1024
    assert public.public_numbers().e == 65537


@pytest.mark.parametrize("provider", ["nonce", "rsa"])
@pytest.mark.parametrize(
    "exception_kind", ["codec", "subclass", "unsupported", "rejected"]
)
def test_provider_exception_boundary_replaces_codec_errors_and_private_attributes(
    provider, exception_kind
):
    # Catches the outer CodecError handler bypassing provider sanitization.
    c = codec()
    marker = "invented-Fix1-provider-private-marker"

    class PrivateProviderError(c.CodecError):
        pass

    error = {
        "codec": lambda: c.CodecError(marker),
        "subclass": lambda: PrivateProviderError(marker),
        "unsupported": lambda: c.UnsupportedBranch(marker),
        "rejected": lambda: c.LoginRejected(marker),
    }[exception_kind]()
    error.private_marker = marker

    def failing_provider():
        raise error

    kwargs = {f"{provider}_factory": failing_provider}
    h = c.LoginHandshake(
        generation=1, sequence=1, credentials=c.Credentials("x", "abc"), **kwargs
    )
    raw_greeting = greeting(
        security=1 if provider == "nonce" else 0,
        version=10 if provider == "nonce" else 11,
    )
    with pytest.raises(c.CodecError) as caught:
        h.build_request(c.parse_greeting(raw_greeting))
    assert type(caught.value) is c.CodecError
    assert caught.value is not error
    assert caught.value.args == ("N9000 private provider failed",)
    assert vars(caught.value) == {}
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__ is True
    assert marker not in str(caught.value)
    assert h.state == "terminal"
    with pytest.raises(c.CodecError) as repeated:
        h.build_request(c.parse_greeting(raw_greeting))
    assert repeated.value.args == ("N9000 login attempt cannot be repeated",)


@pytest.mark.parametrize("provider", ["nonce", "rsa"])
def test_provider_exception_boundary_preserves_internal_return_validation(provider):
    c = codec()
    kwargs = {f"{provider}_factory": lambda: object()}
    h = c.LoginHandshake(
        generation=1, sequence=1, credentials=c.Credentials("x", "abc"), **kwargs
    )
    raw_greeting = greeting(
        security=1 if provider == "nonce" else 0,
        version=10 if provider == "nonce" else 11,
    )
    with pytest.raises(c.CodecError) as caught:
        h.build_request(c.parse_greeting(raw_greeting))
    expected = (
        "invalid secure N9000 client nonce"
        if provider == "nonce"
        else "invalid N9000 RSA provider"
    )
    assert caught.value.args == (expected,)
    assert h.state == "terminal"
    with pytest.raises(c.UnsupportedBranch) as unsupported:
        c.parse_greeting(greeting(security=3))
    assert unsupported.value.branch == "security_mode"


# Shape matches the safe header summary only; body is invented GUID/state data.
RECEIVE_NOTIFICATION = (
    bytes.fromhex("31313131 34000000 06000000 030a0000 00000000 24000000")
    + GUID
    + bytes(16)
    + bytes.fromhex("01000000")
)


def receive_frame(
    body, *, peer_version=6, command=0x10000101, sequence=42, flags=0, encoding=0
):
    return (
        struct.pack(
            "<IIHBBIII",
            825307441,
            len(body) + 16,
            peer_version,
            flags,
            encoding,
            command,
            sequence,
            len(body),
        )
        + body
    )


def test_receive_negotiation_heartbeat_notification_keeps_login_pending():
    c = codec()
    g = c.parse_greeting(greeting(version=10))
    stream = c.N9000Stream(greeting=g)
    h, request = attempt()
    assert request.data[8:10] == bytes.fromhex("0300")
    parsed = stream.feed(bytes.fromhex("3131313100000000") + RECEIVE_NOTIFICATION)
    assert len(parsed) == 1
    assert (parsed[0].peer_version, parsed[0].command, parsed[0].sequence) == (
        6,
        2563,
        0,
    )
    assert h.accept_reply(parsed[0], generation=7) is None
    assert h.state == "awaiting_reply"
    # An unsolicited6 header does not pin the accepted login peer version.
    result = h.accept_reply(
        stream.feed(receive_frame(reply(), peer_version=8))[0], generation=7
    )
    assert result.peer_version == 8
    assert not result.proof_verified and not result.authorized and not result.live
    assert h.state == "terminal"


def test_receive_negotiation_literal_split_every_byte_and_fragmented_notification():
    c = codec()
    g = c.parse_greeting(greeting())
    for split in range(1, len(RECEIVE_NOTIFICATION)):
        stream = c.N9000Stream(greeting=g)
        assert stream.feed(RECEIVE_NOTIFICATION[:split]) == ()
        parsed = stream.feed(RECEIVE_NOTIFICATION[split:])
        assert len(parsed) == 1 and parsed[0].peer_version == 6
    inner = RECEIVE_NOTIFICATION[8:]
    stream = c.N9000Stream(greeting=g)
    assert stream.feed(fragment(inner[:20], 1, 2, len(inner))) == ()
    parsed = stream.feed(fragment(inner[20:], 2, 2, len(inner)))
    h, _ = attempt()
    assert h.accept_reply(parsed[0], generation=7) is None
    assert h.state == "awaiting_reply"


@pytest.mark.parametrize("peer_version", [1, 3, 6, 8, 32767])
def test_receive_negotiation_positive_signed_short_is_independent_of_greeting(
    peer_version,
):
    c = codec()
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting(version=10)))
    parsed = stream.feed(receive_frame(reply(), peer_version=peer_version))
    h, _ = attempt()
    result = h.accept_reply(parsed[0], generation=7)
    assert result.peer_version == peer_version


@pytest.mark.parametrize("peer_version", [0, 32768, 65535])
def test_receive_negotiation_rejects_invalid_peer_version_before_body_copy(
    peer_version,
):
    c = codec()
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting()))
    raw = receive_frame(reply(), peer_version=peer_version)
    with pytest.raises(c.CodecError):
        stream.feed(raw[:24])
    with pytest.raises(c.CodecError):
        stream.feed(raw[24:])


def test_receive_negotiation_unbound_defaults_stay_strict_and_greeting_is_typed():
    c = codec()
    for raw in (
        receive_frame(reply()),
        RECEIVE_NOTIFICATION,
        receive_frame(
            RECEIVE_NOTIFICATION[24:], peer_version=3, command=2563, sequence=0
        ),
    ):
        with pytest.raises(c.CodecError):
            c.N9000Stream().feed(raw)
    assert len(c.N9000Stream().feed(packet(reply()))) == 1
    with pytest.raises(c.CodecError):
        c.N9000Stream(greeting=object())


@pytest.mark.parametrize(
    "change",
    [
        "sequence",
        "action_reply",
        "action_error",
        "flags",
        "encoding",
        "short",
        "long",
        "unknown",
    ],
)
def test_receive_negotiation_invalid_notification_is_never_skipped(change):
    c = codec()
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting()))
    body = RECEIVE_NOTIFICATION[24:]
    command = {
        "action_reply": 0x10000A03,
        "action_error": 0x20000A03,
        "unknown": 2562,
    }.get(change, 2563)
    if change == "short":
        body = body[:-1]
    if change == "long":
        body += b"x"
    raw = receive_frame(
        body,
        command=command,
        sequence=1 if change == "sequence" else 0,
        flags=1 if change == "flags" else 0,
        encoding=1 if change == "encoding" else 0,
    )
    with pytest.raises(c.CodecError):
        stream.feed(raw)
    with pytest.raises(c.CodecError):
        stream.feed(RECEIVE_NOTIFICATION)


@pytest.mark.parametrize(
    "change", ["generation", "sequence", "action", "flags", "encoding", "short"]
)
def test_receive_negotiation_handshake_checks_notification_before_skip(change):
    c = codec()
    h, _ = attempt()
    body = (
        RECEIVE_NOTIFICATION[24:-1] if change == "short" else RECEIVE_NOTIFICATION[24:]
    )
    value = c.Packet(
        0x10000A03 if change == "action" else 2563,
        1 if change == "sequence" else 0,
        1 if change == "flags" else 0,
        1 if change == "encoding" else 0,
        body,
        peer_version=6,
    )
    with pytest.raises(c.CodecError):
        h.accept_reply(value, generation=8 if change == "generation" else 7)
    assert h.state == "terminal"


@pytest.mark.parametrize(
    "change", ["wrong_sequence", "wrong_command", "proof", "rejection"]
)
def test_receive_negotiation_notification_does_not_weaken_login_reply(change):
    c = codec()
    h, _ = attempt(security=1, password="abc")
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1)))
    assert h.accept_reply(stream.feed(RECEIVE_NOTIFICATION)[0], generation=7) is None
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    if change == "rejection":
        body = bytes.fromhex("28000020") + GUID + bytes(2) + bytes(246)
        raw = receive_frame(body, command=0x20000101)
    else:
        raw = receive_frame(
            reply(bytes(20) if change == "proof" else proof),
            command=0x10000105 if change == "wrong_command" else 0x10000101,
            sequence=41 if change == "wrong_sequence" else 42,
        )
    with pytest.raises(c.CodecError):
        h.accept_reply(stream.feed(raw)[0], generation=7)
    assert h.state == "terminal"
    with pytest.raises(c.CodecError):
        h.accept_reply(
            c.Packet(2563, 0, 0, 0, RECEIVE_NOTIFICATION[24:], peer_version=6),
            generation=7,
        )


def test_receive_negotiation_fragment_checks_and_input_bounds_still_apply():
    c = codec()
    g = c.parse_greeting(greeting())
    inner = RECEIVE_NOTIFICATION[8:]
    stream = c.N9000Stream(greeting=g)
    assert stream.feed(fragment(inner[:20], 1, 2, len(inner))) == ()
    with pytest.raises(c.CodecError):
        stream.feed(fragment(inner[20:], 1, 2, len(inner)))
    stream = c.N9000Stream(greeting=g, max_chunk_bytes=512)
    with pytest.raises(c.CodecError):
        stream.feed(bytes(513))
    stream = c.N9000Stream(greeting=g)
    raw = bytearray(RECEIVE_NOTIFICATION)
    before = bytes(raw)
    parsed = stream.feed(raw)[0]
    assert raw == before and parsed.body == before[24:]
    raw[-1] = 0
    assert parsed.body == before[24:]


# Header facts are root-supplied; the opaque92 body is entirely invented.
STARTUP_2561 = bytes.fromhex(
    "31313131 6c000000 06000000 010a0000 00000000 5c000000"
) + bytes(92)
# ml2.a: GUID16 followed by six LE int32 fields, with invented values1..6.
STARTUP_2562 = (
    bytes.fromhex("31313131 38000000 06000000 020a0000 00000000 28000000")
    + GUID
    + bytes.fromhex("01000000 02000000 03000000 04000000 05000000 06000000")
)


def test_startup_notifications_observed_124_bytes_opaque_discard_no_login_result():
    c = codec()
    h, outgoing = attempt(security=1, password="abc")
    assert len(outgoing.data) == 260 and outgoing.data[8:10] == bytes.fromhex("0300")
    raw = bytes.fromhex("3131313100000000") + STARTUP_2561
    assert len(raw) == 124
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1)))
    parsed = stream.feed(raw)
    assert len(parsed) == 1
    assert (
        parsed[0].peer_version,
        parsed[0].command,
        parsed[0].sequence,
        len(parsed[0].body),
    ) == (6, 2561, 0, 92)
    assert h.accept_reply(parsed[0], generation=7) is None
    assert h.state == "awaiting_reply"
    # Startup events cannot satisfy or alter the source credential proof.
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    result = h.accept_reply(
        stream.feed(receive_frame(reply(proof), peer_version=8))[0], generation=7
    )
    assert result.proof_verified and result.peer_version == 8
    assert not result.authorized and not result.serial_validated and not result.live


@pytest.mark.parametrize(
    "raw",
    [STARTUP_2561, STARTUP_2562, RECEIVE_NOTIFICATION],
    ids=["2561-opaque92", "2562-ml2-40", "2563-il2-36"],
)
def test_startup_notifications_whole_family_fragmented_and_every_split(raw):
    c = codec()
    g = c.parse_greeting(greeting())
    for split in range(1, len(raw)):
        stream = c.N9000Stream(greeting=g)
        assert stream.feed(raw[:split]) == ()
        parsed = stream.feed(raw[split:])
        h, _ = attempt()
        assert len(parsed) == 1
        assert h.accept_reply(parsed[0], generation=7) is None
        assert h.state == "awaiting_reply"
    inner = raw[8:]
    stream = c.N9000Stream(greeting=g)
    assert stream.feed(fragment(inner[:20], 1, 2, len(inner))) == ()
    parsed = stream.feed(fragment(inner[20:], 2, 2, len(inner)))
    h, _ = attempt()
    assert h.accept_reply(parsed[0], generation=7) is None
    assert h.state == "awaiting_reply"


def test_startup_notifications_coalesced_family_and_exact_reply_only_completes():
    c = codec()
    g = c.parse_greeting(greeting())
    stream = c.N9000Stream(greeting=g)
    parsed = stream.feed(
        STARTUP_2561
        + STARTUP_2562
        + RECEIVE_NOTIFICATION
        + receive_frame(reply(), peer_version=9)
    )
    assert [p.command for p in parsed] == [2561, 2562, 2563, 0x10000101]
    h, _ = attempt()
    for p in parsed[:-1]:
        assert h.accept_reply(p, generation=7) is None
        assert h.state == "awaiting_reply"
    result = h.accept_reply(parsed[-1], generation=7)
    assert result.peer_version == 9 and not result.authorized
    assert h.state == "terminal"


@pytest.mark.parametrize("command,size", [(2561, 92), (2562, 40), (2563, 36)])
@pytest.mark.parametrize(
    "change",
    ["short", "long", "sequence", "flags", "encoding", "reply_action", "error_action"],
)
def test_startup_notifications_exact_shape_not_any_default_or_error(
    command, size, change
):
    c = codec()
    body = bytes(size + (1 if change == "long" else -1 if change == "short" else 0))
    action = (
        0x10000000
        if change == "reply_action"
        else 0x20000000
        if change == "error_action"
        else 0
    )
    raw = receive_frame(
        body,
        command=command + action,
        sequence=1 if change == "sequence" else 0,
        flags=1 if change == "flags" else 0,
        encoding=1 if change == "encoding" else 0,
    )
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting()))
    with pytest.raises(c.CodecError):
        stream.feed(raw[:24])
    with pytest.raises(c.CodecError):
        stream.feed(raw[24:])


@pytest.mark.parametrize("command", [2560, 2564, 2565, 2331, 2819, 65537])
def test_startup_notifications_unknown_and_other_source_families_stay_unsupported(
    command,
):
    c = codec()
    with pytest.raises(c.UnsupportedBranch):
        c.N9000Stream(greeting=c.parse_greeting(greeting())).feed(
            receive_frame(bytes(92), command=command, sequence=0)
        )


@pytest.mark.parametrize("command,size", [(2561, 92), (2562, 40), (2563, 36)])
@pytest.mark.parametrize(
    "change", ["generation", "sequence", "short", "flags", "encoding"]
)
def test_startup_notifications_handshake_guard_is_terminal(command, size, change):
    c = codec()
    h, _ = attempt()
    p = c.Packet(
        command,
        1 if change == "sequence" else 0,
        1 if change == "flags" else 0,
        1 if change == "encoding" else 0,
        bytes(size - 1 if change == "short" else size),
        peer_version=6,
    )
    with pytest.raises(c.CodecError):
        h.accept_reply(p, generation=8 if change == "generation" else 7)
    assert h.state == "terminal"


@pytest.mark.parametrize("raw", [STARTUP_2561, STARTUP_2562, RECEIVE_NOTIFICATION])
def test_startup_notifications_unbound_still_rejects(raw):
    c = codec()
    with pytest.raises(c.CodecError):
        c.N9000Stream().feed(raw)


@pytest.mark.parametrize("change", ["sequence", "proof", "rejection"])
def test_startup_notifications_do_not_weaken_pending_login(change):
    c = codec()
    h, _ = attempt(security=1, password="abc")
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1)))
    for p in stream.feed(STARTUP_2561 + STARTUP_2562 + RECEIVE_NOTIFICATION):
        assert h.accept_reply(p, generation=7) is None
    if change == "rejection":
        raw = receive_frame(
            bytes.fromhex("28000020") + GUID + bytes(2) + bytes(246), command=0x20000101
        )
    else:
        proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
        raw = receive_frame(
            reply(bytes(20) if change == "proof" else proof),
            sequence=41 if change == "sequence" else 42,
        )
    with pytest.raises(c.CodecError):
        h.accept_reply(stream.feed(raw)[0], generation=7)
    assert h.state == "terminal"


@pytest.mark.parametrize("source_b", [0, 1, 7, 0x20000028, 0x80000000, 0xFFFFFFFF])
def test_reply_semantics_legacy_success_ignores_source_b_with_verified_proof(source_b):
    c = codec()
    h, _ = attempt(security=1, password="abc")
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    raw = receive_frame(reply(proof, source_b=source_b, tail=bytes(208)), encoding=1)
    p = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1))).feed(raw)[0]
    result = h.accept_reply(p, generation=7)
    assert result.proof_verified and result.key_extracted
    assert result.channel_tail == bytes(208)
    assert result.session_guid == bytes.fromhex("102030405060708090a0b0c0d0e0f000")
    assert result.peer_version == 6
    assert not result.authorized and not result.serial_validated and not result.live
    assert h.state == "terminal"


def test_reply_semantics_observed_372_byte_shape_synthetic_success_header():
    c = codec()
    h = c.LoginHandshake(
        generation=7,
        sequence=1,
        credentials=c.Credentials("uSer", "abc"),
        nonce_factory=lambda: "12345678",
    )
    g = c.parse_greeting(greeting(security=1))
    assert len(h.build_request(g).data) == 260
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    # Only header shape is observed. Integer/proof/key/tail are invented fixtures.
    raw = bytes.fromhex(
        "3131313100000000 313131316401000006000001010100100100000054010000"
    ) + reply(proof, source_b=0x11223344, tail=bytes(208))
    assert len(raw) == 372
    p = c.N9000Stream(greeting=g).feed(raw)[0]
    result = h.accept_reply(p, generation=7)
    assert result.proof_verified and len(result.channel_tail) == 208
    assert not result.authorized and not result.live


@pytest.mark.parametrize("source_b", [1, 0xFFFFFFFF])
def test_reply_semantics_newer_success_b_is_not_rejection_or_server_proof(source_b):
    c = codec()
    h, _ = attempt(version=11, security=1, password="abc", rsa_factory=rsa_pair)
    body = (
        GUID
        + source_b.to_bytes(4, "little")
        + bytes(32)
        + bytes(64)
        + CIPHERTEXT
        + bytes(48)
        + b"invented-tail"
    )
    p = c.N9000Stream(greeting=c.parse_greeting(greeting(version=11, security=1))).feed(
        receive_frame(body, command=0x10000105)
    )[0]
    result = h.accept_reply(p, generation=7)
    assert result.key_material == b"00112233445566778899AABBCCDDEEFF"
    assert not result.proof_verified and not result.authorized and not result.live
    assert result.channel_tail == b"invented-tail"


@pytest.mark.parametrize("version", [10, 11])
@pytest.mark.parametrize("error_code", [0, 0x20000028])
def test_reply_semantics_action2_uses_oz0_code_at_zero_and_is_terminal(
    version, error_code
):
    c = codec()
    kwargs = {"rsa_factory": rsa_pair} if version == 11 else {}
    h, _ = attempt(version=version, **kwargs)
    body = error_code.to_bytes(4, "little") + bytes(16) + bytes(2) + bytes(246)
    command = 0x20000101 if version == 10 else 0x20000105
    p = c.N9000Stream(greeting=c.parse_greeting(greeting(version=version))).feed(
        receive_frame(body, command=command)
    )[0]
    with pytest.raises(c.LoginRejected) as caught:
        h.accept_reply(p, generation=7)
    assert caught.value.code == error_code
    assert h.state == "terminal"


@pytest.mark.parametrize(
    "change",
    ["proof", "sequence", "generation", "short", "request_action", "wrong_command"],
)
def test_reply_semantics_nonzero_b_does_not_relax_other_login_guards(change):
    c = codec()
    h, _ = attempt(security=1, password="abc")
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    body = reply(bytes(20) if change == "proof" else proof, source_b=0xFFFFFFFF)
    if change == "short":
        body = body[:131]
    command = (
        257
        if change == "request_action"
        else 0x10000105
        if change == "wrong_command"
        else 0x10000101
    )
    p = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1))).feed(
        receive_frame(
            body, sequence=41 if change == "sequence" else 42, command=command
        )
    )[0]
    with pytest.raises(c.CodecError) as caught:
        h.accept_reply(p, generation=8 if change == "generation" else 7)
    assert type(caught.value) is c.CodecError
    assert h.state == "terminal"


def test_reply_semantics_fragmented_nonzero_b_success_preserves_shape_and_source_tail():
    c = codec()
    h, _ = attempt(security=1, password="abc")
    proof = bytes.fromhex("ee460743988dcd7e7bc2efcc29eb8aa842eabe49")
    inner = receive_frame(reply(proof, source_b=1, tail=bytes(208)))[8:]
    stream = c.N9000Stream(greeting=c.parse_greeting(greeting(security=1)))
    assert stream.feed(fragment(inner[:70], 1, 2, len(inner))) == ()
    p = stream.feed(fragment(inner[70:], 2, 2, len(inner)))[0]
    result = h.accept_reply(p, generation=7)
    assert result.proof_verified and result.channel_tail == bytes(208)
