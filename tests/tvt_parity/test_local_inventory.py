"""Pure invented-data channel/identity tests; never vendor/device acceptance."""

from __future__ import annotations

import dataclasses
import importlib
import pickle
import struct

import pytest
from wso_core.tvt.local_n9000 import CodecError, LoginResult, UnsupportedBranch

TAIL = bytes.fromhex(
    "01000000140002000002030067452301ab89efcd0123456789abcdef01ff080098badcfe54761032abcdef0123456789020000001000010020534146453030312000000000000000"
)
G1 = bytes.fromhex("67452301ab89efcd0123456789abcdef")
G2 = bytes.fromhex("98badcfe54761032abcdef0123456789")
ID1 = "01234567-89AB-CDEF-0123-456789ABCDEF"
ID2 = "FEDCBA98-7654-3210-ABCD-EF0123456789"
ORACLE_REQUESTS = {
    "basic-request.bin": bytes.fromhex(
        "3131313116010000030000011b090000110000000601000072656164657200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000717565727942617369634366670000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003c3f786d6c2076657273696f6e3d27312e302720656e636f64696e673d277574662d38273f3e3c726571756573742076657273696f6e3d27312e30272073797374656d547970653d274e564d532d393030302720636c69656e74547970653d274d4f42494c45272075726c3d2771756572794261736963436667273e3c2f726571756573743e"
    ),
    "channels-request.bin": bytes.fromhex(
        "31313131a4010000030000011b09000011000000940100007265616465720000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000071756572794e6f64654c6973740000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003c3f786d6c2076657273696f6e3d27312e302720656e636f64696e673d277574662d38273f3e3c726571756573742076657273696f6e3d27312e30272073797374656d547970653d274e564d532d393030302720636c69656e74547970653d274d4f42494c45272075726c3d2771756572794e6f64654c697374273e3c6e6f64655479706520747970653d226e6f646554797065223e63686c733c2f6e6f6465547970653e3c726571756972654669656c643e3c6e616d652f3e3c69702f3e3c63686c496e6465782f3e3c63686c547970652f3e3c77696e496e6465782f3e3c707265736574436f756e742f3e3c637275697365436f756e742f3e3c2f726571756972654669656c643e3c2f726571756573743e"
    ),
    "user-request.bin": bytes.fromhex(
        "3131313110010000030000011b090000110000000001000072656164657200000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000646f4c6f67696e0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003c3f786d6c2076657273696f6e3d27312e302720656e636f64696e673d277574662d38273f3e3c726571756573742076657273696f6e3d27312e30272073797374656d547970653d274e564d532d393030302720636c69656e74547970653d274d4f42494c45272075726c3d27646f4c6f67696e273e3c2f726571756573743e"
    ),
    "permissions-request.bin": bytes.fromhex(
        "3131313183010000030000011b09000011000000730100007265616465720000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000071756572794175746847726f757000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000003c3f786d6c2076657273696f6e3d27312e302720656e636f64696e673d277574662d38273f3e3c726571756573742076657273696f6e3d27312e30272073797374656d547970653d274e564d532d393030302720636c69656e74547970653d274d4f42494c45272075726c3d2771756572794175746847726f7570273e3c636f6e646974696f6e3e3c6175746847726f757049643e47524f5550313c2f6175746847726f757049643e3c2f636f6e646974696f6e3e3c726571756972654669656c643e3c63686c417574682f3e3c73797374656d417574682f3e3c2f726571756972654669656c643e3c2f726571756573743e"
    ),
}


def api():
    try:
        return importlib.import_module("wso_core.tvt.local_inventory")
    except ModuleNotFoundError:
        pytest.fail("Private inventory codec is missing")


def login(tail=TAIL, proof=True):
    return LoginResult(b"D" * 16, b"S" * 16, b"K" * 16, tail, bytes(20), proof, True)


def session(**values):
    defaults = {
        "login": login(),
        "generation": 7,
        "expected_serial": "SAFE001",
        "username": "reader",
        "security": 0,
        "peer_version": 6,
        "read_authority": lambda generation: generation == 7,
    }
    defaults.update(values)
    return api().InventorySession(**defaults)


def response(url, content, *, status="success"):
    return (
        f'<response url="{url}"><status>{status}</status>{content}</response>'.encode()
    )


def frame(body, sequence=17, command=0x1000091B, version=6):
    inner = struct.pack("<HBBIII", version, 0, 1, command, sequence, len(body)) + body
    return struct.pack("<II", 825307441, len(inner)) + inner


def accept(ctx, kind, body, sequence=17, generation=7):
    ctx.build_query(kind, sequence=sequence, generation=7)
    return ctx.accept_reply(frame(body, sequence=sequence), generation=generation)


