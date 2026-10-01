"""Credential admission rejects unsafe purposes before any SQL is executed."""

from datetime import UTC, datetime, timedelta

import pytest


def test_credential_factory_rejects_untrusted_scope_without_database_access():
    from wso_core.secrets import SecretRejected
    from wso_core.tvt.credentials import CredentialProvider

    with pytest.raises(SecretRejected):
        CredentialProvider(None).with_handle(
            object(), "media.live", datetime.now(UTC) + timedelta(seconds=5)
        )
