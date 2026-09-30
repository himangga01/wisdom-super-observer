from __future__ import annotations

import hashlib
import io
import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

import pytest
from PIL import Image
from test_asset_storage_primitives import encrypted, make_aad
from wso_core.asset_crypto import AssetCipher, AssetCryptoFailure, LocalAssetKeyProvider
from wso_core.asset_images import ImageValidationFailure, ImageValidator
from wso_core.storage import AssetPolicy, IOBudget, VerifiedPlaintext


def secure_key(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    if os.name == "nt":
        literal = str(path).replace("'", "''")
        script = (
            "$p='"
            + literal
            + "'; $a=New-Object System.Security.AccessControl.FileSecurity; "
            "$s=[System.Security.Principal.WindowsIdentity]::GetCurrent().User; "
            "$a.SetOwner($s);$a.SetAccessRuleProtection($true,$false); "
            "$r=New-Object System.Security.AccessControl.FileSystemAccessRule($s,'FullControl','Allow'); "
            "$a.AddAccessRule($r);[System.IO.File]::SetAccessControl($p,$a)"
        )
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        path.chmod(0o600)
    return path


def test_local_key_rotation_retains_old_key_and_never_falls_back(tmp_path) -> None:
    first = secure_key(tmp_path / "old.key", b"1" * 32)
    second = secure_key(tmp_path / "new.key", b"2" * 32)
    old = LocalAssetKeyProvider(active_key_id="old", key_files={"old": first})
    aad = b"bound wrapping context"
    envelope = old.wrap("old", b"d" * 32, aad)
    rotated = LocalAssetKeyProvider(
        active_key_id="new", key_files={"old": first, "new": second}
    )
    assert rotated.unwrap("old", envelope, aad) == b"d" * 32
    newest = rotated.wrap("new", b"e" * 32, aad)
    assert rotated.unwrap("new", newest, aad) == b"e" * 32
    with pytest.raises(AssetCryptoFailure):
        rotated.wrap("old", b"d" * 32, aad)
    missing = LocalAssetKeyProvider(active_key_id="new", key_files={"new": second})
    with pytest.raises(AssetCryptoFailure) as failure:
        missing.unwrap("old", envelope, aad)
    assert failure.value.code == "KEY_UNAVAILABLE"
    wrong = secure_key(tmp_path / "wrong.key", b"3" * 32)
    provider = LocalAssetKeyProvider(active_key_id="old", key_files={"old": wrong})
    with pytest.raises(AssetCryptoFailure):
        provider.unwrap("old", envelope, aad)
    with pytest.raises(AssetCryptoFailure):
        rotated.unwrap("old", envelope, aad + b"altered")


def test_key_startup_denies_default_acl_and_wrong_length(tmp_path) -> None:
    insecure = tmp_path / "insecure.key"
    insecure.write_bytes(b"k" * 32)
    if os.name != "nt":
        insecure.chmod(0o644)
    with pytest.raises(AssetCryptoFailure):
        LocalAssetKeyProvider(active_key_id="k", key_files={"k": insecure})
    short = secure_key(tmp_path / "short.key", b"k" * 31)
    with pytest.raises(AssetCryptoFailure):
        LocalAssetKeyProvider(active_key_id="k", key_files={"k": short})


def test_nonce_uniqueness_and_prepared_copy_denied(tmp_path) -> None:
    provider = LocalAssetKeyProvider(
        active_key_id="k", key_files={"k": secure_key(tmp_path / "key", b"k" * 32)}
    )
    cipher = AssetCipher(provider)
    one, two = cipher.prepare(make_aad(b"a")), cipher.prepare(make_aad(b"a"))
    assert one.data_key != two.data_key
    assert one.envelope.object_nonce != two.envelope.object_nonce
    assert one.envelope.wrapped_key.wrap_nonce != two.envelope.wrapped_key.wrap_nonce
    with pytest.raises(AssetCryptoFailure):
        cipher.start(replace(one))
    cipher.start(one)


def test_crypto_shared_budget_expiry_prevents_return() -> None:
    cipher, _, _, raw, manifest = encrypted(b"private")
    deadline = time.monotonic() + 0.03

    def chunks():
        yield raw[:20]
        time.sleep(0.05)
        yield raw[20:]

    with pytest.raises(AssetCryptoFailure) as failure:
        cipher.decrypt_verified(manifest, chunks(), budget=IOBudget(deadline))
    assert failure.value.code == "DEADLINE"


def image_bytes(
    width: int = 11,
    height: int = 7,
    *,
    fmt: str = "PNG",
    orientation: int | None = None,
    animated: bool = False,
) -> bytes:
    buf = io.BytesIO()
    image = Image.new("RGB", (width, height), "red")
    if animated:
        image.save(
            buf,
            format="PNG",
            save_all=True,
            append_images=[Image.new("RGB", (width, height), "blue")],
            duration=20,
        )
    elif orientation is not None:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(buf, format=fmt, exif=exif)
    else:
        image.save(buf, format=fmt)
    return buf.getvalue()


def validate(
    data: bytes, *, policy: AssetPolicy | None = None, mime: str = "image/png"
):
    return ImageValidator(policy=policy or AssetPolicy(version=1)).validate(
        VerifiedPlaintext(data, len(data), hashlib.sha256(data).hexdigest()),
        expected_type=mime,
        budget=IOBudget(time.monotonic() + 10),
    )


@pytest.mark.parametrize(
    "case,code",
    [
        ("pixels", "PIXELS"),
        ("dimensions", "DIMENSIONS"),
        ("frames", "FRAMES"),
        ("orientation", "DECODE"),
        ("type", "TYPE"),
    ],
)
def test_image_real_decoder_rejects_limits(case: str, code: str) -> None:
    data = image_bytes(
        animated=case == "frames", orientation=9 if case == "orientation" else None
    )
    policy = AssetPolicy(
        version=1,
        max_pixels=60 if case == "pixels" else 25000000,
        max_dimension=10 if case == "dimensions" else 10000,
    )
    with pytest.raises(ImageValidationFailure) as failure:
        validate(
            data, policy=policy, mime="image/jpeg" if case == "type" else "image/png"
        )
    assert failure.value.code == code


def test_image_jpeg_orientation_and_truncation() -> None:
    raw = image_bytes(fmt="JPEG", orientation=6)
    info = validate(raw, mime="image/jpeg")
    assert (info.width, info.height) == (11, 7)
    assert (info.oriented_width, info.oriented_height) == (7, 11)
    with pytest.raises(ImageValidationFailure):
        validate(raw[:-8], mime="image/jpeg")


def test_image_decoder_refuses_spent_budget_without_helper() -> None:
    from wso_core.asset_process import owned_helper_pids

    data = image_bytes()
    with pytest.raises(ImageValidationFailure) as failure:
        ImageValidator(policy=AssetPolicy(version=1)).validate(
            VerifiedPlaintext(data, len(data), hashlib.sha256(data).hexdigest()),
            expected_type="image/png",
            budget=IOBudget(time.monotonic() + 1),
        )
    assert failure.value.code == "DEADLINE"
    assert owned_helper_pids() == ()
