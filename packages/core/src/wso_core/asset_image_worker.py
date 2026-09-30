"""Fixed decoder child; establish kernel memory limit before receiving plaintext."""

from __future__ import annotations

import ctypes
import io
import os
import socket
import warnings
from dataclasses import asdict, fields
from typing import Any, cast

from wso_core.asset_images import ImageValidationFailure
from wso_core.asset_process import child_request, child_response, quiet_child
from wso_core.storage import MAX_BYTES, AssetPolicy, ImageInfo, ImageMime

_job_handle: Any = None


def _memory_limit(max_bytes: int) -> None:
    global _job_handle
    if os.name != "nt":
        import resource

        cast(Any, resource).setrlimit(
            cast(Any, resource).RLIMIT_AS, (max_bytes, max_bytes)
        )
        return
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IOCount(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_ulonglong)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BasicLimits),
            ("IoInfo", IOCount),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel = cast(Any, ctypes).WinDLL("kernel32", use_last_error=True)
    kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    kernel.SetInformationJobObject.restype = wintypes.BOOL
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    kernel.AssignProcessToJobObject.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.CreateJobObjectW(None, None)
    if not handle:
        raise ImageValidationFailure("UNAVAILABLE")
    limits = ExtendedLimits()
    limits.BasicLimitInformation.LimitFlags = 0x100 | 0x2000
    limits.ProcessMemoryLimit = max_bytes
    if not kernel.SetInformationJobObject(
        handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
    ) or not kernel.AssignProcessToJobObject(handle, kernel.GetCurrentProcess()):
        kernel.CloseHandle(handle)
        raise ImageValidationFailure("UNAVAILABLE")
    # Keep handle open until this owned process exits; closing it kills the job.
    _job_handle = handle


def _decode(data: bytes, policy: AssetPolicy, expected: ImageMime) -> ImageInfo:
    from PIL import Image, ImageFile, ImageOps

    ImageFile.LOAD_TRUNCATED_IMAGES = False
    Image.MAX_IMAGE_PIXELS = policy.max_pixels

    def dimensions(width: int, height: int) -> None:
        if min(width, height) < 1 or max(width, height) > policy.max_dimension:
            raise ImageValidationFailure("DIMENSIONS")
        if width * height > policy.max_pixels:
            raise ImageValidationFailure("PIXELS")

    def metadata(image: Any) -> tuple[int, int, int]:
        actual = {"PNG": "image/png", "JPEG": "image/jpeg"}.get(image.format)
        if actual != expected:
            raise ImageValidationFailure("TYPE")
        width, height = image.size
        dimensions(width, height)
        frames = getattr(image, "n_frames", 1)
        if frames != 1:
            raise ImageValidationFailure("FRAMES")
        return width, height, frames

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as image:
                width, height, frames = metadata(image)
                image.verify()
            with Image.open(io.BytesIO(data)) as image:
                if metadata(image) != (width, height, frames):
                    raise ImageValidationFailure("DECODE")
                orientation = image.getexif().get(274, 1)
                if type(orientation) is not int or not 1 <= orientation <= 8:
                    raise ImageValidationFailure("DECODE")
                oriented_width, oriented_height = (
                    (height, width) if orientation in (5, 6, 7, 8) else (width, height)
                )
                dimensions(oriented_width, oriented_height)
                image.load()
                oriented = ImageOps.exif_transpose(image)
                try:
                    if oriented.size != (oriented_width, oriented_height):
                        raise ImageValidationFailure("DECODE")
                    dimensions(*oriented.size)
                finally:
                    oriented.close()
                return ImageInfo(
                    expected, width, height, oriented_width, oriented_height, frames
                )
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ImageValidationFailure("PIXELS") from None
    except (OSError, ValueError, SyntaxError, EOFError):
        raise ImageValidationFailure("DECODE") from None
    except MemoryError:
        raise ImageValidationFailure("UNAVAILABLE") from None


def image_child(sock: socket.socket) -> None:
    quiet_child()
    deadline = 0.0
    try:
        _memory_limit(536870912)
        control, data, deadline = child_request(sock, MAX_BYTES)
        if (
            set(control) != {"version", "policy", "expected_type"}
            or type(control["version"]) is not int
            or control["version"] != 1
            or type(control["policy"]) is not dict
            or set(control["policy"]) != {f.name for f in fields(AssetPolicy)}
        ):
            raise ImageValidationFailure("UNAVAILABLE")
        policy = AssetPolicy(**control["policy"])
        if policy.decoder_memory_bytes != 536870912:
            _memory_limit(policy.decoder_memory_bytes)
        if len(data) > policy.max_bytes or control["expected_type"] not in (
            "image/png",
            "image/jpeg",
        ):
            raise ImageValidationFailure("TYPE")
        info = _decode(data, policy, control["expected_type"])
        child_response(sock, {"ok": True, "image": asdict(info)}, b"", 0, deadline)
    except BaseException as error:  # noqa: BLE001 - child boundary must sanitize all failures
        if deadline:
            code = (
                error.code
                if isinstance(error, ImageValidationFailure)
                else "UNAVAILABLE"
            )
            try:
                child_response(sock, {"ok": False, "code": code}, b"", 0, deadline)
            except BaseException:  # noqa: BLE001 - disconnected private channel
                return
    finally:
        sock.close()
