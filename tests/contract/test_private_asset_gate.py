"""The asset result gate cannot accept a partial, skipped or substituted suite."""

from xml.etree import ElementTree as ET

import pytest

from scripts.check_private_asset_results import (
    CLASSNAME,
    REQUIRED_CASES,
    verify_results,
)


def report(tmp_path, names=REQUIRED_CASES):
    root = ET.Element("testsuites")
    suite = ET.SubElement(root, "testsuite", tests="999", skipped="0", failures="0")
    for name in names:
        ET.SubElement(suite, "testcase", name=name, classname=CLASSNAME)
    path = tmp_path / "private-assets.xml"
    ET.ElementTree(root).write(path)
    return path


def test_accepts_only_complete_private_asset_suite(tmp_path):
    assert verify_results(report(tmp_path)) == 14


@pytest.mark.parametrize("missing", sorted(REQUIRED_CASES))
def test_missing_required_asset_case_fails(tmp_path, missing):
    with pytest.raises(ValueError, match="missing"):
        verify_results(report(tmp_path, REQUIRED_CASES - {missing}))


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
def test_aggregate_success_cannot_hide_nonpassing_asset_case(tmp_path, status):
    path = report(tmp_path)
    tree = ET.parse(path)
    ET.SubElement(next(tree.getroot().iter("testcase")), status)
    tree.write(path)
    with pytest.raises(ValueError, match="skipped or failed"):
        verify_results(path)


def test_unrelated_suite_cannot_substitute_for_actual_asset_suite(tmp_path):
    path = report(tmp_path)
    tree = ET.parse(path)
    for case in tree.getroot().iter("testcase"):
        case.set("classname", "tests.contract.test_private_assets")
    tree.write(path)
    with pytest.raises(ValueError, match="unexpected"):
        verify_results(path)


def test_duplicate_asset_receipt_is_rejected(tmp_path):
    names = list(REQUIRED_CASES)
    with pytest.raises(ValueError, match="duplicate"):
        verify_results(report(tmp_path, names + names[:1]))


def test_unknown_case_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="unexpected"):
        verify_results(report(tmp_path, REQUIRED_CASES | {"test_mock_provider"}))


def test_zero_cases_fails_despite_successful_aggregate(tmp_path):
    with pytest.raises(ValueError, match="missing"):
        verify_results(report(tmp_path, []))


def test_missing_malformed_and_oversize_reports_fail(tmp_path):
    path = tmp_path / "private-assets.xml"
    with pytest.raises(ValueError, match="missing or malformed"):
        verify_results(path)
    path.write_text("<invalid>")
    with pytest.raises(ValueError, match="missing or malformed"):
        verify_results(path)
    path.write_bytes(b" " * (4 * 1024 * 1024 + 1))
    with pytest.raises(ValueError, match="bound"):
        verify_results(path)


def test_entity_expansion_is_rejected_before_parse(tmp_path):
    path = tmp_path / "private-assets.xml"
    path.write_text('<!DOCTYPE testsuites [<!ENTITY x "sensitive">]><testsuites/>')
    with pytest.raises(ValueError, match="declarations"):
        verify_results(path)


@pytest.mark.parametrize("status", ["skipped", "failure", "error"])
@pytest.mark.parametrize("location", ["root", "suite", "nested"])
def test_nonpassing_status_anywhere_refuses_green_report(tmp_path, status, location):
    path = report(tmp_path)
    tree = ET.parse(path)
    root = tree.getroot()
    parent = root if location == "root" else root.find("testsuite")
    if location == "nested":
        parent = ET.SubElement(parent, "unsupported-wrapper")
    ET.SubElement(parent, status, message="owned provider teardown failed")
    tree.write(path)
    with pytest.raises(ValueError, match="skipped or failed"):
        verify_results(path)


@pytest.mark.parametrize("shape", ["wrapped-case", "nested-suite", "direct-root-cases"])
def test_unsupported_nesting_cannot_supply_required_case_set(tmp_path, shape):
    path = report(tmp_path)
    tree = ET.parse(path)
    root = tree.getroot()
    suite = root.find("testsuite")
    if shape == "wrapped-case":
        case = suite.find("testcase")
        suite.remove(case)
        ET.SubElement(suite, "wrapper").append(case)
    elif shape == "nested-suite":
        root.remove(suite)
        ET.SubElement(root, "testsuite").append(suite)
    else:
        for case in list(suite):
            root.append(case)
        root.remove(suite)
    tree.write(path)
    with pytest.raises(ValueError, match="structure"):
        verify_results(path)


def test_direct_suite_root_and_supported_junit_metadata_are_accepted(tmp_path):
    path = report(tmp_path)
    tree = ET.parse(path)
    suite = tree.getroot().find("testsuite")
    properties = ET.SubElement(suite, "properties")
    ET.SubElement(properties, "property", name="profile", value="private-assets")
    case = suite.find("testcase")
    ET.SubElement(case, "system-out").text = "sanitized output"
    ET.SubElement(case, "system-err").text = "sanitized stderr"
    ET.ElementTree(suite).write(path)
    assert verify_results(path) == 14


@pytest.mark.parametrize("encoding", ["utf-16", "utf-16-le", "utf-16-be"])
@pytest.mark.parametrize("with_entities", [False, True])
def test_utf16_reports_are_rejected_before_entity_expansion(
    tmp_path, encoding, with_entities
):
    path = report(tmp_path)
    xml = path.read_text()
    if with_entities:
        # Suite output exercises actual expansion while retaining all fourteen cases.
        xml = xml.replace("</testsuite>", "<system-out>&x;</system-out></testsuite>")
        xml = '<!DOCTYPE testsuites [<!ENTITY x "expanded">]>' + xml
    path.write_bytes(('<?xml version="1.0" encoding="UTF-16"?>' + xml).encode(encoding))
    with pytest.raises(ValueError, match="encoding"):
        verify_results(path)


def test_non_utf8_xml_declaration_is_rejected_before_parse(tmp_path):
    path = report(tmp_path)
    xml = path.read_text()
    path.write_bytes(
        ('<?xml version="1.0" encoding="ISO-8859-1"?>' + xml).encode("ascii")
    )
    with pytest.raises(ValueError, match="encoding"):
        verify_results(path)


def test_utf8_xml_declaration_and_bom_are_supported(tmp_path):
    path = report(tmp_path)
    xml = path.read_text()
    path.write_bytes(
        ('<?xml version="1.0" encoding="UTF-8"?>' + xml).encode("utf-8-sig")
    )
    assert verify_results(path) == 14
