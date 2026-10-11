"""Pure bounded N9000 notification header shape; no login crypto imports."""

# 2561 has no APK body parser:92 is the root-observed strict opaque bound.
# 2562/2563 read exactly40/36 bytes in ml2.a/il2.a. Never generalize the
# dispatcher default return into admission of arbitrary commands or lengths.
_STARTUP_BODY_LENGTHS = {2561: 92, 2562: 40, 2563: 36}


def _is_startup_header(
    command: int,
    sequence: int,
    flags: int,
    encoding: int,
    length: int,
) -> bool:
    return (
        command in _STARTUP_BODY_LENGTHS
        and sequence == 0
        and flags == 0
        and encoding == 0
        and length == _STARTUP_BODY_LENGTHS[command]
    )
