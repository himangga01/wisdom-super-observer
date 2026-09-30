"""Fixed fixture subprocess entrypoints, never loaded by a production environment."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def barrier(directory, owner, event, opaque_id):
    """An injected callback may carry only one approved event and opaque UUID."""
    from uuid import UUID

    from tests.support.asset_provider import private_json

    events = {
        "intent-committed",
        "multipart-created",
        "parts-written",
        "s3-completed",
        "validation-finalize",
        "first-byte",
        "delete-ack",
    }
    if event not in events:
        raise ValueError("unknown asset fixture barrier")
    opaque_id = str(UUID(str(opaque_id)))
    fields = Path(f"/proc/{os.getpid()}/stat").read_text().rsplit(")", 1)[1].split()
    path = Path(directory) / f"{event}-{opaque_id}.json"
    private_json(
        path,
        {
            "pid": os.getpid(),
            "group": os.getpgrp(),
            "start_time": int(fields[19]),
            "owner": owner,
            "event": event,
            "opaque_id": opaque_id,
        },
    )
    release = path.with_suffix(".release")
    deadline = time.monotonic() + 60
    while not release.exists():
        if time.monotonic() >= deadline:
            raise RuntimeError("asset fixture barrier was not released")
        time.sleep(0.025)


def create_fixture_api():
    from wso_api.auth import configure_auth
    from wso_api.main import create_app

    from tests.support.job_process import auth_service

    # Real AuthService/OIDCVerifier plus restricted PostgreSQL session/identity/app
    # roles. This fixed test factory adds no fake asset endpoint.
    app = create_app()
    service, engines = auth_service()
    configure_auth(app, service)
    app.state.asset_fixture_engines = engines
    return app


def main():
    if sys.platform != "linux" or os.environ.get("CI") != "true":
        raise RuntimeError("asset subprocess requires actual owned Linux CI")
    if len(sys.argv) != 3 or sys.argv[1] != "api":
        raise ValueError("fixed asset subprocess mode required")
    import uvicorn

    uvicorn.run(
        create_fixture_api(),
        host="127.0.0.1",
        port=int(sys.argv[2]),
        access_log=False,
        log_level="warning",
    )


if __name__ == "__main__":
    main()
