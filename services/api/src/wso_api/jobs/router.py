"""Read and cancel persisted jobs; domain APIs own job creation."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel
from wso_contracts.jobs import JobItemView, JobView
from wso_core.jobs import JobFailure, JobService

from wso_api.auth import Service, require_csrf
from wso_api.stores.router import require_tenant

router = APIRouter(prefix="/api/v1/jobs", tags=["jobs"])


class JobItems(BaseModel):
    items: list[JobItemView]
    next_cursor: str | None


@router.get("/{job_id}/items", response_model=JobItems)
def get_items(
    job_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
    cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
) -> JobItems:
    principal = service.authenticate(request)
    try:
        with require_tenant(
            "jobs:read", tenant_id, service=service, principal=principal
        ) as scope:
            items, next_cursor = JobService(scope.session).items(job_id, cursor, limit)
    except JobFailure as exc:
        raise HTTPException(exc.status) from None
    response.headers["Cache-Control"] = "no-store"
    return JobItems(items=items, next_cursor=next_cursor)


@router.get("/{job_id}", response_model=JobView)
def get_job(
    job_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> JobView:
    principal = service.authenticate(request)
    try:
        with require_tenant(
            "jobs:read", tenant_id, service=service, principal=principal
        ) as scope:
            result = JobService(scope.session).get(job_id)
    except JobFailure as exc:
        raise HTTPException(exc.status) from None
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/{job_id}/cancel", response_model=JobView)
def cancel_job(
    job_id: UUID,
    tenant_id: UUID,
    request: Request,
    response: Response,
    service: Service,
) -> JobView:
    principal = service.authenticate(request)
    require_csrf(request, service, principal)
    try:
        with require_tenant(
            "jobs:cancel", tenant_id, service=service, principal=principal
        ) as scope:
            result = JobService(scope.session).cancel(job_id)
    except JobFailure as exc:
        raise HTTPException(exc.status) from None
    response.headers["Cache-Control"] = "no-store"
    return result
