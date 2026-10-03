"""Directory boundary tests; synthetic transport is not SQL authority proof."""

import importlib
from uuid import uuid4

import pytest
from pydantic import ValidationError


def contracts():
    name = "wso_contracts.tvt.directory"
    assert importlib.util.find_spec(name), "strict directory contracts are required"
    return importlib.import_module(name)


def request(name="DeviceListRequest", **changes):
    return getattr(contracts(), name)(
        **({"identity_id": uuid4(), "region": "test", "brand": "brand"} | changes)
    )


def test_source_page_zero_and_opaque_selectors_are_preserved():
    body = request(page_num=0, page_size=0)
    assert body.page_num == 0 and body.page_size == 0
    detail = request("ChannelDetailRequest", sn="opaque:SN", chl_index=7)
    assert detail.sn == "opaque:SN" and detail.chl_index == 7
    assert request("SentSharesRequest").resource_types == ()


@pytest.mark.parametrize(
    "changes",
    [
        {"page_num": True},
        {"page_size": -1},
        {"page_size": 1001},
        {"page_num": "0"},
        {"origin": "https://attacker.invalid"},
        {"token": "private"},
        {"actor_id": str(uuid4())},
        {"generation": 1},
    ],
)
def test_untrusted_authority_and_invalid_page_inputs_are_rejected(changes):
    with pytest.raises(ValidationError):
        request(**changes)


@pytest.mark.parametrize(
    "name,changes",
    [
        ("ChannelListRequest", {"sn_list": []}),
        ("ChannelListRequest", {"sn_list": ["SN", "SN"]}),
        ("ChannelListRequest", {"sn_list": [" SN"]}),
        ("DeviceDetailRequest", {"sn": "SN", "return_chl": 1}),
        ("ChannelDetailRequest", {"sn": "SN", "chl_index": True}),
        ("SentSharesRequest", {"resource_types": [1, 1]}),
        ("ReceivedSharesRequest", {"resource_types": [True]}),
    ],
)
def test_typed_operation_inputs_fail_closed(name, changes):
    with pytest.raises(ValidationError):
        request(name, **changes)


def test_constructed_or_copied_bodies_are_revalidated_and_method_bound():
    c = contracts()
    body = request()
    assert c.checked_request("device_list", body) == body
    with pytest.raises(ValueError):
        c.checked_request("sent_shares", body)
    with pytest.raises(ValueError):
        c.checked_request("device_list", body.model_copy(update={"page_num": True}))


def test_worker_module_exists_for_later_rpc_composition():
    assert importlib.util.find_spec("wso_api.tvt.device_service"), (
        "The worker must compose directory admission, vault, and adapter"
    )


@pytest.fixture
def composed(monkeypatch):
    # Real DirectoryClient/AccountClient/serializers/projections; replace only
    # external PostgreSQL and process I/O. SQL authority is tested separately.
    from types import SimpleNamespace

    import wso_core.tvt.account_client as account
    from wso_api.tvt.session_service import AccountEndpoint
    from wso_core.tvt.account_projection import AccountFailure
    from wso_core.tvt.account_protocol import parse_response
    from wso_core.tvt.token_vault import AccountLease

    name = "wso_api.tvt.device_service"
    assert importlib.util.find_spec(name), "protected worker composition is required"
    service = importlib.import_module(name)
    events = []
    tenant, actor = uuid4(), uuid4()
    state = SimpleNamespace(
        in_transaction=False,
        revoked=False,
        body={
            "total": "1",
            "records": [{"sn": "SN", "maxShareNum": None, "password": "never-export"}],
        },
        code=200,
        hook=lambda: None,
    )

    class Admission:
        def redeem(self, ticket, method, body):
            if ticket != "a" * 64:
                raise AccountFailure("ACCOUNT_DENIED", 404)
            events.append("redeem")
            return SimpleNamespace(
                value="lease",
                tenant_id=tenant,
                actor_id=actor,
                identity_id=body.identity_id,
                region=body.region,
                brand=body.brand,
                generation=1,
            )

        def claim(self, lease):
            events.append("claim")
            return AccountLease(
                "private-lease",
                lease.tenant_id,
                lease.actor_id,
                lease.identity_id,
                lease.region,
                lease.brand,
                1,
                "profile",
            )

        def check(self, lease):
            events.append("check")
            if state.revoked:
                raise AccountFailure("ACCOUNT_DENIED", 404)

        def publish(self, lease):
            self.check(lease)
            events.append("publish")

        def snapshot(self, lease):
            from wso_contracts.tvt.identity import TokenKind, TvtIdentityRef
            from wso_core.tvt.ports import PrivateToken

            state.in_transaction = True
            try:
                self.check(lease)
                return PrivateToken(
                    TvtIdentityRef(
                        tenant_id=lease.tenant_id,
                        actor_user_id=lease.actor_id,
                        identity_id=lease.identity_id,
                    ),
                    TokenKind.USER,
                    "synthetic-user",
                )
            finally:
                state.in_transaction = False

        def dispose(self, lease):
            events.append("dispose")

    class Transport:
        def __init__(self, *args, **kwargs):
            self.deadline_ms = int(kwargs["timeout_seconds"] * 1000)

        def send(self, request):
            import json

            assert not state.in_transaction, (
                "network must execute after vault transaction exits"
            )
            events.append((request.path, json.loads(request.body), self.deadline_ms))
            state.hook()
            return parse_response(
                200,
                json.dumps(
                    {"basic": {"msgcode": state.code}, "data": state.body}
                ).encode(),
            )

        def close(self):
            events.append("close")

    monkeypatch.setattr(account, "ProcessAccountTransport", Transport)
    worker = service.DirectoryWorkerExecutor(
        Admission(),
        (
            AccountEndpoint(
                "test", "brand", "https://directory.example.invalid", "en", "US", "1"
            ),
        ),
    )
    yield worker, state, events
    try:
        worker.close()
    except AccountFailure as error:
        assert error.code == "ACCOUNT_QUARANTINED"


