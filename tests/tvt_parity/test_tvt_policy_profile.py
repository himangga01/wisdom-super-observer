"""Policy derivation and deployment profile boundaries; no provider execution."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from wso_core.tvt.startup import StartupProfile, load_profile, menu

ROOT = Path(__file__).resolve().parents[2]


def module(path):
    source = ROOT / path
    assert source.is_file(), f"Missing W03 implementation: {path}"
    spec = importlib.util.spec_from_file_location(source.stem, source)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def policies():
    return json.loads(
        (ROOT / "apps/web/src/features/tvt/policies/generated-content.json").read_text(
            encoding="utf-8"
        )
    )


def test_parser_keeps_readable_structure_and_discards_active_or_hidden_content():
    generator = module("scripts/generate_tvt_policy_content.py")
    result = generator.extract_blocks(
        "<html><head><title>Head only</title></head><body>"
        '<h2 onclick="attack()">Heading &amp; title</h2>'
        "<p>Visible <b>words</b><br>next line "
        '<a href="javascript:attack()">link text</a></p>'
        "<ol><li>First<ul><li>Nested</li></ul></li><li>Second</li></ol>"
        "<table><tr><td>Company</td><td><p>Purpose</p></td></tr></table>"
        "<script>attack()</script><style>css-secret</style>"
        '<iframe>frame-secret</iframe><img src="https://remote.test/tracker">'
        '<p hidden>hidden-secret</p><p style="display:none">css-hidden-secret</p>'
        "</body></html>"
    )
    assert result[0] == {"type": "heading", "level": 2, "text": "Heading & title"}
    assert result[1]["text"] == "Visible words\nnext line link text"
    assert result[2]["ordered"] is True
    assert result[2]["items"][0][1]["items"][0][0]["text"] == "Nested"
    assert result[3]["rows"][0][1][0]["text"] == "Purpose"
    flattened = json.dumps(result)
    for forbidden in (
        "Head only",
        "attack",
        "secret",
        "remote.test",
        "href",
        "onclick",
    ):
        assert forbidden not in flattened


def test_source_list_paragraphs_outside_li_are_preserved_in_order():
    generator = module("scripts/generate_tvt_policy_content.py")
    blocks = generator.extract_blocks(
        "<body><ul><li>Request methods</li><p>Required written request</p>"
        "<p>Other supported channels</p><li>Validity</li><p>Verify identity</p>"
        "</ul></body>"
    )
    assert blocks == [
        {
            "type": "list",
            "ordered": False,
            "items": [
                [
                    {"type": "paragraph", "text": "Request methods"},
                    {"type": "paragraph", "text": "Required written request"},
                    {"type": "paragraph", "text": "Other supported channels"},
                ],
                [
                    {"type": "paragraph", "text": "Validity"},
                    {"type": "paragraph", "text": "Verify identity"},
                ],
            ],
        }
    ]


def test_bundled_documents_retain_original_text_sources_and_independent_digests():
    source = ROOT / "apps/web/src/features/tvt/policies/generated-content.json"
    assert source.is_file(), "Missing safe bundled policies"
    bundle = policies()
    expected = {
        ("en", "terms"): (
            "ServiceTerms_en.html",
            "7973f409b90d62127488bf496de299dc537c32832b1c27b9d37f020ce2525544",
            158863,
            "Release/Effective Date: July 28, 2021",
        ),
        ("zh-Hans", "terms"): (
            "ServiceTerms_zh-Hans.html",
            "9580039561c539e348a2a45f6682b54fe3f2681749817baceb3e99e6fc9f3965",
            196817,
            "服务协议",
        ),
        ("en", "privacy"): (
            "PrivacyStatement_en.html",
            "e2f542f723b332188db98d428a49b15d5430b4b3e2722338b2df8aed31882f1b",
            47981,
            "Issuance/Effective Date: March 26, 2026",
        ),
        ("zh-Hans", "privacy"): (
            "PrivacyStatement_zh-Hans.html",
            "ff1a8d79ee2ee6b2b095129a0187a54f7e39c83f2b8e233b71988a72e513028d",
            38500,
            "发布/生效日期：2026年3月26日",
        ),
    }
    assert bundle["app_version"] == "1.18.1"
    assert (
        bundle["source_apk_sha256"]
        == "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
    )
    assert len(bundle["documents"]) == 4
    for document in bundle["documents"]:
        filename, sha, size, visible = expected[(document["locale"], document["kind"])]
        assert document["source_reference"] == "agreement/" + filename
        assert (document["source_sha256"], document["source_bytes"]) == (sha, size)
        rendered = json.dumps(document["blocks"], ensure_ascii=False)
        assert visible in rendered
        assert "<script" not in rendered and "common.js" not in rendered
        canonical = json.dumps(
            document["blocks"],
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        assert hashlib.sha256(canonical).hexdigest() == document["content_sha256"]
    privacy = next(
        doc
        for doc in bundle["documents"]
        if doc["locale"] == "en" and doc["kind"] == "privacy"
    )
    assert any(block["type"] == "table" for block in privacy["blocks"])
    assert any(block["type"] == "list" for block in privacy["blocks"])
    assert "Tencent Technology (Shenzhen) Co., Ltd." in json.dumps(privacy["blocks"])


def build(**overrides):
    generator = module("scripts/dev/write_tvt_startup_profile.py")
    inputs = {
        "public_origin": "https://wso.example.test:8443",
        "region": "KR",
        "default_locale": "en",
        "timezone": "Asia/Seoul",
        "ui_locale": "ko",
        "enable_settings": False,
    }
    inputs.update(overrides)
    return generator.build_profile(**inputs)


def test_profile_is_actual_validated_contract_with_local_policy_routes(monkeypatch):
    profile = build()
    assert isinstance(profile, StartupProfile)
    assert profile.terms.url == "https://wso.example.test:8443/tvt/policies/en/terms"
    assert profile.privacy.source_reference == "agreement/PrivacyStatement_en.html"
    assert profile.supported_locales == ["en", "zh-Hans"]
    assert profile.local_routes == [] and menu(profile) == []
    assert profile.consent_version.startswith("slp-1.18.1-")
    assert build(default_locale="zh-Hans").consent_version == profile.consent_version
    assert build(default_locale="zh-Hans").terms.url.endswith("/zh-Hans/terms")
    monkeypatch.setenv("WSO_TVT_STARTUP_PROFILE", profile.model_dump_json())
    assert load_profile() == profile
    assert [entry.path for entry in menu(build(enable_settings=True))] == [
        "/tvt/settings"
    ]


@pytest.mark.parametrize(
    "settings,expected",
    [
        (False, ["/tvt/account"]),
        (True, ["/tvt/account", "/tvt/settings"]),
    ],
)
def test_account_route_requires_independent_opt_in_and_keeps_menu_order(
    settings, expected
):
    profile = build(enable_account=True, enable_settings=settings)
    assert profile.local_routes == expected
    assert [(entry.id, entry.path) for entry in menu(profile)] == [
        ("local-account", "/tvt/account")
    ] + ([("local-settings", "/tvt/settings")] if settings else [])


@pytest.mark.parametrize(
    "include_route,include_component", [(False, True), (True, False)]
)
def test_account_opt_in_refuses_missing_web_route_or_component(
    tmp_path, monkeypatch, include_route, include_component
):
    generator = module("scripts/dev/write_tvt_startup_profile.py")
    if include_route:
        route = tmp_path / "apps/web/src/app/tvt/[[...path]]/page.tsx"
        route.parent.mkdir(parents=True)
        route.touch()
    if include_component:
        component = tmp_path / "apps/web/src/features/tvt/account/SessionBoundary.tsx"
        component.parent.mkdir(parents=True)
        component.touch()
    monkeypatch.setattr(generator, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="account web route"):
        generator.build_profile(
            public_origin="https://wso.example.test",
            region="KR",
            default_locale="en",
            timezone="UTC",
            enable_account=True,
        )


@pytest.mark.parametrize(
    "origin",
    [
        "http://wso.test",
        "https://user:pass@wso.test",
        "https://wso.test/path",
        "https://wso.test?x=1",
        "https://wso.test#x",
        "https://wso.test:wrong",
        "https://wso.test\\@evil.test",
        "https://wso.test\n",
        "https://.",
        "https://-invalid.test",
        "https://wso..test",
        "https://wso.test:",
    ],
)
def test_profile_rejects_untrusted_origins(origin):
    with pytest.raises(ValueError):
        build(public_origin=origin)


@pytest.mark.parametrize(
    "override",
    [
        {"region": "kr"},
        {"region": "KR / ../../"},
        {"region": ""},
        {"timezone": "Mars/Nowhere"},
        {"timezone": "../UTC"},
        {"default_locale": "ko"},
        {"ui_locale": "en"},
    ],
)
def test_profile_rejects_malformed_or_unsupported_configuration(override):
    with pytest.raises(ValueError):
        build(**override)


def test_profile_cli_is_bounded_atomic_and_never_overwrites_env(tmp_path):
    script = ROOT / "scripts/dev/write_tvt_startup_profile.py"
    assert script.is_file(), "Missing profile writer"
    output = tmp_path / "startup.json"
    argv = [
        sys.executable,
        str(script),
        "--public-origin",
        "https://wso.example.test",
        "--region",
        "KR",
        "--default-locale",
        "en",
        "--timezone",
        "Asia/Seoul",
        "--ui-locale",
        "ko",
        "--output-root",
        str(tmp_path),
        "--output",
        str(output),
    ]
    result = subprocess.run(argv, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    StartupProfile.model_validate_json(output.read_text(encoding="utf-8"))
    before = output.read_bytes()
    assert subprocess.run(argv, capture_output=True, check=False).returncode != 0
    assert output.read_bytes() == before
    bad = argv[:-1] + [str(tmp_path.parent / "escape.json")]
    assert subprocess.run(bad, capture_output=True, check=False).returncode != 0
    env = tmp_path / ".env"
    env.write_text("KEEP", encoding="utf-8")
    assert (
        subprocess.run(
            argv[:-1] + [str(env)], capture_output=True, check=False
        ).returncode
        != 0
    )
    assert env.read_text() == "KEEP"
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "flags,expected",
    [
        ([], []),
        (["--enable-settings"], ["/tvt/settings"]),
        (["--enable-account"], ["/tvt/account"]),
        (["--enable-settings", "--enable-account"], ["/tvt/account", "/tvt/settings"]),
    ],
)
def test_profile_cli_writes_explicit_account_route_combinations(
    tmp_path, flags, expected
):
    output = tmp_path / "startup.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts/dev/write_tvt_startup_profile.py"),
            "--public-origin",
            "https://wso.example.test",
            "--region",
            "KR",
            "--default-locale",
            "en",
            "--timezone",
            "Asia/Seoul",
            "--output-root",
            str(tmp_path),
            "--output",
            str(output),
            *flags,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (
        StartupProfile.model_validate_json(
            output.read_text(encoding="utf-8")
        ).local_routes
        == expected
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_sha256", "0" * 64),
        ("source_bytes", 1),
        ("source_reference", "agreement/ServiceTerms_zh-Hans.html"),
    ],
)
def test_profile_rejects_a_bundle_claiming_unreviewed_source_metadata(
    tmp_path, monkeypatch, field, value
):
    generator = module("scripts/dev/write_tvt_startup_profile.py")
    bundle = policies()
    bundle["documents"][0][field] = value
    changed = tmp_path / "policies.json"
    changed.write_text(json.dumps(bundle), encoding="utf-8")
    monkeypatch.setattr(generator, "CONTENT", changed)
    with pytest.raises(ValueError, match="reviewed source"):
        generator.build_profile(
            public_origin="https://wso.example.test",
            region="KR",
            default_locale="en",
            timezone="UTC",
        )