def test_source_java_tail_oracle_and_signed_window_sort_public_positions():
    m = api()
    evidence = session().inventory
    assert evidence.serial_matched is True
    assert evidence.channels_complete is True
    assert [
        (c.guid, c.window_index, c.raw_index, c.position, c.name)
        for c in evidence.channels
    ] == [(G2, -1, 8, 1, None), (G1, 2, 3, 2, None)]
    assert evidence.authorized is False and evidence.live is False
    assert evidence.availability is m.Availability.IDENTITY_AVAILABLE


def test_serial_missing_is_unverified_and_mismatch_never_admitted():
    m = api()
    evidence = session(login=login(TAIL[:48])).inventory
    assert evidence.serial_matched is False
    assert evidence.availability is m.Availability.SERIAL_UNVERIFIED
    with pytest.raises(CodecError, match="serial mismatch") as caught:
        session(expected_serial="OTHER999")
    assert "OTHER999" not in str(caught.value)


@pytest.mark.parametrize(
    "tail",
    [
        TAIL[:3],
        TAIL[:-1],
        TAIL + b"x",
        struct.pack("<hhhh", 1, 0, 20, -1),
        struct.pack("<hhhh", 1, 0, 32767, 32767),
        TAIL + TAIL[48:],
        TAIL[:8] + TAIL[8:28] * 2 + TAIL[48:],
        TAIL[:48] + struct.pack("<hhhh", 2, 0, 1, 2) + b"AB",
        TAIL[:48] + struct.pack("<hhhh", 2, 0, 2, 1) + b"\xff\xff",
    ],
    ids=lambda value: "bytes-" + str(len(value)),
)
def test_tail_bounds_counts_duplicates_and_utf8_reject(tail):
    with pytest.raises(CodecError):
        session(login=login(tail))


@pytest.mark.parametrize(
    "tail",
    [
        TAIL + struct.pack("<hhhh", 77, 0, 1, 1) + b"x",
        bytes((99,)) + TAIL[1:],
        TAIL[:8] + bytes((99,)) + TAIL[9:],
        TAIL[:11] + b"\x01" + TAIL[12:],
    ],
)
def test_unknown_extension_channel_type_or_reserved_is_explicitly_unsupported(tail):
    m = api()
    evidence = session(login=login(tail)).inventory
    assert evidence.availability is m.Availability.UNSUPPORTED_TAIL
    assert evidence.channels_complete is False
    assert evidence.authorized is False


def test_private_records_are_immutable_redacted_not_dataclass_or_picklable():
    evidence = session().inventory
    for value in (evidence, *evidence.channels):
        assert "SAFE001" not in repr(value) and "01234567" not in repr(value)
        assert dataclasses.is_dataclass(value) is False
        with pytest.raises(TypeError):
            pickle.dumps(value)
        with pytest.raises(TypeError):
            dataclasses.asdict(value)
        with pytest.raises(AttributeError):
            value.extra = "supplier"


def test_source_java_exact_plain_read_query_serializers():
    m = api()
    for kind, filename in (
        (m.ReadQuery.BASIC, "basic-request.bin"),
        (m.ReadQuery.CHANNELS, "channels-request.bin"),
        (m.ReadQuery.USER, "user-request.bin"),
    ):
        assert (
            session().build_query(kind, sequence=17, generation=7).data
            == ORACLE_REQUESTS[filename]
        )
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId><userType>reader</userType></content>",
        ),
        sequence=16,
    )
    assert (
        ctx.build_query(m.ReadQuery.PERMISSIONS, sequence=17, generation=7).data
        == ORACLE_REQUESTS["permissions-request.bin"]
    )


def test_source_crypto_gap_is_typed_unsupported_not_guessed():
    for security in (1, 2):
        with pytest.raises(UnsupportedBranch) as caught:
            session(security=security).build_query(
                api().ReadQuery.BASIC, sequence=17, generation=7
            )
        assert caught.value.branch == "encrypted_xml"


def test_metadata_requires_external_current_actor_authority_not_parse_flags():
    m = api()
    for proof in (False, True):
        ctx = session(login=login(proof=proof), read_authority=lambda generation: False)
        with pytest.raises(CodecError):
            ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
        assert ctx.state == "terminal"


def test_supplier_authority_exception_never_enters_cause_context_or_message():
    def private_failure(generation):
        raise ValueError("SUPPLIER_PRIVATE_TEXT")

    ctx = session(read_authority=private_failure)
    with pytest.raises(CodecError) as caught:
        ctx.build_query(api().ReadQuery.BASIC, sequence=17, generation=7)
    assert "SUPPLIER_PRIVATE_TEXT" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


@pytest.mark.parametrize(
    "changes",
    [{"generation": 8}, {"sequence": 18}, {"command": 0x10000A03}, {"version": 7}],
)
def test_stale_sequence_generation_command_or_unnegotiated_version_is_terminal(changes):
    m = api()
    ctx = session()
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    generation = changes.pop("generation", 7)
    with pytest.raises(CodecError):
        ctx.accept_reply(
            frame(
                response("queryBasicCfg", "<content><sn>SAFE001</sn></content>"),
                **changes,
            ),
            generation=generation,
        )
    assert ctx.state == "terminal"


