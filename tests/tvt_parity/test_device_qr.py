"""Invented SN_USER fixtures; never use actual device or credential records."""

import importlib
import importlib.util
import traceback

import pytest


def api():
    name = "wso_core.tvt.device_qr"
    assert importlib.util.find_spec(name) is not None, "SN_USER parser missing"
    return importlib.import_module(name)


@pytest.mark.parametrize(
    "payload,serial,username",
    [
        ("<sn>DEMO00000001</sn><user>alpha</user>", "DEMO00000001", "alpha"),
        (b"<sn>DEMO00000002</sn><user>bravo</user>", "DEMO00000002", "bravo"),
    ],
)
def test_invented_stores_parse_exact_identity_without_connection(
    payload, serial, username
):
    assert len(payload) == 39
    result = api().parse_device_info_qr(payload)
    assert result.serial == serial
    assert result.username == username
    assert result.status == "not_connected"


def test_source_serial_acceptance_is_separate_from_connect_by_token_dispatch():
    module = api()
    result = module.parse_device_info_qr("<sn>" + "A" * 33 + "</sn><user>demo</user>")
    assert result.serial == "A" * 33
    with pytest.raises(module.DeviceInfoQrError):
        module.validate_connect_by_token_device_info(result)


@pytest.mark.parametrize("serial", ["A", "z9", "A" * 31, "A" * 32, "A" * 128])
def test_source_serial_classifier_accepts_exact_ascii_range(serial):
    assert (
        api().parse_device_info_qr(f"<sn>{serial}</sn><user>demo</user>").serial
        == serial
    )


@pytest.mark.parametrize(
    "username", ["  demo  ", "관리자", "é", "e\u0301", "a&b", "&amp;", "\tuser\n"]
)
def test_source_username_is_literal_without_normalization_or_xml_expansion(username):
    result = api().parse_device_info_qr(f"<sn>DEMO1</sn><user>{username}</user>")
    assert result.username == username


@pytest.mark.parametrize(
    "serial", ["", "A" * 129, "é", "Ａ", "a_b", "a-b", "host:80", "https://demo", "A\n"]
)
def test_serial_never_becomes_address_or_unicode_classifier(serial):
    with pytest.raises(api().DeviceInfoQrError):
        api().parse_device_info_qr(f"<sn>{serial}</sn><user>demo</user>")


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "DEMO1",
        "https://example.invalid/device",
        "<sn>DEMO1</sn>",
        "<sn>DEMO1</sn><user></user>",
        "<user>demo</user><sn>DEMO1</sn>",
        "<SN>DEMO1</SN><user>demo</user>",
        " <sn>DEMO1</sn><user>demo</user>",
        "<sn>DEMO1</sn><user>demo</user>\n",
        "<sn>DEMO1</sn><user>demo</user>x",
        "<sn>DEMO1</sn><sn>DEMO2</sn><user>demo</user>",
        "<sn>DEMO1</sn><user>demo</user><user>other</user>",
        "<sn>DEMO1</sn><user>demo</user><pw>demo</pw>",
        "<sn>DEMO1</sn><user>demo</user><ip>127.0.0.1</ip>",
        "<sn>DEMO1</sn><user>demo</usr>",
        "<sn>DEMO1</sn><user>demo",
        "<sn>DEMO1</sn><user><user>demo</user></user>",
        "<sn>DEMO1</sn><user><![CDATA[demo]]></user>",
        '<!DOCTYPE x [<!ENTITY user SYSTEM "file:///demo">]><sn>DEMO1</sn><user>&user;</user>',
        "<?xml version='1.0'?><sn>DEMO1</sn><user>demo</user>",
        "<sn>DEMO1\0</sn><user>demo</user>",
        "<sn>DEMO1</sn><user>de\0mo</user>",
        "<sn>DEMO1</sn><user>\ud800</user>",
        "<sn>DEMO1</sn><user>\udfff</user>",  # noqa: PT014 -- distinct low surrogate
        b"<sn>DEMO1</sn><user>\xff</user>",
        b"\xef\xbb\xbf<sn>DEMO1</sn><user>demo</user>",
        None,
        42,
        bytearray(b"<sn>DEMO1</sn><user>demo</user>"),
        {"v": "QR10", "data": "ZGVtbw=="},
    ],
)
def test_invalid_payloads_are_rejected_with_private_fixed_error(payload):
    module = api()
    with pytest.raises(module.DeviceInfoQrError) as caught:
        module.parse_device_info_qr(payload)
    assert "DEMO1" not in str(caught.value)
    assert "demo" not in repr(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert "\\xff" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize(
    "payload",
    ['{"v":"QR10","data":"ZGVtbw==","eyp":0,"crc":0,"scrlen":4}', b'{"v":"QR10"}'],
)
def test_qr10_is_distinctly_unsupported(payload):
    module = api()
    with pytest.raises(module.UnsupportedDeviceQr):
        module.parse_device_info_qr(payload)


def test_payload_cap_counts_utf8_bytes_and_accepts_exact_cap():
    module = api()
    # 1-byte SN + 22-byte literal framing = 23; 4073 username bytes fill 4096.
    exact = "<sn>A</sn><user>" + "x" * 4073 + "</user>"
    assert len(exact.encode()) == 4096
    assert len(module.parse_device_info_qr(exact).username) == 4073
    with pytest.raises(module.DeviceInfoQrError):
        module.parse_device_info_qr(exact.replace("</user>", "x</user>"))
    with pytest.raises(module.DeviceInfoQrError):
        module.parse_device_info_qr("<sn>A</sn><user>" + "한" * 1400 + "</user>")


def test_connect_by_token_validation_preserves_values_and_remains_not_connected():
    module = api()
    parsed = module.parse_device_info_qr("<sn>" + "A" * 32 + "</sn><user>관리자</user>")
    assert module.validate_connect_by_token_device_info(parsed) is parsed
    assert parsed.status == "not_connected"


def test_private_result_never_represents_serial_username_or_raw_payload():
    module = api()
    parsed = module.parse_device_info_qr(
        "<sn>DEMOPRIVATE1</sn><user>privateDemoUser</user>"
    )
    assert "DEMOPRIVATE1" not in repr(parsed)
    assert "privateDemoUser" not in str(parsed)
    assert "<sn>" not in repr(parsed)
    assert not hasattr(parsed, "password")
    assert not hasattr(parsed, "token")
    assert not hasattr(parsed, "authority")
    assert not hasattr(parsed, "raw_payload")
    with pytest.raises(AttributeError):
        parsed.serial = "DEMOOTHER"


def test_connect_by_token_dispatch_rejects_forged_private_input_privately():
    module = api()
    for value in [None, {"serial": "DEMO1", "username": "demo"}]:
        with pytest.raises(module.DeviceInfoQrError):
            module.validate_connect_by_token_device_info(value)
    with pytest.raises(module.DeviceInfoQrError):
        module.DeviceInfoQr("https://demo", "privateDemoUser")
