"""PostgreSQL truth recovered through actual Celery and owned Valkey processes."""

import pytest

pytestmark = pytest.mark.jobs_recovery


@pytest.fixture
def recovery(tmp_path):
    from tests.support.job_broker_harness import JobBrokerHarness

    with JobBrokerHarness(tmp_path) as harness:
        yield harness


def test_producer_crash_after_commit_before_publication(recovery):
    job = recovery.crashed_producer()
    assert recovery.row(job)["state"] == "QUEUED"
    recovery.start_worker()
    recovery.start_dispatcher()
    recovery.assert_one_effect(job)


def test_dispatcher_crash_after_publication_before_ack(recovery):
    job = recovery.enqueue()
    dispatcher = recovery.start_dispatcher(barrier="published")
    recovery.wait_barrier("published")
    recovery.kill_group(dispatcher)
    assert recovery.projection(job)["last_published_at"] is None
    dispatcher = recovery.start_dispatcher()
    recovery.wait_published([job])
    assert recovery.queue_length() >= 2
    duplicates = recovery.queued_task_ids(job)
    assert len(duplicates) >= 2
    recovery.kill_group(dispatcher)
    recovery.start_worker()
    recovery.assert_one_effect(job, require_consumed=True, expected_task_ids=duplicates)


def test_worker_child_crash_before_effect(recovery):
    recovery.crash_before_effect(child_only=True)


def test_worker_process_crash_before_effect(recovery):
    recovery.crash_before_effect(child_only=False)


def test_worker_crash_after_effect_before_ack(recovery):
    job = recovery.enqueue()
    worker = recovery.start_worker(barrier="committed")
    recovery.start_dispatcher()
    recovery.wait_barrier("committed")
    original = recovery.capture_orphan_reservation(job)
    recovery.kill_group(worker)
    recovery.assert_orphan_present(job)
    assert recovery.row(job)["state"] == "SUCCEEDED"
    recovery.assert_http_status(job, "SUCCEEDED")
    recovery.start_worker()
    duplicate = recovery.publish_reference(job)
    recovery.wait_replayed_ack(job)
    recovery.assert_one_effect(
        job, require_consumed=True, expected_task_ids={duplicate, original["task_id"]}
    )


def test_valkey_aof_restart_preserves_delivery(recovery):
    jobs = [recovery.enqueue(), recovery.enqueue()]
    recovery.dispatch_once()
    recovery.wait_published(jobs)
    recovery.wait_aof_synced()
    assert recovery.queue_length() >= 2
    recovery.restart_broker_same_volume()
    assert recovery.queue_length() >= 2
    recovery.start_worker()
    for job in jobs:
        recovery.assert_one_effect(job)


def test_empty_broker_rebuilds_published_and_running_jobs(recovery):
    running = recovery.enqueue(barrier="before-effect")
    worker = recovery.start_worker()
    dispatcher = recovery.start_dispatcher()
    recovery.wait_barrier("before-effect")
    recovery.kill_group(worker)
    recovery.kill_group(dispatcher)
    queued = recovery.enqueue()
    recovery.dispatch_once()
    recovery.wait_published([queued])
    assert recovery.row(queued)["state"] == "QUEUED"
    assert recovery.row(running)["state"] == "RUNNING"
    recovery.replace_broker_empty_preserving_original()
    assert recovery.queue_length() == 0
    recovery.start_worker()
    recovery.start_dispatcher()
    recovery.assert_one_effect(queued)
    recovery.assert_one_effect(running)
    assert recovery.row(running)["lease_generation"] >= 2


def test_external_write_crash_reconciles_without_resubmit(recovery):
    job = recovery.crash_external_write(unreadable=False)
    recovery.start_worker()
    recovery.start_dispatcher()
    recovery.wait_state(job, "SUCCEEDED")
    assert recovery.upstream_count(job) == 1
    assert recovery.upstream_submissions(job) == 1
    assert recovery.upstream_reads(job) >= 1


def test_unresolved_external_write_blocks_resubmit(recovery):
    job = recovery.crash_external_write(unreadable=True)
    recovery.start_worker()
    recovery.start_dispatcher()
    recovery.wait_state(job, "NEEDS_USER_INPUT")
    assert recovery.row(job)["failure_code"] == "UNKNOWN_REMOTE_STATE"
    duplicate = recovery.publish_reference(job)
    original = recovery.wait_replayed_ack(job)
    recovery.wait_queue_empty(expected_task_ids={duplicate, original})
    assert recovery.upstream_count(job) == 1
    assert recovery.upstream_submissions(job) == 1
    assert recovery.upstream_reads(job) >= 1


def test_queue_isolation_prevents_starvation(recovery):
    parked = recovery.enqueue(queue="wso.media", barrier="media-parked")
    media = recovery.start_worker(queue="wso.media")
    recovery.start_dispatcher()
    parked_pid = recovery.wait_barrier("media-parked")["pid"]
    recovery.start_worker(queue="wso.default")
    ordinary = recovery.enqueue()
    recovery.assert_one_effect(ordinary, timeout=15)
    recovery.cancel(parked)
    recovery.release_barrier("media-parked")
    recovery.wait_state(parked, "CANCELLED")
    recovery.wait_barrier("media-parked-closed")
    recovery.assert_process_closed(parked_pid)
    assert recovery.effect_count(parked) == 0
    assert media.poll() is None
