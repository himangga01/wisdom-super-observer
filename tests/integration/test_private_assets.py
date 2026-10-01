"""Fourteen direct Linux leaves: real HTTP, SQL, storage and broker witnesses.

The final age leaf deliberately runs last. No shortened hour, eager job, fake
page or SDK substitute can satisfy these tests.
"""

import hashlib
from datetime import UTC, datetime
from uuid import UUID

pytest_plugins = ["tests.support.asset_harness"]


def _digest(data):
    return hashlib.sha256(data).hexdigest()


def _roundtrip(h, asset, data, *, actor=None):
    response = h.download(asset["id"], actor=actor)
    assert response.status_code == 200
    assert _digest(response.content) == _digest(data)
    assert len(response.content) == len(data)


def test_photo_upload_does_not_require_a_store(asset_harness):
    h = asset_harness
    h.prepare_case()
    data = h.image()
    asset = h.upload(data)
    assert asset["state"] == "READY" and asset["store_id"] is None
    assert h.row(asset["id"])["state"] == "READY"
    _roundtrip(h, asset, data)
    h.assert_error(h.metadata(asset["id"], actor=h.actors[1]), 404)
    h.assert_error(h.ticket(asset["id"], actor=h.actors[1]), 404)
    h.assert_no_stores()
    h.erase(asset)


def test_upload_validation_rejects_truncation_checksum_and_type(asset_harness):
    h = asset_harness
    h.prepare_case()
    png, jpeg = h.image(), h.image(format="JPEG")
    trials = (
        (png, png[:32], {}, "chunked", 422, "ASSET_INTEGRITY"),
        (png, png, {}, "different-length", 422, "ASSET_LENGTH"),
        (png, png[:32], {}, "premature-eof", None, None),
        (
            png,
            png,
            {"checksum": {"algorithm": "SHA256", "value": "0" * 64}},
            "normal",
            422,
            "ASSET_INTEGRITY",
        ),
        (jpeg, jpeg, {}, "normal", 415, "ASSET_TYPE"),
        (
            b"\x89PNG\r\n\x1a\n" + b"x" * 64,
            None,
            {},
            "decode",
            503,
            "ASSET_UNAVAILABLE",
        ),
        (png[:32], None, {}, "decode", 503, "ASSET_UNAVAILABLE"),
    )
    for registered, body, overrides, transport, status, code in trials:
        h.prepare_scenario()  # Previous rejected upload and cleanup have settled.
        session = h.require_begin(registered, **overrides)
        body = registered if body is None else body
        response = (
            h.raw_put(session, body, mode=transport)
            if transport in {"different-length", "premature-eof"}
            else h.put(session, h.chunks(body) if transport == "chunked" else body)
        )
        if transport == "decode":
            assert response.status_code == 204
            response = h.complete(session["asset_id"])
            assert h.row(session["asset_id"])["failure_code"] == "DECODE"
        if status is not None:
            h.assert_error(response, status, code)
        else:
            h.assert_parser_disconnect(response)
        h.assert_never_ready(session["asset_id"])
        h.recover_rejected(session)


def test_upload_enforces_byte_pixel_dimension_and_frame_limits(asset_harness):
    h = asset_harness
    h.prepare_case()
    data = h.image()
    with h.policy(max_bytes=len(data)):
        boundary = h.upload(data)
        _roundtrip(h, boundary, data)
        h.assert_error(h.begin(data + b"x"), 413, "ASSET_LIMIT")
        for chunked in (False, True):
            h.prepare_scenario()
            session = h.require_begin(data)
            response = h.put(session, h.chunks(data + b"x") if chunked else data + b"x")
            h.assert_error(
                response,
                413 if chunked else 422,
                "ASSET_LIMIT" if chunked else "ASSET_LENGTH",
            )
            h.recover_rejected(session)
        h.prepare_scenario()  # The ready boundary asset has no live upload/ticket.
        h.erase(boundary)
    with h.policy(max_dimension=128, max_pixels=4096):
        for width, height in ((128, 1), (64, 64)):
            h.prepare_scenario()
            valid = h.image(width=width, height=height)
            asset = h.upload(valid)
            _roundtrip(h, asset, valid)
            h.erase(asset)
        for data, expected, private_code in (
            (h.image(width=129, height=1), 413, "DIMENSIONS"),
            (h.image(width=64, height=65), 413, "PIXELS"),
            (h.image(width=128, height=128), 413, "PIXELS"),
            (h.animated_image(), 503, "FRAMES"),
            (h.image()[:32], 503, "DECODE"),
        ):
            h.prepare_scenario()
            session = h.require_begin(data)
            assert h.put(session, data).status_code == 204
            h.assert_error(
                h.complete(session["asset_id"]),
                expected,
                "ASSET_LIMIT" if expected == 413 else "ASSET_UNAVAILABLE",
            )
            assert h.row(session["asset_id"])["failure_code"] == private_code
            h.assert_never_ready(session["asset_id"])
            h.recover_rejected(session)


