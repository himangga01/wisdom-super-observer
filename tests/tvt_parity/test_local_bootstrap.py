"""Invented private context; no APK runtime, device or credential access."""

import json
from dataclasses import FrozenInstanceError
from importlib import import_module, util

import pytest


def module():
    # A missing implementation is an assertion failure, not a collection error.
    assert util.find_spec("wso_core.tvt.local_bootstrap") is not None
    return import_module("wso_core.tvt.local_bootstrap")


def runtime(**changes):
    values = {
        "private_files_path": "/data/user/0/example.helper/files",
        "single_id": "invented-helper-instance",
        "source_network_type": 4,
    }
    values.update(changes)
    return module().TrustedAndroidRuntime(**values)


def select(country="KR", **changes):
    values = {
        "country_code": country,
        "runtime": runtime(),
        "attempt_branch": "initial",
    }
    values.update(changes)
    return module().select_local_bootstrap(**values)


@pytest.mark.parametrize(
    "country,domain,region,reason",
    [
        ("KR", "autonatap.com", "AP", "country_match"),
        ("US", "autonat.us", "US", "country_match"),
        ("CN", "autonat.cn", "CN", "country_match"),
        ("RU", "autonatru.com", "RU", "country_match"),
        ("GB", "autonateu.com", "EU", "country_match"),
        ("CA", "autonatglb.com", "GLB", "country_match"),
        ("TW", "autonatglb.com", "GLB", "resource_default"),
        ("", "autonatglb.com", "GLB", "resource_default"),
        ("ZZ", "autonatglb.com", "GLB", "resource_default"),
    ],
)
def test_region_initialization_replaces_xml_nat2(country, domain, region, reason):
    profile = select(country)
    payload = json.loads(profile.private_helper_json())
    assert (payload["nat1Host"], payload["nat1Port"]) == ("c2.autonat.com", 40002)
    assert (payload["nat2Host"], payload["nat2Port"]) == (f"cli-nat20.{domain}", 7968)
    assert profile.region_id == region
    assert profile.selection_reason == reason
    assert profile.saved_state == "unobserved"


def test_exact_build_transform_and_private_schema_without_credentials():
    profile = select()
    text = profile.private_helper_json()
    assert json.loads(text) == {
        "nat1Host": "c2.autonat.com",
        "nat1Port": 40002,
        "nat2Host": "cli-nat20.autonatap.com",
        "nat2Port": 7968,
        "networkFlag": 1,
        "traversalMode": 0,
        "disableUPnP": False,
        "privateFilesPath": "/data/user/0/example.helper/files",
        "platform": "AND",
        "appVersion": "1.18.1.20267",
        "appName": "AND_M_PH_SuperLivePlus",
        "model": "invented-helper-instance",
    }
    assert text == profile.private_helper_json()
    assert profile.package_name == "com.tvt.superliveplus"
    assert (
        profile.apk_sha256
        == "f57ff98226fcc7a0ec3587b077d5538facb57cc5b713a0938d1ee02b0f72f281"
    )
    assert "invented-helper-instance" not in repr(profile)
    assert "example.helper" not in repr(profile)
    assert "invented-helper-instance" not in repr(runtime())
    assert len(profile.source_sha256) >= 6
    with pytest.raises(FrozenInstanceError):
        profile.region_id = "GLB"


@pytest.mark.parametrize("network,flag", [(0, 0), (2, 0), (3, 0), (4, 1), (5, 0)])
def test_wifi_comparison_is_the_source_network_flag(network, flag):
    payload = json.loads(
        select(runtime=runtime(source_network_type=network)).private_helper_json()
    )
    assert payload["networkFlag"] == flag


@pytest.mark.parametrize(
    "branch,mode,disabled",
    [
        ("initial", 0, False),
        ("retry_nat1", 1, False),
        ("retry_disable_upnp", 0, True),
        ("retry_nat1_disable_upnp", 1, True),
    ],
)
def test_explicit_source_attempt_history_controls_flags(branch, mode, disabled):
    payload = json.loads(select(attempt_branch=branch).private_helper_json())
    assert (payload["traversalMode"], payload["disableUPnP"]) == (mode, disabled)


