"""Launch the configured worker; no synthetic executor or insecure fallback."""

import signal
from threading import Event


def main() -> int:
    stopped = Event()
    server = None
    try:
        from .server import create_server_from_environment

        server = create_server_from_environment()
        signal.signal(signal.SIGINT, lambda *_: stopped.set())
        signal.signal(signal.SIGTERM, lambda *_: stopped.set())
        server.start()
        stopped.wait()
        return 0
    except Exception:  # noqa: BLE001 - redact untrusted executor/config errors
        # No config, TLS, secret or DB exception text reaches process output.
        print("ACCOUNT_WORKER_UNAVAILABLE")
        return 1
    finally:
        if server is not None:
            server.close()


if __name__ == "__main__":
    raise SystemExit(main())