def test_composition_exits_vault_transaction_and_returns_safe_presence(composed):
    worker, _state, events = composed
    body = request()
    view = worker.execute(
        "device_list", "a" * 64, body, deadline_ms=10000, correlation_id="read-1"
    )
    assert view.identity_id == body.identity_id and view.request_id == "read-1"
    assert view.complete is None and view.grants_operations is False
    fields = {f.name: f for f in view.records[0].fields}
    assert fields["sn"].value == "SN"
    assert fields["maxShareNum"].state == "null"
    assert fields["maxShareNum"].source_default == "0"
    assert fields["name"].state == "missing"
    assert "never-export" not in view.model_dump_json()
    wire = next(e for e in events if isinstance(e, tuple))
    assert (
        wire[0] == "/resource/device/list"
        and wire[1]["basic"]["token"] == "synthetic-user"
    )
    assert 0 < wire[2] <= 10000
    assert (
        events.index("claim")
        < events.index(wire)
        < events.index("publish")
        < events.index("dispose")
    )


def test_current_authority_change_during_network_cannot_publish(composed):
    from wso_core.tvt.account_projection import AccountFailure

    worker, state, events = composed
    state.hook = lambda: setattr(state, "revoked", True)
    with pytest.raises(AccountFailure, match="ACCOUNT_DENIED"):
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=10000,
            correlation_id="read-2",
        )
    assert "publish" not in events and "dispose" in events


@pytest.mark.parametrize(
    "deadline,correlation", [(10001, "read"), (True, "read"), (10000, " bad")]
)
def test_invalid_budget_or_request_id_fails_before_admission(
    composed, deadline, correlation
):
    from wso_core.tvt.account_projection import AccountFailure

    worker, _, events = composed
    with pytest.raises(AccountFailure):
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=deadline,
            correlation_id=correlation,
        )
    assert events == []


def test_token_invalid_is_closed_reauthentication_for_exact_identity(composed):
    from wso_core.tvt.account_projection import AccountFailure

    worker, state, events = composed
    state.code = 7000
    body = request()
    with pytest.raises(AccountFailure, match="DIRECTORY_REAUTHENTICATION_REQUIRED"):
        worker.execute(
            "device_list", "a" * 64, body, deadline_ms=10000, correlation_id="read"
        )
    state.code = 200
    with pytest.raises(AccountFailure, match="DIRECTORY_REAUTHENTICATION_REQUIRED"):
        worker.execute(
            "device_list", "a" * 64, body, deadline_ms=10000, correlation_id="read"
        )
    assert len([e for e in events if isinstance(e, tuple)]) == 1


