"""Offline fixture safety tests are not S3/HTTP lifecycle acceptance."""

import json
import subprocess
import tarfile
from io import BytesIO
from unittest.mock import Mock

import pytest

from tests.support.asset_harness import AssetHarness
from tests.support.asset_provider import LABEL, AssetProvider


def volume_archive(
    *, uid=65532, gid=65532, mode=0o700, name="data", kind=tarfile.DIRTYPE, extra=False
):
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.uid, info.gid, info.mode, info.type = uid, gid, mode, kind
        archive.addfile(info)
        if extra:
            archive.addfile(tarfile.TarInfo("DO_NOT_EMIT_extra_private_name"))
    return output.getvalue()


@pytest.mark.parametrize(
    "case,stage",
    [
        ("uid", "entry_identity"),
        ("mode", "entry_identity"),
        ("name", "entry_name"),
        ("type", "entry_type"),
        ("extra", "entry_count"),
        ("malformed", "archive_parse"),
        ("nonzero", "command"),
        ("timeout", "command"),
    ],
)
def test_volume_failure_exposes_only_bounded_structured_metadata(
    tmp_path, monkeypatch, case, stage
):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(
        provider, "docker_invocation", lambda *_: (["fixed-local-docker"], {})
    )
    payload = volume_archive(
        uid=0 if case == "uid" else 65532,
        mode=0o755 if case == "mode" else 0o700,
        name="DO_NOT_EMIT_private_name" if case == "name" else "data",
        kind=tarfile.REGTYPE if case == "type" else tarfile.DIRTYPE,
        extra=case == "extra",
    )
    if case == "malformed":
        payload = b"DO_NOT_EMIT_private_body"
    runner = Mock(
        return_value=subprocess.CompletedProcess(
            [], 0, stdout=payload, stderr=b"DO_NOT_EMIT_private_stderr"
        )
    )
    if case == "nonzero":
        runner.side_effect = subprocess.CalledProcessError(
            2,
            ["DO_NOT_EMIT_private_path"],
            output=b"DO_NOT_EMIT_private_body",
            stderr=b"DO_NOT_EMIT_private_stderr",
        )
    elif case == "timeout":
        runner.side_effect = subprocess.TimeoutExpired(
            ["DO_NOT_EMIT_private_path"], 15, output=b"DO_NOT_EMIT_private_body"
        )
    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", runner)
    with pytest.raises(RuntimeError, match="nonroot data volume") as failure:
        provider.verify_data_volume()
    message = str(failure.value)
    assert "DO_NOT_EMIT" not in message
    assert len(message) < 512
    assert ": {" in message
    diagnostic = json.loads(message.partition(": ")[2])
    assert set(diagnostic) == {
        "stage",
        "returncode",
        "archive_bytes",
        "entry_count",
        "directory",
        "type",
        "uid",
        "gid",
        "mode",
    }
    assert diagnostic["stage"] == stage
    assert diagnostic["returncode"] == (
        2 if case == "nonzero" else None if case == "timeout" else 0
    )
    if case in {"malformed", "nonzero", "timeout"}:
        assert diagnostic["entry_count"] is None
        assert diagnostic["directory"] == "unobserved"
        assert diagnostic["uid"] is None
    else:
        assert diagnostic["entry_count"] == (2 if case == "extra" else 1)
        assert diagnostic["directory"] == (
            "unexpected" if case == "name" else "expected_data"
        )
        assert diagnostic["uid"] == (0 if case == "uid" else 65532)
        assert diagnostic["gid"] == 65532
        assert diagnostic["mode"] == (0o755 if case == "mode" else 0o700)
        assert diagnostic["type"] == ("regular" if case == "type" else "directory")
    assert provider.receipt is None


