"""Publish metadata references. Transport acknowledgment never completes a job."""

from typing import Any

from wso_contracts.jobs import DispatchReference


class CeleryPublisher:
    def __init__(self, app: Any) -> None:
        self.app = app

    def publish_reference(self, reference: DispatchReference, queue: str) -> None:
        self.app.send_task(
            "wso.execute_job",
            kwargs={"reference": reference.model_dump(mode="json")},
            queue=queue,
            serializer="json",
        )

    def __call__(self, reference: DispatchReference, queue: str) -> None:
        self.publish_reference(reference, queue)