@pytest.mark.parametrize(
    "name,changes,payload,path,data",
    [
        (
            "ChannelListRequest",
            {"sn_list": ["SN"]},
            [{"sn": "SN", "chls": [{"chlIndex": 7, "chlName": "Camera"}]}],
            "/resource/channel/list",
            {"snList": ["SN"]},
        ),
        (
            "DeviceDetailRequest",
            {"sn": "SN", "return_chl": True},
            {"devInfo": {"sn": "SN", "userId": {"password": "discard-me"}}},
            "/resource/device/detail",
            {"sn": "SN", "returnChl": True},
        ),
        (
            "ChannelDetailRequest",
            {"sn": "SN", "chl_index": 7},
            {"sn": "SN", "chlIndex": 7, "ip": "192.0.2.1"},
            "/resource/channel/detail",
            {"sn": "SN", "chlIndex": 7},
        ),
        (
            "SentSharesRequest",
            {},
            {"total": 0, "records": []},
            "/resource/channel/share/to-other/list",
            {"pageNum": 0, "pageSize": 1000},
        ),
        (
            "ReceivedSharesRequest",
            {"resource_types": [1, 99]},
            {
                "total": 1,
                "records": [
                    {"auth": ["talk"], "recipientId": "discard-me", "ownerId": "owner"}
                ],
            },
            "/resource/channel/share/from-other/list",
            {"pageNum": 0, "pageSize": 1000, "resourceTypes": [1, 99]},
        ),
    ],
)
def test_all_six_operations_compose_actual_serializers_and_safe_results(
    composed, name, changes, payload, path, data
):
    worker, state, events = composed
    state.body = payload
    body = request(name, **changes)
    view = worker.execute(
        body.method, "a" * 64, body, deadline_ms=10000, correlation_id="six"
    )
    wire = next(e for e in events if isinstance(e, tuple))
    assert wire[0] == path and wire[1]["data"] == data
    assert "discard-me" not in view.model_dump_json()
    assert view.method == body.method and view.grants_operations is False


def test_inherited_budget_is_not_reset_by_worker_or_vault(composed):
    from wso_core.tvt.token_vault import token_budget

    worker, _, events = composed
    with token_budget(lambda: 37):
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=10000,
            correlation_id="budget",
        )
    wire = next(e for e in events if isinstance(e, tuple))
    assert 0 < wire[2] <= 37


def test_unproved_cleanup_never_returns_success_or_reuses_worker(composed):
    from wso_core.tvt.account_projection import AccountFailure

    worker, _, _ = composed

    def failed(_):
        raise AccountFailure()

    worker._admission.dispose = failed
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=10000,
            correlation_id="cleanup",
        )
    with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=10000,
            correlation_id="closed",
        )


def test_close_cancels_owned_reader_and_late_success_is_discarded(composed):
    import threading

    from wso_core.tvt.account_projection import AccountFailure

    worker, state, events = composed
    reached, release = threading.Event(), threading.Event()

    def paused():
        reached.set()
        assert release.wait(2)

    state.hook = paused
    outcomes = []

    def run():
        try:
            worker.execute(
                "device_list",
                "a" * 64,
                request(),
                deadline_ms=10000,
                correlation_id="close",
            )
        except AccountFailure as error:
            outcomes.append(error.code)

    thread = threading.Thread(target=run)
    thread.start()
    assert reached.wait(1)
    try:
        with pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"):
            worker.close(deadline_ms=20)
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and outcomes == ["ACCOUNT_CANCELLED"]
    assert "publish" not in events
    assert worker._readers, "unproved cleanup retains custody"


def test_canonical_query_is_bounded_before_sql_admission():
    c = contracts()
    body = request(
        "ChannelListRequest", sn_list=[str(i) + "x" * 4000 for i in range(100)]
    )
    with pytest.raises(ValueError):
        c.canonical_request("channel_list", body)


def test_actor_concurrency_limit_denies_fifth_reader_before_transport(composed):
    import threading

    from wso_core.tvt.account_projection import AccountFailure

    worker, state, events = composed
    release = threading.Event()
    reached = threading.Barrier(5)
    outcomes = []

    def paused():
        reached.wait(timeout=3)
        assert release.wait(3)

    state.hook = paused

    def run():
        try:
            outcomes.append(
                worker.execute(
                    "device_list",
                    "a" * 64,
                    request(),
                    deadline_ms=10000,
                    correlation_id="concurrent",
                )
            )
        except AccountFailure as error:
            outcomes.append(error.code)

    threads = [threading.Thread(target=run) for _ in range(4)]
    for thread in threads:
        thread.start()
    reached.wait(timeout=3)
    try:
        with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE"):
            worker.execute(
                "device_list",
                "a" * 64,
                request(),
                deadline_ms=10000,
                correlation_id="fifth",
            )
    finally:
        release.set()
        for thread in threads:
            thread.join(3)
    assert len(outcomes) == 4 and all(
        not isinstance(outcome, str) for outcome in outcomes
    )
    assert len([event for event in events if isinstance(event, tuple)]) == 4