def test_exact_nonroot_volume_archive_still_passes(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(
        provider, "docker_invocation", lambda *_: (["fixed-local-docker"], {})
    )
    monkeypatch.setattr(
        "tests.support.asset_provider.subprocess.run",
        Mock(
            return_value=subprocess.CompletedProcess(
                [], 0, stdout=volume_archive(), stderr=b""
            )
        ),
    )
    provider.verify_data_volume()
    assert provider.receipt is None


def test_scratch_build_copies_private_data_as_child_with_explicit_metadata(
    tmp_path, monkeypatch
):
    from tests.support import asset_provider

    provider = AssetProvider(tmp_path)
    monkeypatch.setattr(asset_provider, "require_linux_ci", lambda: None)
    monkeypatch.setattr(asset_provider, "LocalDocker", lambda *_: object())
    binary_bytes = b"offline fixture bytes, never an executable"

    def artifact(directory, name):
        target = directory / name
        target.write_bytes(binary_bytes)
        return target

    monkeypatch.setattr(asset_provider, "download_artifact", artifact)
    monkeypatch.setattr(asset_provider, "verify_binary_version", lambda *_: None)

    class BuildBoundaryReached(Exception):
        pass

    def stop_at_build(*arguments):
        assert arguments[:2] == ("build", "--network=none")
        raise BuildBoundaryReached

    monkeypatch.setattr(provider, "docker", stop_at_build)
    with pytest.raises(BuildBoundaryReached):
        provider.start()
    context = provider.work / "image"
    instructions = (context / "Dockerfile").read_text().splitlines()
    copies = [line.split() for line in instructions if line.startswith("COPY ")]
    assert len(copies) == 2
    data_copy = next(line for line in copies if "--chown=65532:65532" in line)
    assert data_copy[1:3] == ["--chown=65532:65532", "--chmod=0700"]
    # COPY directory contents into an existing root. /data must be a child,
    # not the destination root whose newly created metadata BuildKit preserves.
    assert data_copy[-1] == "/"
    data_root = context / data_copy[-2]
    assert data_root.is_dir() and not data_root.is_symlink()
    assert [entry.name for entry in data_root.iterdir()] == ["data"]
    data = data_root / "data"
    assert data.is_dir() and not data.is_symlink() and not list(data.iterdir())
    assert (context / "minio").read_bytes() == binary_bytes
    assert "USER 65532:65532" in instructions
    assert 'VOLUME ["/data"]' in instructions
    assert 'ENTRYPOINT ["/minio"]' in instructions
    assert not any(line.startswith(("RUN ", "ADD ")) for line in instructions)
    assert provider.receipt is None


@pytest.mark.parametrize("command", ["build", "create", "inspect", "remove", "copy"])
def test_all_docker_commands_pin_local_socket_and_private_config_despite_saved_context(
    tmp_path, monkeypatch, command
):
    from tests.support import asset_minio

    ambient = tmp_path / "ambient"
    ambient.mkdir()
    (ambient / "config.json").write_text('{"currentContext":"remote-deployment"}')
    alternate = tmp_path / "alternate"
    alternate.mkdir()
    (alternate / "config.json").write_text('{"currentContext":"another-remote"}')
    monkeypatch.setenv("DOCKER_CONFIG", str(ambient))
    monkeypatch.setenv("HOME", str(ambient))
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.delenv("DOCKER_CONTEXT", raising=False)
    monkeypatch.setenv("BUILDKIT_HOST", "tcp://remote-builder.invalid:1234")
    monkeypatch.setattr(asset_minio, "require_linux_ci", lambda: None)
    monkeypatch.setattr(
        asset_minio, "local_socket_identity", lambda: (1, 2, 0), raising=False
    )
    # Windows has no POSIX chmod/uid; only this OS boundary is emulated.
    monkeypatch.setattr(
        asset_minio, "verify_private_path", lambda *_: None, raising=False
    )
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / "owned"
    provider.work.mkdir()
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        if "cp" in arguments:
            import io
            import tarfile

            data = io.BytesIO()
            with tarfile.open(fileobj=data, mode="w") as archive:
                info = tarfile.TarInfo("data")
                info.type, info.uid, info.gid, info.mode = (
                    tarfile.DIRTYPE,
                    65532,
                    65532,
                    0o700,
                )
                archive.addfile(info)
            return subprocess.CompletedProcess(
                arguments, 0, stdout=data.getvalue(), stderr=b""
            )
        return subprocess.CompletedProcess(arguments, 0, stdout="[]", stderr="")

    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", run)
    if command == "copy":
        provider.verify_data_volume()
    elif command == "remove":
        provider.docker("container", "rm", "owned-resource")
    else:
        provider.docker(command, "owned-resource")
    monkeypatch.setenv("DOCKER_CONFIG", str(alternate))
    monkeypatch.setenv("DOCKER_CONTEXT", "remote-after-initialization")
    provider.docker("inspect", "owned-resource")
    for arguments, options in calls:
        assert arguments[:5] == [
            "docker",
            "--config",
            str(provider.work / "docker-config"),
            "--host",
            "unix:///var/run/docker.sock",
        ]
        assert options["env"]["DOCKER_CONFIG"] == str(provider.work / "docker-config")
        assert options["env"]["HOME"] == str(provider.work)
        assert not (
            {"DOCKER_HOST", "DOCKER_CONTEXT", "BUILDKIT_HOST"} & options["env"].keys()
        )
    assert json.loads((provider.work / "docker-config/config.json").read_text()) == {}


def test_changed_local_socket_refuses_docker_before_subprocess(tmp_path, monkeypatch):
    from tests.support import asset_minio

    monkeypatch.setattr(asset_minio, "require_linux_ci", lambda: None)
    monkeypatch.setattr(
        asset_minio, "verify_private_path", lambda *_: None, raising=False
    )
    observations = iter([(1, 2, 0), (1, 2, 0), (1, 99, 0)])
    monkeypatch.setattr(
        asset_minio, "local_socket_identity", lambda: next(observations), raising=False
    )
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / "owned"
    provider.work.mkdir()
    runner = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout="[]", stderr="")
    )
    monkeypatch.setattr("tests.support.asset_provider.subprocess.run", runner)
    provider.docker("inspect", "owned")
    with pytest.raises(RuntimeError, match="local Docker socket identity changed"):
        provider.docker("remove", "owned")
    assert runner.call_count == 1