def test_basic_identity_reply_and_channel_names_are_guid_joined_no_authority():
    m = api()
    ctx = session(login=login(proof=False))
    evidence = accept(
        ctx,
        m.ReadQuery.BASIC,
        response(
            "queryBasicCfg", "<content><sn>SAFE001</sn><name>Recorder</name></content>"
        ),
    )
    assert evidence.serial_matched is True and evidence.proof_verified is False
    content = f'<content total="2"><item id="{{{ID1}}}"><name>Back</name><chlIndex>3</chlIndex><chlType>analog</chlType><winIndex>2</winIndex></item><item id="{{{ID2}}}"><name>Front</name><chlIndex>8</chlIndex><chlType>digital</chlType><winIndex>-1</winIndex></item></content>'
    evidence = accept(
        ctx, m.ReadQuery.CHANNELS, response("queryNodeList", content), sequence=18
    )
    assert [c.name for c in evidence.channels] == ["Front", "Back"]
    assert evidence.authorized is False and evidence.live is False
    with pytest.raises(CodecError):
        ctx.build_query(m.ReadQuery.BASIC, sequence=18, generation=7)


def test_permission_symbols_are_metadata_and_default_admin_does_not_bypass_missing_group():
    m = api()
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId><userType>default_admin</userType></content>",
        ),
    )
    content = f'<content id="GROUP1"><chlAuth><item id="{{{ID2}}}"><auth>@lp@ptz</auth></item></chlAuth><systemAuth><previewAndSnap>true</previewAndSnap></systemAuth></content>'
    evidence = accept(
        ctx, m.ReadQuery.PERMISSIONS, response("queryAuthGroup", content), sequence=18
    )
    assert evidence.permissions_complete is True
    assert evidence.permissions[0].guid == G2 and evidence.permissions[
        0
    ].symbols == frozenset(("lp", "ptz"))
    assert evidence.authorized is False and evidence.live is False
    another = session()
    accept(
        another,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><userType>default_admin</userType></content>",
        ),
    )
    with pytest.raises(UnsupportedBranch):
        another.build_query(m.ReadQuery.PERMISSIONS, sequence=18, generation=7)


@pytest.mark.parametrize(
    "body",
    [
        b"\xff",
        b"<!DOCTYPE x><response/>",
        b"<response>&supplier;</response>",
        response(
            "queryBasicCfg", "<content><sn>SAFE001</sn><sn>SAFE001</sn></content>"
        ),
        response("queryBasicCfg", "<content><sn>OTHER999</sn></content>"),
        b"<response><status>success</status><content>"
        + b"<x>" * 20
        + b"</x>" * 20
        + b"</content></response>",
        response("queryBasicCfg", "<content><sn>SAFE001</sn></content><content/>"),
    ],
    ids=lambda value: "bytes-" + str(len(value)),
)
def test_xml_entities_depth_duplicate_identity_content_and_encoding_reject(body):
    ctx = session()
    ctx.build_query(api().ReadQuery.BASIC, sequence=17, generation=7)
    with pytest.raises(CodecError) as caught:
        ctx.accept_reply(frame(body), generation=7)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert ctx.state == "terminal"


def test_foreign_channel_or_permission_guid_and_duplicate_items_reject():
    m = api()
    for content in (
        f'<content><item id="{{{ID1}}}"><name>Back</name></item><item id="{{{ID1}}}"><name>Again</name></item></content>',
        '<content total="1"><item id="{11111111-2222-3333-4444-555555555555}"><name>Foreign</name><chlIndex>3</chlIndex><chlType>analog</chlType><winIndex>2</winIndex></item></content>',
    ):
        with pytest.raises(CodecError):
            accept(session(), m.ReadQuery.CHANNELS, response("queryNodeList", content))
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>",
        ),
    )
    with pytest.raises(CodecError):
        accept(
            ctx,
            m.ReadQuery.PERMISSIONS,
            response(
                "queryAuthGroup",
                '<content id="GROUP1"><chlAuth><item id="{11111111-2222-3333-4444-555555555555}"><auth>@lp</auth></item></chlAuth></content>',
            ),
            sequence=18,
        )


def test_latest_blank_basic_serial_stays_explicitly_unverified():
    m = api()
    for content in (
        "<content><sn> </sn></content>",
        "<content><name>Recorder</name></content>",
    ):
        evidence = accept(
            session(), m.ReadQuery.BASIC, response("queryBasicCfg", content)
        )
        assert evidence.serial_matched is False
        assert evidence.availability is m.Availability.SERIAL_UNVERIFIED


