"""Signature checks and full image validation within an owned memory-limited child."""

from __future__ import annotations

from dataclasses import asdict
from typing import Literal, cast

from wso_core.asset_process import exchange_owned
from wso_core.storage import (
    AssetPolicy,
    ImageInfo,
    ImageMime,
    IOBudget,
    StorageFailure,
    VerifiedPlaintext,
)

ImageCode = Literal[
    "TYPE", "DECODE", "PIXELS", "DIMENSIONS", "FRAMES", "DEADLINE", "UNAVAILABLE"
]


class ImageValidationFailure(Exception):
    def __init__(self, code: ImageCode) -> None:
        self.code = code
        super().__init__(code)


class ImageValidator:
    def __init__(self, *, policy: AssetPolicy) -> None:
        self.policy = policy

    def sniff(self, prefix: bytes) -> ImageMime:
        if type(prefix) is not bytes:
            raise ImageValidationFailure("TYPE")
        prefix = prefix[:32]
        if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if prefix.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        raise ImageValidationFailure("TYPE")

    def validate(
        self,
        plaintext: VerifiedPlaintext,
        *,
        expected_type: ImageMime,
        budget: IOBudget,
    ) -> ImageInfo:
        from wso_core.asset_image_worker import image_child

        if (
            plaintext.byte_size > self.policy.max_bytes
            or self.sniff(plaintext.data[:32]) != expected_type
        ):
            raise ImageValidationFailure("TYPE")
        try:
            response, body = exchange_owned(
                image_child,
                {
                    "version": 1,
                    "policy": asdict(self.policy),
                    "expected_type": expected_type,
                },
                plaintext.data,
                request_cap=self.policy.max_bytes,
                response_cap=0,
                budget=budget,
                mutating=False,
                wall_seconds=self.policy.decoder_seconds,
            )
            if body:
                raise ImageValidationFailure("UNAVAILABLE")
            if response.get("ok") is False:
                if set(response) != {"ok", "code"} or response["code"] not in (
                    "TYPE",
                    "DECODE",
                    "PIXELS",
                    "DIMENSIONS",
                    "FRAMES",
                    "DEADLINE",
                    "UNAVAILABLE",
                ):
                    raise ImageValidationFailure("UNAVAILABLE")
                raise ImageValidationFailure(cast(ImageCode, response["code"]))
            if (
                set(response) != {"ok", "image"}
                or response["ok"] is not True
                or type(response["image"]) is not dict
                or set(response["image"])
                != {
                    "content_type",
                    "width",
                    "height",
                    "oriented_width",
                    "oriented_height",
                    "frame_count",
                }
            ):
                raise ImageValidationFailure("UNAVAILABLE")
            result = ImageInfo(**response["image"])
            if (
                result.content_type != expected_type
                or result.width * result.height > self.policy.max_pixels
                or result.oriented_width * result.oriented_height
                > self.policy.max_pixels
                or max(
                    result.width,
                    result.height,
                    result.oriented_width,
                    result.oriented_height,
                )
                > self.policy.max_dimension
            ):
                raise ImageValidationFailure("UNAVAILABLE")
            budget.remaining_seconds()
            return result
        except StorageFailure as error:
            raise ImageValidationFailure(
                "DEADLINE" if error.code == "DEADLINE" else "UNAVAILABLE"
            ) from None
        except (ValueError, TypeError, KeyError):
            raise ImageValidationFailure("UNAVAILABLE") from None