def test_pending_ready_and_ticket_authorization_isolation(asset_harness):
    h = asset_harness
    h.prepare_case()
    data = h.image()
    pending, ready = h.require_begin(data), h.upload(data)
    foreign = h.actors[1]
    for response in (
        h.put(pending, data, actor=foreign),
        h.complete(pending["asset_id"], actor=foreign),
        h.delete(ready["id"], actor=foreign),
        h.metadata(ready["id"], actor=foreign),
        h.ticket(ready["id"], actor=foreign),
        h.begin(
            data, actor=foreign, purpose="IMPORT_CROP", parent_asset_id=ready["id"]
        ),
    ):
        h.assert_error(response, 404)
    issued = h.require_ticket(ready["id"])
    h.assert_error(h.download(ready["id"], actor=foreign, ticket=issued), 404)
    for actor in (h.same_user_session(), h.same_tenant_actor()):
        h.assert_error(h.put(pending, data, actor=actor), 404)
        h.assert_error(h.download(ready["id"], actor=actor, ticket=issued), 404)
        h.revoke_session(actor)
    for headers in (
        {},
        {"Origin": "https://wrong.test", "X-CSRF-Token": h.actors[0].csrf},
        {"Origin": "https://app.test", "X-CSRF-Token": "wrong"},
    ):
        assert (
            h.request(
                "DELETE",
                f"/api/v1/assets/{ready['id']}?tenant_id={h.actors[0].tenant_id}",
                csrf=False,
                headers=headers,
            ).status_code
            == 403
        )
    _roundtrip(h, ready, data)
    normal = h.require_ticket(ready["id"])
    assert h.download(ready["id"], ticket=normal).status_code == 200
    h.assert_error(h.download(ready["id"], ticket=normal), 404)
    expiry = h.require_ticket(ready["id"])
    h.wait_until_utc(datetime.fromisoformat(expiry["expires_at"]), cap=35)
    h.assert_error(h.download(ready["id"], ticket=expiry), 404)
    h.prove_runtime_authority_denials(ready)
    h.assert_evidence_unsupported(data)
    h.recover_rejected(pending)
    h.erase(ready)


def test_stored_bytes_are_encrypted_and_tamper_fails_closed(asset_harness):
    h = asset_harness
    h.prepare_case()
    data = h.image()
    a, b = h.upload(data), h.upload(h.image(noise=True))
    encrypted = h.raw_object(a)
    assert len(encrypted) == len(data) + 36
    assert encrypted[:8] == b"WSOAST01" and _digest(encrypted) != _digest(data)
    h.assert_not_image(encrypted)
    h.restart_api()
    _roundtrip(h, a, data)
    for trial in ("wrong-key", "tag", "magic", "nonce", "truncate", "other-envelope"):
        with h.corruption(a, trial, donor=b):
            h.assert_no_image(
                h.download(a["id"]), 422, "ASSET_INTEGRITY", asset_id=a["id"]
            )
    _roundtrip(h, a, data)
    h.erase(a, b, key_free=True)