def test_source_ignored_content_ids_and_count_attributes_do_not_grant():
    m = api()
    for query, content in (
        (m.ReadQuery.USER, '<content id="FOREIGN"><userId>USER1</userId></content>'),
        (m.ReadQuery.BASIC, f'<content id="{{{ID1}}}"><sn>SAFE001</sn></content>'),
    ):
        evidence = accept(session(), query, response(query.value, content))
        assert evidence.authorized is False and evidence.live is False
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>",
        ),
    )
    evidence = accept(
        ctx,
        m.ReadQuery.PERMISSIONS,
        response(
            "queryAuthGroup",
            '<content id="GROUP1"><chlAuth count="2"/><systemAuth/></content>',
        ),
        sequence=18,
    )
    assert evidence.permissions == () and evidence.authorized is False


def test_generation_and_system_permission_metadata_remain_private_not_grants():
    m = api()
    ctx = session()
    user = accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId><systemAuth><net>false</net></systemAuth></content>",
        ),
    )
    assert user.generation == 7
    assert user.user.system_auth == (("net", False),)
    evidence = accept(
        ctx,
        m.ReadQuery.PERMISSIONS,
        response(
            "queryAuthGroup",
            '<content id="GROUP1"><chlAuth/><systemAuth><previewAndSnap>false</previewAndSnap></systemAuth></content>',
        ),
        sequence=18,
    )
    assert evidence.permission_system == (("previewAndSnap", False),)
    assert evidence.permissions_complete is True and evidence.authorized is False


def test_generation_guard_alone_rejects_stale_reply_even_with_current_actor_scope():
    ctx = session(read_authority=lambda generation: True)
    ctx.build_query(api().ReadQuery.BASIC, sequence=17, generation=7)
    with pytest.raises(CodecError):
        ctx.accept_reply(
            frame(response("queryBasicCfg", "<content><sn>SAFE001</sn></content>")),
            generation=8,
        )
    assert ctx.state == "terminal"


def test_private_record_constructors_reject_mutable_payloads():
    m = api()
    for construct in (
        lambda: m.ChannelRecord(bytearray(G1), "analog", 2, 3, 1),
        lambda: m.PermissionMetadata(G1, {"lp"}),
        lambda: m.UserMetadata("USER1", "GROUP1", None, False, [("net", False)]),
        lambda: m.InventoryEvidence(
            "SAFE001", True, [], True, True, True, True, generation=7
        ),
    ):
        with pytest.raises(CodecError):
            construct()


def test_xml_fragmentation_is_explicitly_unsupported_and_failure_code_is_safe():
    m = api()
    ctx = session()
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    with pytest.raises(UnsupportedBranch) as caught:
        ctx.accept_reply(
            struct.pack("<II", 825307441, 0xFFFFFFFF) + bytes(24), generation=7
        )
    assert caught.value.branch == "metadata_fragmentation"
    ctx = session()
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    rejection = bytearray(268)
    struct.pack_into("<I", rejection, 0, 536870947)
    struct.pack_into("<H", rejection, 20, 8)
    rejection[22:30] = b"PRIVATE!"
    with pytest.raises(m.InventoryRejected) as caught:
        ctx.accept_reply(frame(bytes(rejection), command=0x2000091B), generation=7)
    assert caught.value.code == 536870947 and "PRIVATE" not in str(caught.value)


def test_current_authority_revocation_pending_query_and_policy_bounds():
    m = api()
    current = [True]
    ctx = session(read_authority=lambda generation: current[0])
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    current[0] = False
    with pytest.raises(CodecError):
        ctx.accept_reply(
            frame(response("queryBasicCfg", "<content><sn>SAFE001</sn></content>")),
            generation=7,
        )
    assert ctx.state == "terminal"
    with pytest.raises(CodecError):
        session(limits=m.InventoryLimits(max_channels=1))
    ctx = session(limits=m.InventoryLimits(max_queries=1))
    accept(
        ctx,
        m.ReadQuery.BASIC,
        response("queryBasicCfg", "<content><sn>SAFE001</sn></content>"),
    )
    with pytest.raises(CodecError):
        ctx.build_query(m.ReadQuery.USER, sequence=18, generation=7)
    ctx = session()
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    with pytest.raises(CodecError):
        ctx.build_query(m.ReadQuery.USER, sequence=18, generation=7)


def test_missing_serial_cannot_read_permissions_and_partial_system_remains_incomplete():
    m = api()
    with pytest.raises(CodecError):
        session(login=login(TAIL[:48])).build_query(
            m.ReadQuery.USER, sequence=17, generation=7
        )
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>",
        ),
    )
    evidence = accept(
        ctx,
        m.ReadQuery.PERMISSIONS,
        response("queryAuthGroup", '<content id="GROUP1"><chlAuth/></content>'),
        sequence=18,
    )
    assert evidence.permissions_complete is False and evidence.authorized is False