def test_saved_resource_root_and_address_overrides_are_separate_operator_input():
    saved = module().ReviewedSavedOverrides(
        root_domain="autonateu.com", nat2_address="c2020.autonat.com:8888"
    )
    profile = select(saved_overrides=saved)
    payload = json.loads(profile.private_helper_json())
    assert profile.source_region_id == "AP"
    assert profile.region_id == "EU"
    assert profile.saved_state == "operator_supplied"
    assert profile.selection_reason == "operator_root_domain"
    assert (payload["nat2Host"], payload["nat2Port"]) == ("c2020.autonat.com", 8888)
    assert "operator_supplied" not in profile.private_helper_json()


@pytest.mark.parametrize(
    "changes",
    [
        {"nat1_address": "evil.invalid:40002"},
        {"nat2_address": "https://cli-nat20.autonatap.com:7968"},
        {"nat2_address": "cli-nat20.autonatap.com"},
        {"nat1_address": "c2.autonat.com"},
        {"nat1_address": "c2.autonat.com:0"},
        {"nat1_address": "c2.autonat.com:65536"},
        {"nat2_address": "cli-nat20.autonatap.com:9998"},
        {"nat1_address": "c2.autonat.com:80"},
        {"nat1_address": "c2.autonat.com:040002"},
        {"nat1_address": "c2.autonat.com:True"},
        {"nat1_address": "c2.autonat.com:40002\x00"},
        {"nat2_address": "x" * 64 + ":7968"},
        {"nat1_address": "x" * 128 + ":40002"},
        {"root_domain": "autonatglbsit.com"},
        {"root_domain": "autonatap.com\x00"},
        {"root_domain": ""},
        {"nat2_address": 7968},
    ],
)
def test_unreviewed_hosts_fallbacks_ports_and_debug_domains_are_rejected(changes):
    with pytest.raises(module().LocalBootstrapError):
        module().ReviewedSavedOverrides(**changes)


@pytest.mark.parametrize("country", ["kr", " KR", "AP", "KOR", None, {}, "K\x00", "éA"])
def test_country_contract_rejects_malformed_and_region_alias_input(country):
    with pytest.raises(module().LocalBootstrapError):
        select(country)


@pytest.mark.parametrize(
    "changes",
    [
        {"single_id": ""},
        {"single_id": "x\x00y"},
        {"single_id": "\ud800"},
        {"single_id": "é" * 32},
        {"private_files_path": "é" * 256},
        {"private_files_path": "relative/files"},
        {"private_files_path": "/a/../files"},
        {"private_files_path": "/a/./files"},
        {"private_files_path": "/a//files"},
        {"private_files_path": "/a\\files"},
        {"private_files_path": "/a\x00/files"},
        {"source_network_type": True},
        {"source_network_type": 1},
        {"source_network_type": -1},
        {"source_network_type": "4"},
    ],
)
def test_runtime_unicode_utf8_path_and_network_admission(changes):
    with pytest.raises(module().LocalBootstrapError):
        runtime(**changes)


def test_runtime_native_bounds_are_bytes_and_do_not_truncate():
    profile = select(
        runtime=runtime(single_id="é" * 31 + "a", private_files_path="/" + "a" * 254)
    )
    payload = json.loads(profile.private_helper_json())
    assert payload["model"] == "é" * 31 + "a"
    assert payload["privateFilesPath"] == "/" + "a" * 254
    # The helper must still check composed path against a separately supplied SN.


@pytest.mark.parametrize(
    "changes",
    [
        {"runtime": {}},
        {"saved_overrides": {}},
        {"attempt_branch": "automatic"},
        {"attempt_branch": 0},
        {"package_name": "com.other.app"},
        {"nat2_host": "evil.invalid"},
        {"resource_path": "browser.xml"},
    ],
)
def test_factory_accepts_only_typed_private_context_and_fixed_resources(changes):
    with pytest.raises((module().LocalBootstrapError, TypeError)):
        select(**changes)


def test_profile_cannot_be_constructed_from_browser_field_dictionary():
    with pytest.raises(TypeError):
        module().LocalBootstrapProfile(nat1Host="evil.invalid", nat1Port=80)