def test_unexpected_private_snapshot_error_is_closed_without_exception_context(
    composed,
):
    from wso_core.tvt.account_projection import AccountFailure

    worker, _, events = composed

    def broken(_):
        raise RuntimeError("private-key-provider-marker")

    worker._admission.snapshot = broken
    with pytest.raises(AccountFailure, match="ACCOUNT_UNAVAILABLE") as failure:
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=10000,
            correlation_id="private-error",
        )
    assert failure.value.__context__ is None
    assert "private-key-provider-marker" not in repr(failure.value)
    assert not any(isinstance(event, tuple) for event in events)


@pytest.mark.parametrize("inherited", [False, True])
def test_close_retains_custody_of_blocked_sql_redemption(composed, inherited):
    import threading

    from wso_core.tvt.account_projection import AccountFailure

    worker, _, events = composed
    reached, release = threading.Event(), threading.Event()
    original = worker._admission.redeem

    def blocked(*args):
        reached.set()
        assert release.wait(2)
        return original(*args)

    worker._admission.redeem = blocked
    outcomes = []

    def run():
        try:
            worker.execute(
                "device_list",
                "a" * 64,
                request(),
                deadline_ms=10000,
                correlation_id="sql-close",
            )
        except AccountFailure as failure:
            outcomes.append(failure.code)

    thread = threading.Thread(target=run)
    thread.start()
    assert reached.wait(1)
    try:
        from wso_core.tvt.token_vault import token_budget

        with (
            token_budget((lambda: 1) if inherited else None),
            pytest.raises(AccountFailure, match="ACCOUNT_QUARANTINED"),
        ):
            worker.close(deadline_ms=5000 if inherited else 20)
    finally:
        release.set()
        thread.join(2)
    assert not thread.is_alive() and outcomes == ["ACCOUNT_QUARANTINED"]
    assert worker._readers
    assert not any(isinstance(event, tuple) for event in events)


def test_close_winning_during_dispose_discards_prepared_view(composed, monkeypatch):
    import threading

    from wso_core.tvt.account_projection import AccountFailure

    worker, _, events = composed
    disposing, release, close_won = (
        threading.Event(),
        threading.Event(),
        threading.Event(),
    )
    original_dispose, original_close = worker._admission.dispose, worker._close_once
    execute_outcomes, close_outcomes = [], []

    def paused_dispose(lease):
        disposing.set()
        assert release.wait(2)
        original_dispose(lease)

    def observed_close(reader):
        original_close(reader)
        close_won.set()

    monkeypatch.setattr(worker._admission, "dispose", paused_dispose)
    monkeypatch.setattr(worker, "_close_once", observed_close)

    def execute():
        try:
            view = worker.execute(
                "device_list",
                "a" * 64,
                request(),
                deadline_ms=10000,
                correlation_id="dispose-close",
            )
            execute_outcomes.append(("success", view.method))
        except AccountFailure as error:
            execute_outcomes.append(("failure", error.code))

    def close():
        try:
            worker.close(deadline_ms=1000)
            close_outcomes.append("settled")
        except AccountFailure as error:
            close_outcomes.append(error.code)

    execution = threading.Thread(target=execute)
    execution.start()
    assert disposing.wait(1)
    with worker._lock:
        reader = next(iter(worker._readers.values()))
    closing = threading.Thread(target=close)
    closing.start()
    try:
        assert close_won.wait(1), "close must own the lifecycle before disposal returns"
        assert not reader.done.is_set()
    finally:
        release.set()
        execution.join(2)
        closing.join(2)
    assert not execution.is_alive() and not closing.is_alive()
    assert execute_outcomes == [("failure", "ACCOUNT_CANCELLED")]
    assert close_outcomes == ["settled"]
    assert reader.done.is_set() and reader.close_done.is_set()
    assert not worker._readers
    assert events.index("publish") < events.index("dispose")


def test_original_deadline_expiring_during_dispose_discards_prepared_view(
    composed, monkeypatch
):
    import wso_api.tvt.device_service as service
    from wso_core.tvt.account_projection import AccountFailure

    worker, _, events = composed
    now = [100.0]
    monkeypatch.setattr(service.time, "monotonic", lambda: now[0])
    original = worker._admission.dispose
    readers = []

    def expired_after_dispose(lease):
        readers.extend(worker._readers.values())
        original(lease)
        now[0] = 101.0

    monkeypatch.setattr(worker._admission, "dispose", expired_after_dispose)
    with pytest.raises(AccountFailure, match="ACCOUNT_DEADLINE_EXCEEDED") as failure:
        worker.execute(
            "device_list",
            "a" * 64,
            request(),
            deadline_ms=1000,
            correlation_id="dispose-deadline",
        )
    assert failure.value.__context__ is None
    assert events.index("publish") < events.index("dispose")
    assert len(readers) == 1 and readers[0].done.is_set()
    assert readers[0].close_done.is_set() and not worker._readers