def test_text_node_and_packet_bounds_and_unknown_permission_token_fail_closed():
    m = api()
    for ctx, body in (
        (
            session(limits=m.InventoryLimits(max_text_bytes=4)),
            response("queryBasicCfg", "<content><sn>SAFE001</sn></content>"),
        ),
        (
            session(limits=m.InventoryLimits(max_xml_nodes=3)),
            response("queryBasicCfg", "<content><sn>SAFE001</sn></content>"),
        ),
        (
            session(limits=m.InventoryLimits(max_xml_bytes=32)),
            response("queryBasicCfg", "<content><sn>SAFE001</sn></content>"),
        ),
    ):
        with pytest.raises(CodecError):
            accept(ctx, m.ReadQuery.BASIC, body)
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        response(
            "doLogin",
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>",
        ),
    )
    with pytest.raises(UnsupportedBranch):
        accept(
            ctx,
            m.ReadQuery.PERMISSIONS,
            response(
                "queryAuthGroup",
                f'<content id="GROUP1"><chlAuth><item id="{{{ID1}}}"><auth>@lpx</auth></item></chlAuth><systemAuth/></content>',
            ),
            sequence=18,
        )


@pytest.mark.parametrize("failure", ["revoked", "throws", "closed"])
def test_fix1_post_parse_authority_fence_keeps_previous_inventory(monkeypatch, failure):
    m = api()
    current = [True]
    supplier_throw = [False]
    calls = []

    def authority(generation):
        calls.append(generation)
        if supplier_throw[0]:
            raise ValueError("PRIVATE_POST_GUARD_SUPPLIER")
        return current[0]

    ctx = session(read_authority=authority)
    prior = ctx.inventory
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    original_xml = m._xml

    def parse_then_revoke(raw, limits):
        element = original_xml(raw, limits)
        if failure == "revoked":
            current[0] = False
        elif failure == "throws":
            supplier_throw[0] = True
        else:
            ctx.close()
        return element

    monkeypatch.setattr(m, "_xml", parse_then_revoke)
    with pytest.raises(CodecError) as caught:
        ctx.accept_reply(
            frame(
                response(
                    "queryBasicCfg",
                    "<content><sn>SAFE001</sn><name>Changed</name></content>",
                )
            ),
            generation=7,
        )
    assert ctx.state == "terminal"
    assert ctx.inventory is prior
    assert ctx.inventory.authorized is False and ctx.inventory.live is False
    assert "PRIVATE_POST_GUARD_SUPPLIER" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    if failure != "closed":
        assert calls == [7, 7, 7]


def test_fix1_success_rechecks_scope_and_basic_child_id_is_discarded():
    m = api()
    calls = []

    def authority(generation):
        calls.append(generation)
        return True

    ctx = session(read_authority=authority)
    evidence = accept(
        ctx,
        m.ReadQuery.BASIC,
        response(
            "queryBasicCfg",
            "<content><id>UNMAPPED_PRIVATE_CHILD</id><sn>SAFE001</sn></content>",
        ),
    )
    assert calls == [7, 7, 7]
    assert evidence.serial_matched is True and evidence.authorized is False
    assert not hasattr(evidence, "basic_child_id")
    assert ctx.state == "ready"


def auxiliary_fixture(serial_aux=1, channel_aux=1):
    # Only root's structural shape is reused; all serial/GUID bytes are invented.
    serial = b"INERT001" + bytes(24)
    records = b"".join(
        bytes((0, index, index, 0, index + 1))
        + bytes.fromhex("112233445566778899aabbccddeeff")
        for index in range(8)
    )
    return (
        struct.pack("<hhhh", 2, serial_aux, 32, 1)
        + serial
        + struct.pack("<hhhh", 1, channel_aux, 20, 8)
        + records
    )


@pytest.mark.parametrize("serial_aux", [0, 1, -32768, 32767])
@pytest.mark.parametrize("channel_aux", [0, 1, -32768, 32767])
def test_aux_fix2_opaque_signed_auxiliary_preserves_known_inventory(
    serial_aux, channel_aux
):
    m = api()
    raw = auxiliary_fixture(serial_aux, channel_aux)
    assert len(raw) == 208
    evidence = session(
        login=login(raw, proof=False), expected_serial="INERT001"
    ).inventory
    assert evidence.availability is m.Availability.IDENTITY_AVAILABLE
    assert evidence.serial_matched is True and evidence.channels_complete is True
    assert evidence.proof_verified is False and evidence.key_extracted is True
    assert len(evidence.channels) == 8
    assert [
        (c.kind, c.window_index, c.raw_index, c.position, c.name)
        for c in evidence.channels
    ] == [("analog", index, index, index + 1, None) for index in range(8)]
    assert [c.guid for c in evidence.channels] == [
        bytes((index + 1,)) + bytes.fromhex("112233445566778899aabbccddeeff")
        for index in range(8)
    ]
    assert evidence.authorized is False and evidence.live is False
    assert evidence.permissions_complete is False


