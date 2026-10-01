"""Fixed domain composition; feature-specific writers must be reviewed separately."""

from typing import Literal

from wso_contracts.models import WireModel
from wso_contracts.tvt.operation import IntentLabel, OperationJobPayload

from wso_core.jobs import DEFAULT_REGISTRY, JobKind, JobRegistry

DOMAIN_KINDS = frozenset(
    {"TVT_ACCOUNT_OPERATION", "TVT_DEVICE_OPERATION", "TYCO_OPERATION"}
)


def compose_registry(base: JobRegistry = DEFAULT_REGISTRY) -> JobRegistry:
    return JobRegistry(
        (
            *base.kinds.values(),
            *(
                JobKind(
                    name,
                    OperationJobPayload,
                    "STORE" if name == "TVT_DEVICE_OPERATION" else "TENANT",
                    permission="STAFF",
                    effect_mode="EXTERNAL_WRITE",
                    max_attempts=1,
                    credential_use=True,
                )
                for name in sorted(DOMAIN_KINDS)
            ),
        )
    )


OPERATION_REGISTRY = compose_registry()


class AuthoritativeReadback(WireModel):
    """Worker transport evidence. Never part of an API request or generic job result."""

    outcome: Literal["SUCCEEDED", "FAILED"]
    reference: IntentLabel