def owned_container_state(provider):
    provider.image = "sha256:" + "a" * 64
    return {
        "Name": "/" + provider.container,
        "Image": provider.image,
        "Config": {
            "Image": provider.image,
            "User": "65532:65532",
            "Entrypoint": ["/minio"],
            "Cmd": [
                "server",
                "/data",
                "--address",
                ":9000",
                "--console-address",
                ":9001",
                "--quiet",
            ],
            "Env": [
                "MINIO_ROOT_USER=" + provider.credentials["bootstrap"][0],
                "MINIO_ROOT_PASSWORD=" + provider.credentials["bootstrap"][1],
                "MINIO_BROWSER=off",
                "MINIO_UPDATE=off",
            ],
        },
        "NetworkSettings": {"Networks": {provider.network: {}}},
        "Mounts": [
            {
                "Destination": "/data",
                "Type": "volume",
                "Name": provider.volume,
                "RW": True,
            }
        ],
        "HostConfig": {
            "NetworkMode": provider.network,
            "Privileged": False,
            "ReadonlyRootfs": True,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Memory": 2147483648,
            "NanoCpus": 2000000000,
            "PidsLimit": 128,
            "LogConfig": {"Type": "none"},
            "PortBindings": {"9000/tcp": [{"HostIp": "127.0.0.1", "HostPort": ""}]},
            "Tmpfs": {
                "/tmp": "rw,noexec,nosuid,nodev,size=64m,mode=0700,uid=65532,gid=65532"
            },
        },
    }


@pytest.mark.parametrize("mutation", ["public-port", "tmpfs-size", "tmpfs-mode"])
def test_container_mapping_refuses_public_port_or_unbounded_tmpfs(
    tmp_path, monkeypatch, mutation
):
    provider = AssetProvider(tmp_path)
    state = owned_container_state(provider)
    monkeypatch.setattr(
        provider,
        "inspect",
        lambda kind, _: (
            {"Name": provider.volume}
            if kind == "volume"
            else {"Internal": True}
            if kind == "network"
            else {}
        ),
    )
    monkeypatch.setattr(provider, "assert_image", lambda _: None)
    if mutation == "public-port":
        state["HostConfig"]["PortBindings"]["9000/tcp"][0]["HostIp"] = "0.0.0.0"
    elif mutation == "tmpfs-size":
        state["HostConfig"]["Tmpfs"]["/tmp"] = "rw,size=8g"
    else:
        state["HostConfig"]["Tmpfs"]["/tmp"] = "rw,size=64m,mode=0777"
    with pytest.raises(RuntimeError, match="mapping mismatch"):
        provider.assert_container_mapping(state)