@pytest.mark.parametrize(
    "variant",
    ["wrong_serial", "duplicate_guid", "truncated", "negative_count", "count_bound"],
)
def test_aux_fix2_ignored_auxiliary_does_not_relax_real_constraints(variant):
    m = api()
    raw = auxiliary_fixture()
    if variant == "wrong_serial":
        raw = raw.replace(b"INERT001", b"OTHER999")
    elif variant == "duplicate_guid":
        raw = raw[:72] + raw[52:68] + raw[88:]
    elif variant == "truncated":
        raw = raw[:-1]
    elif variant == "negative_count":
        raw = raw[:46] + struct.pack("<h", -1) + raw[48:]
    else:
        with pytest.raises(CodecError):
            session(
                login=login(raw),
                expected_serial="INERT001",
                limits=m.InventoryLimits(max_channels=7),
            )
        return
    with pytest.raises(CodecError):
        session(login=login(raw), expected_serial="INERT001")


@pytest.mark.parametrize(
    "variant", ["unknown_kind", "unknown_width", "reserved", "channel_type"]
)
def test_aux_fix2_no_unknown_shape_skip_or_status_guess(variant):
    m = api()
    raw = auxiliary_fixture()
    if variant == "unknown_kind":
        raw += struct.pack("<hhhh", 77, 1, 1, 1) + b"x"
    elif variant == "unknown_width":
        raw = raw[:44] + struct.pack("<h", 19) + raw[46:48] + raw[48:-8]
    elif variant == "reserved":
        raw = raw[:51] + b"\x01" + raw[52:]
    else:
        raw = raw[:48] + b"\x63" + raw[49:]
    evidence = session(login=login(raw), expected_serial="INERT001").inventory
    assert evidence.availability is m.Availability.UNSUPPORTED_TAIL
    assert evidence.channels_complete is False and evidence.channels == ()
    assert evidence.authorized is False and evidence.live is False


def source_xml_reply(
    content,
    *,
    status="success",
    attributes='clientType="MOBILE" cmdId="opaque" cmdUrl="opaque"',
    prefix=True,
    catalog=True,
):
    types = (
        '<types><languageType><enum value="inert">English</enum></languageType><catalogExtra><item kind="inert"/></catalogExtra></types>'
        if catalog
        else ""
    )
    xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><response {attributes}><status>{status}</status>{types}{content}</response>'
    ).encode()
    opaque = bytes((0, 255, 1, 2)) * 29 if prefix else b""
    return opaque + xml


def test_xml_fix3_source_shaped_successes_all_four_consumers():
    m = api()
    ctx = session(login=login(proof=False))
    basic = source_xml_reply(
        "<content><sn>SAFE001</sn><name>Inert &amp; recorder</name><devType>opaque-unused</devType><deviceNumber>unused</deviceNumber><productModel>inert</productModel><softwareVersion>inert</softwareVersion><hardwareVersion>inert</hardwareVersion><languageType>unused</languageType><additionalCfg><item/></additionalCfg></content>"
    )
    assert basic.find(b"<?xml") == 116
    evidence = accept(ctx, m.ReadQuery.BASIC, basic, sequence=17)
    assert evidence.serial_matched and not evidence.proof_verified
    # D8 reads item IDs/known fields; content@id and unconsumed counts/fields are not joins.
    channel = source_xml_reply(
        f'<content><item id="{{{ID1}}}" supplierAttr="ignored"><name>Back &amp; side</name><ignoredCfg><item/></ignoredCfg></item><item id="{{{ID2}}}"><name>Front &#x2603;</name></item><itemType type="catalog"/></content>'
    )
    evidence = accept(ctx, m.ReadQuery.CHANNELS, channel, sequence=18)
    assert [c.name for c in evidence.channels] == ["Front ☃", "Back & side"]
    user = source_xml_reply(
        '<content supplierAttr="ignored"><userId>USER1</userId><authGroupId>GROUP1</authGroupId><adminName>A &amp; B</adminName><systemAuth><net>false</net><unusedCfg><child/></unusedCfg></systemAuth><unknownMeta><item/></unknownMeta></content>'
    )
    evidence = accept(ctx, m.ReadQuery.USER, user, sequence=19)
    assert (
        evidence.user.auth_group_id == "GROUP1" and evidence.user.admin_name == "A & B"
    )
    permission = source_xml_reply(
        f'<content><group><chlAuth><item id="{{{ID2}}}" extra="ignored"><auth>@lp</auth><other/></item><itemType/></chlAuth><systemAuth><previewAndSnap>false</previewAndSnap><unknownMeta/></systemAuth></group><unknown/></content>'
    )
    evidence = accept(ctx, m.ReadQuery.PERMISSIONS, permission, sequence=20)
    assert evidence.permissions_complete is True
    assert evidence.permissions[0].guid == G2 and evidence.permissions[
        0
    ].symbols == frozenset(("lp",))
    assert evidence.permission_system == (("previewAndSnap", False),)
    assert evidence.authorized is False and evidence.live is False


