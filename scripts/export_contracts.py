"""Export stable JSON schemas and OpenAPI for generated clients."""

import argparse
import json
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter
from wso_api.main import create_app
from wso_contracts.jobs import (
    DispatchReference,
    ImportJobPayload,
    JobItemView,
    JobView,
    RegistrationJobPayload,
)
from wso_contracts.models import (
    EventEnvelope,
    IncidentSummary,
    JobScope,
    Money,
    ProductCandidate,
    SignedMoney,
    StoreScope,
    TenantScope,
    VariantOption,
)

MODELS = (
    DispatchReference,
    EventEnvelope,
    ImportJobPayload,
    IncidentSummary,
    JobItemView,
    JobView,
    Money,
    ProductCandidate,
    RegistrationJobPayload,
    SignedMoney,
    StoreScope,
    TenantScope,
    VariantOption,
)


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "packages/contracts/generated",
    )
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    for model in MODELS:
        write_json(args.out_dir / f"{model.__name__}.json", model.model_json_schema())
    write_json(args.out_dir / "JobScope.json", TypeAdapter(JobScope).json_schema())
    write_json(args.out_dir / "openapi.json", create_app().openapi())
    print(f"Exported {len(MODELS) + 2} contract documents")


if __name__ == "__main__":
    main()
