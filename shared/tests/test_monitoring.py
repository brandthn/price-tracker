import json

import pytest

from shared.monitoring import (
    STATUS_FAILED,
    STATUS_SUCCESS,
    PipelineSignalError,
    QualityGateError,
    UpstreamSignalFailedError,
    UpstreamSignalTimeoutError,
    build_worker_signal,
    evaluate_min_threshold,
    raise_if_quality_gates_failed,
    read_signal_from_bucket,
    signal_blob_path,
    wait_for_upstream_signal,
    write_signal_to_bucket,
)


class FakeBlob:
    def __init__(self):
        self.content = None

    def upload_from_string(self, content, content_type=None):
        self.content = content

    def exists(self):
        return self.content is not None

    def download_as_text(self):
        return self.content


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, path):
        if path not in self.blobs:
            self.blobs[path] = FakeBlob()
        return self.blobs[path]


class FakeStorageClient:
    def __init__(self):
        self.buckets = {}

    def bucket(self, name):
        if name not in self.buckets:
            self.buckets[name] = FakeBucket()
        return self.buckets[name]


def test_signal_blob_path():
    assert signal_blob_path("2026-05-12", "worker_ingestion") == \
        "pipeline-signals/date=2026-05-12/worker_ingestion.json"


def test_evaluate_min_threshold_pass():
    result = evaluate_min_threshold("acceptance_rate", 0.8, 0.6)
    assert result["passed"] is True


def test_evaluate_min_threshold_fail():
    result = evaluate_min_threshold("acceptance_rate", 0.5, 0.6)
    assert result["passed"] is False


def test_raise_if_quality_gates_failed_passes_when_all_green():
    gates = [evaluate_min_threshold("acceptance_rate", 0.8, 0.6)]
    raise_if_quality_gates_failed(gates)


def test_raise_if_quality_gates_failed_raises():
    gates = [evaluate_min_threshold("acceptance_rate", 0.4, 0.6)]
    with pytest.raises(QualityGateError):
        raise_if_quality_gates_failed(gates)


def test_build_worker_signal():
    payload = build_worker_signal(
        worker_name="worker_ingestion",
        execution_date="2026-05-12",
        status=STATUS_SUCCESS,
        started_at="2026-05-12T03:00:00+00:00",
        finished_at="2026-05-12T03:05:00+00:00",
        metrics={"accepted_records": 100},
        quality_gates=[],
    )
    assert payload["worker_name"] == "worker_ingestion"
    assert payload["status"] == STATUS_SUCCESS


def test_write_and_read_signal():
    client = FakeStorageClient()
    payload = {"status": STATUS_SUCCESS, "worker_name": "worker_ingestion"}
    write_signal_to_bucket(client, "signals", "2026-05-12", "worker_ingestion", payload)
    loaded = read_signal_from_bucket(client, "signals", "2026-05-12", "worker_ingestion")
    assert loaded["status"] == STATUS_SUCCESS


def test_read_signal_missing_returns_none():
    client = FakeStorageClient()
    loaded = read_signal_from_bucket(client, "signals", "2026-05-12", "worker_ingestion")
    assert loaded is None


def test_wait_for_upstream_signal_success():
    client = FakeStorageClient()
    payload = {"status": STATUS_SUCCESS, "worker_name": "worker_ingestion"}
    write_signal_to_bucket(client, "signals", "2026-05-12", "worker_ingestion", payload)

    loaded = wait_for_upstream_signal(
        storage_client=client,
        bucket_name="signals",
        execution_date="2026-05-12",
        upstream_worker_name="worker_ingestion",
        max_wait_seconds=1,
        poll_interval_seconds=0,
    )
    assert loaded["status"] == STATUS_SUCCESS


def test_wait_for_upstream_signal_failed():
    client = FakeStorageClient()
    payload = {
        "status": STATUS_FAILED,
        "worker_name": "worker_ingestion",
        "error_message": "quality gate failed",
    }
    write_signal_to_bucket(client, "signals", "2026-05-12", "worker_ingestion", payload)

    with pytest.raises(UpstreamSignalFailedError):
        wait_for_upstream_signal(
            storage_client=client,
            bucket_name="signals",
            execution_date="2026-05-12",
            upstream_worker_name="worker_ingestion",
            max_wait_seconds=1,
            poll_interval_seconds=0,
        )


def test_wait_for_upstream_signal_timeout():
    client = FakeStorageClient()
    with pytest.raises(UpstreamSignalTimeoutError):
        wait_for_upstream_signal(
            storage_client=client,
            bucket_name="signals",
            execution_date="2026-05-12",
            upstream_worker_name="worker_ingestion",
            max_wait_seconds=0,
            poll_interval_seconds=0,
        )


def test_wait_for_upstream_signal_unsupported_status():
    client = FakeStorageClient()
    payload = {"status": "UNKNOWN", "worker_name": "worker_ingestion"}
    write_signal_to_bucket(client, "signals", "2026-05-12", "worker_ingestion", payload)

    with pytest.raises(PipelineSignalError):
        wait_for_upstream_signal(
            storage_client=client,
            bucket_name="signals",
            execution_date="2026-05-12",
            upstream_worker_name="worker_ingestion",
            max_wait_seconds=1,
            poll_interval_seconds=0,
        )


def test_signal_payload_is_json_serializable():
    client = FakeStorageClient()
    payload = build_worker_signal(
        worker_name="worker_indices",
        execution_date="2026-05-12",
        status=STATUS_SUCCESS,
        started_at="2026-05-12T05:00:00+00:00",
        finished_at="2026-05-12T05:12:00+00:00",
        metrics={"rows": 10},
        quality_gates=[evaluate_min_threshold("min_obs", 4, 3)],
    )
    write_signal_to_bucket(client, "signals", "2026-05-12", "worker_indices", payload)
    blob = client.bucket("signals").blob("pipeline-signals/date=2026-05-12/worker_indices.json")
    parsed = json.loads(blob.download_as_text())
    assert parsed["worker_name"] == "worker_indices"