def test_xml_fix3_opaque_attributes_do_not_invent_device_user_or_group_joins():
    m = api()
    ctx = session()
    evidence = accept(
        ctx,
        m.ReadQuery.BASIC,
        source_xml_reply(
            '<content id="NOT_A_DEVICE_GUID"><id>ignored</id><sn>SAFE001</sn></content>'
        ),
    )
    assert evidence.serial_matched is True
    evidence = accept(
        ctx,
        m.ReadQuery.USER,
        source_xml_reply(
            '<content id="NOT_USER1"><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>'
        ),
        sequence=18,
    )
    assert evidence.user.user_id == "USER1"
    evidence = accept(
        ctx,
        m.ReadQuery.PERMISSIONS,
        source_xml_reply('<content id="NOT_GROUP1"><chlAuth/><systemAuth/></content>'),
        sequence=19,
    )
    assert evidence.permissions_complete is True and evidence.authorized is False


@pytest.mark.parametrize(
    "body",
    [
        b'<?xml version="1.0"?><!DOCTYPE response SYSTEM "file:///never-read"><response><status>success</status><content/></response>',
        b'<?xml version="1.0"?><!DOCTYPE response [<!ENTITY x "bad">]><response><status>success</status><content><sn>&x;</sn></content></response>',
        b'<?xml version="1.0"?><response><status>success</status><content><sn>&unknown;</sn></content></response>',
        source_xml_reply("<content><sn>SAFE001</sn><sn>SAFE001</sn></content>"),
        source_xml_reply("<content><sn>OTHER999</sn></content>"),
        source_xml_reply("<content><sn>\ufffd</sn></content>"),
    ],
    ids=lambda value: "bytes-" + str(len(value)),
)
def test_xml_fix3_dtd_custom_entities_and_real_identity_guards_reject(body):
    ctx = session()
    ctx.build_query(api().ReadQuery.BASIC, sequence=17, generation=7)
    prior = ctx.inventory
    with pytest.raises(CodecError) as caught:
        ctx.accept_reply(frame(body), generation=7)
    assert ctx.state == "terminal" and ctx.inventory is prior
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_xml_fix3_prefix_rule_is_first_declaration_not_fixed_offset():
    m = api()
    for prefix in (b"", bytes(7), b"opaque\xff" * 23):
        body = (
            prefix
            + b'<?xml version="1.0"?><response><status>success</status><content><sn>SAFE001</sn></content></response>'
            + bytes(3)
        )
        assert accept(session(), m.ReadQuery.BASIC, body).serial_matched is True
    with pytest.raises(CodecError):
        accept(
            session(),
            m.ReadQuery.BASIC,
            b"no declaration prefix<response><status>success</status><content><sn>SAFE001</sn></content></response>",
        )


def test_xml_fix3_source_failure_and_missing_user_metadata_stay_unavailable():
    m = api()
    with pytest.raises(m.InventoryRejected) as caught:
        accept(
            session(),
            m.ReadQuery.BASIC,
            source_xml_reply("<errorCode>536870947</errorCode>", status="fail"),
        )
    assert caught.value.code == 536870947
    ctx = session()
    evidence = accept(
        ctx, m.ReadQuery.USER, source_xml_reply("<content><ignored/></content>")
    )
    assert evidence.user is None and evidence.permissions_complete is False
    with pytest.raises(UnsupportedBranch):
        ctx.build_query(m.ReadQuery.PERMISSIONS, sequence=18, generation=7)


@pytest.mark.parametrize(
    "changes", [{"sequence": 18}, {"command": 0x10000A03}, {"generation": 8}]
)
def test_xml_fix3_wrong_wire_query_or_generation_stays_terminal(changes):
    ctx = session(read_authority=lambda generation: True)
    ctx.build_query(api().ReadQuery.BASIC, sequence=17, generation=7)
    generation = changes.get("generation", 7)
    fields = {name: value for name, value in changes.items() if name != "generation"}
    with pytest.raises(CodecError):
        ctx.accept_reply(
            frame(source_xml_reply("<content><sn>SAFE001</sn></content>"), **fields),
            generation=generation,
        )
    assert ctx.state == "terminal"