def test_multipart_and_adapter_capabilities_against_real_s3(asset_harness):
    h = asset_harness
    h.prepare_case()
    data = h.large_image()
    assert 5242880 < len(data) <= 20971520
    session = h.require_begin(data)
    with h.paused_upload(session, data, after=6291456) as upload:
        parts = h.wait_parts(session)
        assert parts and parts[0]["Size"] >= 5242880
        upload.release()
        assert upload.result().status_code == 204
    response = h.complete(session["asset_id"])
    assert response.status_code == 200
    asset = response.json()
    _roundtrip(h, asset, data)
    h.exercise_normal_adapter(asset)
    h.exercise_presign(asset, expires_seconds=1)
    h.assert_anonymous_and_maintenance_denials(asset)
    h.erase(asset)


def test_upload_crash_recovery_and_abandoned_expiry(asset_harness):
    h = asset_harness
    h.prepare_case()
    for position in (
        "UPLOAD_INTENT_COMMITTED",
        "MULTIPART_CREATED_BEFORE_RECORD",
        "uploaded-part",
        "OBJECT_COMPLETED_BEFORE_SEAL",
        "VALIDATED_BEFORE_FINALIZE",
    ):
        h.prepare_scenario()
        h.gateway_crash_trial(position)
    for operation in ("CREATE_MULTIPART", "UPLOAD_PART", "COMPLETE_MULTIPART"):
        for hold in ("HOLD_REQUEST", "HOLD_RESPONSE"):
            h.prepare_scenario()
            h.live_helper_crash_trial(operation, hold)
    h.prepare_scenario()
    abandoned = h.require_begin(h.image())
    h.recover_rejected(abandoned, natural_expiry=True)


def test_download_revocation_and_stream_deadline(asset_harness):
    h = asset_harness
    h.prepare_case()
    for mutation in ("delete", "session", "membership", "parent"):
        h.revocation_trial(mutation, before_yield=False)
        h.revocation_trial(mutation, before_yield=True)
    asset = h.upload(h.large_image())
    h.prove_backpressure_deadline(asset, original_seconds=30, observation_seconds=45)
    h.erase(asset)


def test_parent_crop_scope_retention_and_cleanup(asset_harness):
    h = asset_harness
    h.prepare_case()
    stores = h.create_stores(2)
    for store in (None, stores[0]):
        h.prepare_scenario()
        parent = h.upload(h.image(), store_id=store)
        h.prepare_scenario()  # Parent upload is complete before starting the child.
        child = h.upload(
            h.image(),
            purpose="IMPORT_CROP",
            parent_asset_id=parent["id"],
            store_id=store,
        )
        assert child["store_id"] == parent["store_id"]
        assert datetime.fromisoformat(child["expires_at"]) <= datetime.fromisoformat(
            parent["expires_at"]
        )
        h.prove_invalid_parents(parent, child, other_store=stores[1])
        h.prepare_scenario()  # Invalid-parent uploads have completed recovery.
        h.erase(parent, child)
    h.prepare_scenario()
    parent = h.upload(h.image())
    crops = []
    for _ in range(100):
        h.prepare_scenario()  # Each prior crop is READY; no session-bound ticket.
        crops.append(
            h.upload(h.image(), purpose="IMPORT_CROP", parent_asset_id=parent["id"])
        )
    assert len(crops) == 100 and h.ready_child_count(parent["id"]) == 100
    before = h.asset_count()
    assert h.begin(
        h.image(), purpose="IMPORT_CROP", parent_asset_id=parent["id"]
    ).status_code in (409, 429)
    assert h.asset_count() == before
    h.prepare_scenario(required_seconds=505)  # 101 settled assets, 5s per DELETE.
    h.erase(parent, *crops)
    h.prepare_scenario()
    h.parent_overlap_trial("crop-first")
    h.prepare_scenario()
    h.parent_overlap_trial("delete-first")
    h.prepare_scenario()
    h.natural_parent_expiry_trial()


def test_asset_job_restart_and_wrong_tenant_reference(asset_harness):
    h = asset_harness
    h.prepare_case()
    asset = h.upload(h.image())
    with h.jobs() as jobs:
        jobs.assert_registry_and_runtime_denials()
        for position in ("after-read", "after-commit"):
            jobs.crash_and_recover(asset, position, recovery_seconds=160)
        for variant in (
            "other-tenant",
            "other-store",
            "no-attachment",
            "payload-other",
            "tombstoned",
            "parent-deleted",
            "membership-revoked",
            "photo-only-crop",
            "no-asset-read",
            "unknown-kind",
            "stale-generation",
            "guc-spoof",
        ):
            jobs.denial_trial(variant)
        jobs.assert_settled()
    h.erase(asset)


