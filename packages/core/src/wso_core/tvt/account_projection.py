"""Allowlisted projections from APK 1.18.1 UserInfoBeanNew and h62/rl1/f11.

No private user/installer IDs, upstream image paths, URLs or response strings
are returned. Account type 0/1/4 means none/user/installer; unknown integers
remain unknown rather than silently acquiring user/installer privileges.
"""

import base64
import binascii

from pydantic import ValidationError
from wso_contracts.tvt.account import AccountProfileFields

from wso_core.tvt.account_protocol import AccountProtocolError, private_json


class AccountFailure(ValueError):
    def __init__(self, code: str = "ACCOUNT_UNAVAILABLE", status: int = 503) -> None:
        self.code, self.status = code, status
        super().__init__(code)


def project_profile(body: bytes) -> AccountProfileFields:
    result = None
    try:
        data = private_json(body).get("data")
        if type(data) is not dict:
            raise ValueError
        value = {
            name: data[source]
            for name, source in (
                ("account_type", "type"),
                ("user_name", "userName"),
                ("nickname", "nickName"),
                ("email", "email"),
                ("mobile", "mobile"),
                ("address", "address"),
                ("no_password", "noPassword"),
            )
            if source in data
        }
        image = data.get("image", "")
        if type(image) is not str:
            raise ValueError
        value["avatar_available"] = bool(image)
        result = AccountProfileFields.model_validate(value)
    except (ValueError, TypeError, ValidationError, AccountProtocolError):
        pass
    if result is None:
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502) from None
    return result


def project_image(value: str | None) -> tuple[str, str]:
    # h62.java:41-44 strips this exact prefix; rl1.j -> f11.a decodes Base64.
    # Re-encoding removes input whitespace and prevents forwarding an arbitrary
    # data URL. Only inert JPEG/PNG bytes pass this boundary, capped at 64 KiB.
    data = b""
    if type(value) is str and 0 < len(value) <= 90000:
        candidate = value.removeprefix("data:image/jpg;base64,")
        try:
            data = base64.b64decode("".join(candidate.split()), validate=True)
        except (ValueError, binascii.Error):
            pass
    if not 1 <= len(data) <= 65536:
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
    if data.startswith(b"\xff\xd8\xff") and data.endswith(b"\xff\xd9"):
        kind = "image/jpeg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82"):
        kind = "image/png"
    else:
        raise AccountFailure("ACCOUNT_PROTOCOL_INVALID", 502)
    return kind, base64.b64encode(data).decode("ascii")