def test_xml_fix3_foreign_channel_and_permission_items_still_reject():
    m = api()
    foreign = "11111111-2222-3333-4444-555555555555"
    with pytest.raises(CodecError):
        accept(
            session(),
            m.ReadQuery.CHANNELS,
            source_xml_reply(
                f'<content><item id="{{{foreign}}}"><name>inert</name></item></content>'
            ),
        )
    ctx = session()
    accept(
        ctx,
        m.ReadQuery.USER,
        source_xml_reply(
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>"
        ),
    )
    with pytest.raises(CodecError):
        accept(
            ctx,
            m.ReadQuery.PERMISSIONS,
            source_xml_reply(
                f'<content><chlAuth><item id="{{{foreign}}}"><auth>@lp</auth></item></chlAuth><systemAuth/></content>'
            ),
            sequence=18,
        )


def test_xml_fix3_partial_channel_fields_and_catalog_counts_are_not_invented_ids():
    m = api()
    ctx = session()
    result = accept(
        ctx,
        m.ReadQuery.CHANNELS,
        source_xml_reply(
            f'<content id="opaque" total="catalog" count="opaque"><item id="{{{ID1}}}"><name><![CDATA[Back & side]]></name><presetCount>ignored</presetCount></item><itemType/></content>'
        ),
    )
    assert len(result.channels) == 2 and result.channels_complete
    assert result.channels[0].guid == G2 and result.channels[0].name is None
    assert result.channels[1].guid == G1 and result.channels[1].name == "Back & side"
    missing = session(login=login(TAIL[48:]))
    with pytest.raises(CodecError):
        accept(
            missing,
            m.ReadQuery.CHANNELS,
            source_xml_reply(
                f'<content><item id="{{{ID1}}}"><name>inert</name></item></content>'
            ),
        )


def test_xml_fix3_decoded_text_and_structure_bounds_still_apply():
    m = api()
    for limits, content in (
        (m.InventoryLimits(max_text_bytes=4), "<content><sn>SAFE001</sn></content>"),
        (m.InventoryLimits(max_xml_nodes=4), "<content><sn>SAFE001</sn></content>"),
        (m.InventoryLimits(max_xml_bytes=100), "<content><sn>SAFE001</sn></content>"),
    ):
        with pytest.raises(CodecError):
            accept(session(limits=limits), m.ReadQuery.BASIC, source_xml_reply(content))


def test_xml_fix3_source_shaped_revocation_before_publication(monkeypatch):
    m = api()
    current = [True]
    ctx = session(read_authority=lambda generation: current[0])
    ctx.build_query(m.ReadQuery.BASIC, sequence=17, generation=7)
    previous = ctx.inventory
    parse = m._xml

    def parsed_then_revoked(raw, limits):
        element = parse(raw, limits)
        current[0] = False
        return element

    monkeypatch.setattr(m, "_xml", parsed_then_revoked)
    with pytest.raises(CodecError):
        ctx.accept_reply(
            frame(source_xml_reply("<content><sn>SAFE001</sn></content>")), generation=7
        )
    assert ctx.state == "terminal" and ctx.inventory is previous


@pytest.mark.parametrize(
    "content,expected_count",
    [
        ("<content><itemType/></content>", 0),
        (
            f'<content><item id="{{{ID1}}}"><name>Partial</name><chlType>analog</chlType><winIndex>2</winIndex><chlIndex>3</chlIndex></item></content>',
            1,
        ),
    ],
)
def test_xml_fix3_fix1_detail_only_never_proves_missing_roster(content, expected_count):
    m = api()
    ctx = session(login=login(TAIL[48:]))
    assert ctx.inventory.serial_matched and not ctx.inventory.channels_complete
    evidence = accept(ctx, m.ReadQuery.CHANNELS, source_xml_reply(content))
    assert len(evidence.channels) == expected_count
    assert evidence.channels_complete is False
    assert evidence.availability is m.Availability.CHANNELS_UNAVAILABLE
    accept(
        ctx,
        m.ReadQuery.USER,
        source_xml_reply(
            "<content><userId>USER1</userId><authGroupId>GROUP1</authGroupId></content>"
        ),
        sequence=18,
    )
    with pytest.raises(UnsupportedBranch) as caught:
        ctx.build_query(m.ReadQuery.PERMISSIONS, sequence=19, generation=7)
    assert caught.value.branch == "permission_channels_missing"
    assert evidence.authorized is False and evidence.live is False


def test_xml_fix3_fix1_known_roster_survives_partial_detail_update():
    m = api()
    ctx = session()
    evidence = accept(
        ctx,
        m.ReadQuery.CHANNELS,
        source_xml_reply(
            f'<content total="ignored"><item id="{{{ID1}}}"><name>Updated</name></item><itemType/></content>'
        ),
    )
    assert evidence.channels_complete is True and len(evidence.channels) == 2
    assert [
        (c.guid, c.window_index, c.raw_index, c.position, c.name)
        for c in evidence.channels
    ] == [(G2, -1, 8, 1, None), (G1, 2, 3, 2, "Updated")]
    assert evidence.authorized is False and evidence.live is False