def test_cleanup_survives_actor_revocation_and_restart(asset_harness):
    h = asset_harness
    h.prepare_case()
    actor = h.new_actor()
    asset = h.upload(h.image(), actor=actor)
    assert h.delete(asset["id"], actor=actor).status_code == 202
    h.revoke_membership(actor)
    h.revoke_session(actor)
    h.cleanup_effect_crash_trial(asset, lease_seconds=30, observation_seconds=90)
    h.assert_deleted(asset)
    assert h.cleanup_success_count(asset["id"]) == 1


def test_delete_during_upload_and_retryable_provider_failure(asset_harness):
    h = asset_harness
    h.prepare_case()
    h.delete_during_complete_trial("callback")
    h.prepare_scenario()
    h.delete_during_complete_trial("HOLD_RESPONSE")
    h.prepare_scenario()
    h.absence_only_uncertainty_trial()
    for fault in ("DELETE_OBJECT", "LIST_OBJECTS", "LIST_MULTIPART"):
        h.prepare_scenario()
        asset = h.upload(h.image())
        before = h.row(asset["id"])
        assert h.delete(asset["id"]).status_code == 202
        first = h.row(asset["id"])
        assert first["access_generation"] > before["access_generation"]
        assert h.delete(asset["id"]).status_code == 202
        second = h.row(asset["id"])
        assert second["access_generation"] >= first["access_generation"]
        assert (
            h.query(
                "SELECT count(*) AS n FROM wso_private.asset_cleanup WHERE asset_id=:id",
                {"id": UUID(asset["id"])},
            )[0]["n"]
            == 1
        )
        assert h.cleanup_success_count(asset["id"]) == 0
        h.cleanup_transport_failure_trial(asset, fault)
        assert h.delete(asset["id"]).status_code == 202
        h.assert_deleted(asset)
        assert h.cleanup_success_count(asset["id"]) == 1
    h.assert_maintenance_no_read()


def test_encryption_key_rotation_and_missing_key_fail_closed(asset_harness):
    h = asset_harness
    h.prepare_case()
    data_a, data_b = h.image(), h.image(noise=True)
    a = h.upload(data_a)
    old = h.envelope_snapshot(a)
    old_ciphertext = hashlib.sha256(h.raw_object(a)).digest()
    h.restart_api(keys=("K1", "K2"), active="K2")
    b = h.upload(data_b)
    assert h.envelope_snapshot(a) == old
    assert hashlib.sha256(h.raw_object(a)).digest() == old_ciphertext
    assert h.envelope_snapshot(b)["key_id"] == "K2"
    h.restart_api(keys=("K1", "K2"), active="K2")
    _roundtrip(h, a, data_a)
    _roundtrip(h, b, data_b)
    h.restart_api(keys=("K2",), active="K2")
    h.assert_no_image(h.download(a["id"]), 503, "ASSET_UNAVAILABLE", asset_id=a["id"])
    _roundtrip(h, b, data_b)
    with h.wrong_key("K1"):
        h.restart_api(keys=("K1", "K2"), active="K2")
        h.assert_no_image(h.download(a["id"]), 422, "ASSET_INTEGRITY", asset_id=a["id"])
        _roundtrip(h, b, data_b)
        assert h.envelope_snapshot(a) == old
    h.erase(a, b, key_free=True)


def test_expired_pending_asset_and_orphan_reconciliation(asset_harness):
    h = asset_harness
    h.prepare_case()
    h.assert_young_epoch_witness()
    h.prepare_idle()
    h.resume_after_age()
    assert datetime.now(UTC) >= h.oldest_eligible_boundary()
    h.assert_original_seed_metadata()
    h.seed_post_age_young()
    h.prove_persisted_restart_and_full_epochs()
    h.assert_aged_work_and_young_refusals()
    h.drain_aged_cleanup()
    h.assert_seed_absence_and_survivors()
    h.assert_final_cursors_null()
    h.assert_no_unfinished_owned_work_except_conservative_negative()
