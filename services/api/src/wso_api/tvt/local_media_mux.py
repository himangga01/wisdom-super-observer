"""Application scoped mux issuance/readback, with ticket-only worker dispatch."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from wso_contracts.tvt.local_media import LocalLiveRequest, LocalLiveResponse
from wso_contracts.tvt.local_media_mux import (
    LocalFocusRequest,
    LocalFocusResponse,
    LocalFocusSettleRequest,
    LocalFocusView,
    LocalWallResponse,
    LocalWallView,
)
from wso_contracts.tvt.media import LocalMediaOwnerRef
from wso_core.tvt.local_admission import _bound, _boundary, _token
from wso_core.tvt.local_media_admission import LocalMediaReader
from wso_core.tvt.local_service import LocalDeviceFailure
from wso_tvt_bridge.local_media_mux_rpc import LocalMuxAck, checked_mux_json

from wso_api.auth import SESSION_COOKIE, token_digest
from wso_api.stores.router import require_tenant
from wso_api.tvt.account import Current
from wso_api.tvt.local_media import LocalMediaRoute, call_owned, checked_view


def validate_mode_request(shared: bool, request: LocalLiveRequest) -> None:
    if type(shared) is not bool or type(request) is not LocalLiveRequest:
        raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
    if shared:
        if request.wall_id is None or (
            request.stream == "main" and request.focus_ref_id is None
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
    elif request.wall_id is not None or request.focus_ref_id is not None:
        raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)


def focus_deadline(now: datetime, session_expires: datetime) -> datetime:
    if now.tzinfo is None or session_expires.tzinfo is None or session_expires <= now:
        raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    return min(now + timedelta(seconds=20), session_expires)


def public_wall(
    row: Any, tenant_id: UUID, wall_id: UUID | None = None
) -> LocalWallView:
    try:
        if type(row) is not dict or set(row) != {"id", "state", "expires_at"}:
            raise ValueError
        view = LocalWallView.model_validate(row | {"tenant_id": tenant_id})
        if not view.id.int or (wall_id is not None and view.id != wall_id):
            raise ValueError
        return view
    except (ValueError, TypeError):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502) from None


class LocalMuxTicketIssuer:
    """Call only frozen app functions inside an authenticated tenant transaction."""

    def __init__(self, session: Session, remaining: Callable[[], int]) -> None:
        self._session, self._remaining = session, remaining

    def _sql(self, function: str, arguments: str, values: dict[str, Any]) -> Any:
        _bound(self._session, self._remaining)
        row: Any = self._session.execute(
            text(f"SELECT public.wso_tvt_local_media_{function}({arguments})"), values
        ).scalar_one()
        _bound(self._session, self._remaining)
        if row is None:
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return row

    @staticmethod
    def _scope(session_digest: str, *identities: UUID) -> None:
        if not _token(session_digest) or any(
            type(identity) is not UUID or not identity.int for identity in identities
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)

    def _ticket(self, function: str, arguments: str, values: dict[str, Any]) -> str:
        value = self._sql(function, arguments, values)
        if not _token(value):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        return str(value)

    @_boundary
    def issue_shared(
        self, session_digest: str, connection_id: UUID, request: LocalLiveRequest
    ) -> str:
        self._scope(session_digest, connection_id)
        validate_mode_request(True, request)
        return self._ticket(
            "shared_issue",
            ":s,:c,:store,:device,:channel,:gen,:rev,:stream,:ttl,:wall,:focus",
            {
                "s": session_digest,
                "c": connection_id,
                "store": request.store_id,
                "device": request.device_id,
                "channel": request.channel_id,
                "gen": request.expected_generation,
                "rev": request.inventory_revision,
                "stream": request.stream,
                "ttl": 30,
                "wall": request.wall_id,
                "focus": request.focus_ref_id,
            },
        )

    @_boundary
    def issue_wall_control(
        self, session_digest: str, wall_id: UUID, purpose: Literal["heartbeat", "stop"]
    ) -> str:
        self._scope(session_digest, wall_id)
        if purpose not in {"heartbeat", "stop"}:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        return self._ticket(
            "wall_control_issue",
            ":s,:wall,:purpose",
            {
                "s": session_digest,
                "wall": wall_id,
                "purpose": {"heartbeat": "WALL_HEARTBEAT", "stop": "WALL_STOP"}[
                    purpose
                ],
            },
        )

    @_boundary
    def issue_focus(
        self,
        session_digest: str,
        lease_id: UUID,
        request: LocalFocusRequest,
        deadline_at: datetime,
    ) -> str:
        self._scope(session_digest, lease_id)
        if (
            type(request) is not LocalFocusRequest
            or type(deadline_at) is not datetime
            or deadline_at.tzinfo is None
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        return self._ticket(
            "focus_issue",
            ":s,:lease,:direction,:deadline",
            {
                "s": session_digest,
                "lease": lease_id,
                "direction": request.direction,
                "deadline": deadline_at,
            },
        )

    @_boundary
    def issue_focus_settle(
        self,
        session_digest: str,
        wall_id: UUID,
        reference_id: UUID,
        request: LocalFocusSettleRequest,
    ) -> str:
        self._scope(session_digest, wall_id, reference_id)
        if type(request) is not LocalFocusSettleRequest:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
        row = self.read_focus(session_digest, reference_id)
        if UUID(row["wall_id"]) != wall_id or row["state"] != "PENDING":
            raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
        return self._ticket(
            "focus_settle_issue",
            ":s,:focus,:outcome",
            {"s": session_digest, "focus": reference_id, "outcome": request.outcome},
        )

    @_boundary
    def issue_wall(self, session_digest: str) -> Any:
        self._scope(session_digest)
        return self._sql("wall_issue", ":s,:ttl", {"s": session_digest, "ttl": 30})

    @_boundary
    def read_wall(self, session_digest: str, wall_id: UUID) -> Any:
        self._scope(session_digest, wall_id)
        return self._sql(
            "wall_view",
            ":s,:wall",
            {"s": session_digest, "wall": wall_id},
        )

    @_boundary
    def read_focus(self, session_digest: str, reference_id: UUID) -> dict[str, Any]:
        self._scope(session_digest, reference_id)
        row = self._sql(
            "focus_read", ":s,:focus", {"s": session_digest, "focus": reference_id}
        )
        if (
            type(row) is not dict
            or set(row)
            != {"id", "wall_id", "lease_id", "direction", "state", "expires_at"}
            or UUID(row["id"]) != reference_id
        ):
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        return dict(row)


def _public_focus(
    issuer: LocalMuxTicketIssuer,
    digest: str,
    reference: UUID,
    tenant: UUID,
    actor: UUID,
    *,
    wall: UUID | None = None,
    source: UUID | None = None,
    direction: str | None = None,
) -> LocalFocusView:
    row = issuer.read_focus(digest, reference)
    try:
        states = {
            "PENDING": "PENDING",
            "MAIN_ACTIVE": "ACTIVE",
            "ATTACHED": "CLOSED",
            "CONSUMED": "CLOSED",
            "CANCELLED": "CLOSED",
            "FAILED": "CLOSED",
            "EXPIRED": "CLOSED",
        }
        lease_id = UUID(row["lease_id"])
        lease = LocalMediaReader(issuer._session, issuer._remaining).get(
            digest, lease_id
        )
        checked_view(
            LocalLiveResponse(lease=lease, request_id="scope"), tenant, actor, lease_id
        )
        assert isinstance(lease.owner, LocalMediaOwnerRef)
        view = LocalFocusView.model_validate(
            row
            | {
                "state": states[row["state"]],
                "connection_id": lease.owner.connection_id,
                "channel_id": lease.channel,
            }
        )
        if (
            (wall is not None and view.wall_id != wall)
            or (source is not None and view.lease_id != source)
            or (direction is not None and view.direction != direction)
        ):
            raise ValueError
        return view
    except (ValueError, TypeError, KeyError, AttributeError):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502) from None


def dispatch_mux(
    request: Request,
    tenant_id: UUID,
    current: tuple[Any, Any],
    action: str,
    *,
    wall_id: UUID | None = None,
    lease_id: UUID | None = None,
    reference_id: UUID | None = None,
    body: Any = None,
) -> LocalWallResponse | LocalFocusResponse:
    if getattr(request.app.state, "tvt_local_media_shared_enabled", False) is not True:
        raise LocalDeviceFailure("LOCAL_DEVICE_DENIED", 404)
    service, principal = current
    digest = token_digest(request.cookies[SESSION_COOKIE])
    budget = request.state.local_media_budget
    worker = getattr(request.app.state, "tvt_local_media_mux_worker", None)
    with require_tenant(
        "connections:write", tenant_id, service=service, principal=principal
    ) as scope:
        issuer = LocalMuxTicketIssuer(scope.session, budget.remaining_ms)
        if action == "wall_issue":
            wall = public_wall(issuer.issue_wall(digest), tenant_id)
            return LocalWallResponse(wall=wall, request_id=request.state.request_id)
        if action == "wall_state" and wall_id is not None:
            wall = public_wall(issuer.read_wall(digest, wall_id), tenant_id, wall_id)
            return LocalWallResponse(wall=wall, request_id=request.state.request_id)
        if worker is None:
            raise LocalDeviceFailure()
        if action in {"wall_heartbeat", "stop_wall"} and wall_id is not None:
            ticket = issuer.issue_wall_control(
                digest, wall_id, "heartbeat" if action == "wall_heartbeat" else "stop"
            )
        elif action == "focus_reserve" and lease_id is not None:
            source_view = LocalMediaReader(scope.session, budget.remaining_ms).get(
                digest, lease_id
            )
            checked_view(
                LocalLiveResponse(
                    lease=source_view, request_id=request.state.request_id
                ),
                tenant_id,
                principal.user_id,
                lease_id,
            )
            ticket = issuer.issue_focus(
                digest,
                lease_id,
                body,
                focus_deadline(datetime.now(UTC), principal.expires_at),
            )
        elif (
            action == "focus_settle"
            and wall_id is not None
            and reference_id is not None
        ):
            ticket = issuer.issue_focus_settle(digest, wall_id, reference_id, body)
        else:
            raise LocalDeviceFailure("LOCAL_DEVICE_INPUT_INVALID", 422)
    # SQL app transaction has committed before any remote/native operation.
    value = getattr(worker, action)(
        ticket,
        deadline_ms=budget.remaining_ms(),
        correlation_id=request.state.request_id,
        cancel=budget.cancel,
    )
    budget.remaining_ms()
    result = checked_mux_json(
        value.model_dump_json(exclude_none=True).encode(),
        action,
        request.state.request_id,
    )
    if type(result) is not LocalMuxAck:
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    if (
        action in {"wall_heartbeat", "stop_wall"}
        and result.id != wall_id
        or action == "focus_settle"
        and result.id != reference_id
    ):
        raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
    with require_tenant(
        "connections:write", tenant_id, service=service, principal=principal
    ) as scope:
        issuer = LocalMuxTicketIssuer(scope.session, budget.remaining_ms)
        if action in {"wall_heartbeat", "stop_wall"}:
            wall = public_wall(issuer.read_wall(digest, result.id), tenant_id, wall_id)
            return LocalWallResponse(wall=wall, request_id=request.state.request_id)
        view = _public_focus(
            issuer,
            digest,
            result.id,
            tenant_id,
            principal.user_id,
            wall=wall_id,
            source=lease_id,
            direction=body.direction if action == "focus_reserve" else None,
        )
        if action == "focus_settle" and view.state != "CLOSED":
            raise LocalDeviceFailure("LOCAL_DEVICE_PROTOCOL_INVALID", 502)
        return LocalFocusResponse(reference=view, request_id=request.state.request_id)


router = APIRouter(
    prefix="/api/v1/tvt", tags=["tvt-local-mux"], route_class=LocalMediaRoute
)


@router.post("/live-walls", response_model=LocalWallResponse)
async def wall_issue(request: Request, tenant_id: UUID, current: Current) -> Any:
    return await call_owned(
        request,
        dispatch_fn=dispatch_mux,
        tenant_id=tenant_id,
        current=current,
        action="wall_issue",
    )


@router.get("/live-walls/{wall_id}", response_model=LocalWallResponse)
def wall_state(
    request: Request, tenant_id: UUID, wall_id: UUID, current: Current
) -> LocalWallResponse | LocalFocusResponse:
    return dispatch_mux(request, tenant_id, current, "wall_state", wall_id=wall_id)


@router.post("/live-walls/{wall_id}/heartbeat", response_model=LocalWallResponse)
async def wall_heartbeat(
    request: Request, tenant_id: UUID, wall_id: UUID, current: Current
) -> Any:
    return await call_owned(
        request,
        dispatch_fn=dispatch_mux,
        tenant_id=tenant_id,
        wall_id=wall_id,
        current=current,
        action="wall_heartbeat",
    )


@router.post("/live-walls/{wall_id}/stop", response_model=LocalWallResponse)
async def wall_stop(
    request: Request, tenant_id: UUID, wall_id: UUID, current: Current
) -> Any:
    return await call_owned(
        request,
        dispatch_fn=dispatch_mux,
        tenant_id=tenant_id,
        wall_id=wall_id,
        current=current,
        action="stop_wall",
    )


@router.post(
    "/live-sessions/{lease_id}/focus-reservations", response_model=LocalFocusResponse
)
async def focus_reserve(
    request: Request,
    tenant_id: UUID,
    lease_id: UUID,
    body: LocalFocusRequest,
    current: Current,
) -> Any:
    return await call_owned(
        request,
        dispatch_fn=dispatch_mux,
        tenant_id=tenant_id,
        lease_id=lease_id,
        body=body,
        current=current,
        action="focus_reserve",
    )


@router.post(
    "/live-walls/{wall_id}/focus-reservations/{reference_id}/settle",
    response_model=LocalFocusResponse,
)
async def focus_settle(
    request: Request,
    tenant_id: UUID,
    wall_id: UUID,
    reference_id: UUID,
    body: LocalFocusSettleRequest,
    current: Current,
) -> Any:
    return await call_owned(
        request,
        dispatch_fn=dispatch_mux,
        tenant_id=tenant_id,
        wall_id=wall_id,
        reference_id=reference_id,
        body=body,
        current=current,
        action="focus_settle",
    )