def test_unowned_provider_resource_refuses_cleanup(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.created.append(("volume", provider.volume))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps([{"Name": provider.volume, "Labels": {LABEL: "foreign"}}])

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert not any("rm" in arguments for arguments in calls)


def test_unowned_local_image_refuses_cleanup(tmp_path, monkeypatch):
    provider = AssetProvider(tmp_path)
    provider.created.append(("image", provider.image_tag))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps([{"Config": {"Labels": {LABEL: "foreign"}}}])

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert not any("rm" in arguments for arguments in calls)


def test_client_close_failure_does_not_prevent_owned_resource_teardown(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    client = Mock()
    client.close.side_effect = RuntimeError("transport close failed")
    provider.clients["bootstrap"] = client
    provider.created.append(("volume", provider.volume))
    calls = []

    def docker(*arguments):
        calls.append(arguments)
        return json.dumps(
            [{"Name": provider.volume, "Labels": {LABEL: provider.owner}}]
        )

    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert ("volume", "rm", provider.volume) in calls


def test_private_directory_foreign_owner_refuses_deletion(tmp_path):
    provider = AssetProvider(tmp_path)
    provider.work = tmp_path / ("minio-" + provider.owner)
    provider.work.mkdir()
    (provider.work / "owner.json").write_text(json.dumps({"owner": "foreign"}))
    sentinel = provider.work / "keep"
    sentinel.write_text("owned by another task")
    with pytest.raises(RuntimeError, match="cleanup failed"):
        provider.close()
    assert sentinel.exists()


def test_provider_start_refuses_windows_before_download_or_docker(
    tmp_path, monkeypatch
):
    provider = AssetProvider(tmp_path)
    monkeypatch.setattr("tests.support.asset_minio.sys.platform", "win32")
    docker = Mock()
    monkeypatch.setattr(provider, "docker", docker)
    with pytest.raises(RuntimeError, match="Linux amd64 CI"):
        provider.start()
    assert not docker.called and provider.work is None


def test_selected_asset_fixture_refuses_windows_without_skip(tmp_path, monkeypatch):
    monkeypatch.setattr("tests.support.asset_harness.sys.platform", "win32")
    with pytest.raises(pytest.fail.Exception, match="actual owned Linux"):
        AssetHarness(tmp_path).__enter__()


def test_foreign_process_identity_refuses_signal(tmp_path, monkeypatch):
    harness = AssetHarness(tmp_path)

    class Process:
        pid = 123

        def poll(self):
            return None

    harness.process = Process()
    harness.start_time = 5
    monkeypatch.setattr(
        "tests.support.asset_harness.os.pidfd_open", lambda *_: 999, raising=False
    )
    monkeypatch.setattr("tests.support.asset_harness.os.close", lambda *_: None)
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: None,
        raising=False,
    )
    monkeypatch.setattr(harness, "process_identity", lambda _: ("S", 456, 5))
    monkeypatch.setattr(
        "pathlib.Path.read_bytes", lambda _: b"WSO_ASSET_FIXTURE_OWNER=foreign"
    )
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()


def process_fixture(tmp_path, monkeypatch):
    """Emulate a pinned subprocess handle; never call an operating-system signal."""
    harness = AssetHarness(tmp_path)
    events = []
    pinned = {"value": False}

    class Process:
        pid = 123

        def poll(self):
            return None

        def wait(self, timeout):
            events.append("wait")

    class Log:
        def close(self):
            events.append("log-close")

    harness.process = Process()
    harness.log = Log()
    harness.start_time = 5
    harness.command = [
        "fixture-python",
        "-m",
        "tests.support.asset_process",
        "api",
        "1234",
    ]

    def pin(*_):
        pinned["value"] = True
        events.append("pin")
        return 999

    def identity(_):
        events.append("identity")
        return "S", 123, 5

    def read(path):
        if path.name == "cmdline":
            return b"\0".join(part.encode() for part in harness.command) + b"\0"
        return f"WSO_ASSET_FIXTURE_OWNER={harness.owner}".encode()

    monkeypatch.setattr(harness, "process_identity", identity)
    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    monkeypatch.setattr("tests.support.asset_harness.os.pidfd_open", pin, raising=False)
    monkeypatch.setattr(
        "tests.support.asset_harness.os.close", lambda *_: events.append("close")
    )
    monkeypatch.setattr(
        "tests.support.asset_harness.signal.pidfd_send_signal",
        lambda *_: events.append("signal"),
        raising=False,
    )
    monkeypatch.setattr("tests.support.asset_harness.signal.SIGKILL", 9, raising=False)
    return harness, events, pinned


def test_owned_process_pinned_before_signal_with_descriptor_closed(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    harness.stop_api()
    assert events.index("pin") < events.index("identity") < events.index("signal")
    assert events.index("signal") < events.index("close") < events.index("wait")
    assert harness.process is None


def test_identity_change_during_pidfd_open_denies_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, pinned = process_fixture(tmp_path, monkeypatch)

    def changed(_):
        events.append("identity")
        return "S", 123, 999 if pinned["value"] else 5

    monkeypatch.setattr(harness, "process_identity", changed)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_command_change_refuses_signal_and_closes_handle(tmp_path, monkeypatch):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)
    original = __import__("pathlib").Path.read_bytes

    def read(path):
        return b"unrelated-process\0" if path.name == "cmdline" else original(path)

    monkeypatch.setattr("pathlib.Path.read_bytes", read)
    with pytest.raises(ValueError, match="ownership mismatch"):
        harness.stop_api()
    assert "signal" not in events and "close" in events


def test_process_disappearing_after_pin_refuses_signal_and_closes_handle(
    tmp_path, monkeypatch
):
    harness, events, _ = process_fixture(tmp_path, monkeypatch)

    def vanished(_):
        raise FileNotFoundError("process exited")

    monkeypatch.setattr(harness, "process_identity", vanished)
    with pytest.raises(ValueError, match="identity unavailable"):
        harness.stop_api()
    assert "signal" not in events and "close" in events
