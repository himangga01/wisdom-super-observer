"""Selected Linux acceptance always requires actual PostgreSQL, S3 and HTTP."""

pytest_plugins = ["tests.support.asset_harness"]


def test_photo_upload_does_not_require_a_store(asset_harness):
    from tests.support.asset_harness import synthetic_image

    data = synthetic_image()
    asset = asset_harness.upload(data)
    assert asset["state"] == "READY"
    assert asset["store_id"] is None
    downloaded = asset_harness.download(asset["id"])
    assert downloaded.status_code == 200
    assert downloaded.content == data
    assert (
        asset_harness.download(asset["id"], actor=asset_harness.actors[1]).status_code
        == 404
    )
