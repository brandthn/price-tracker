from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional


STATUS_SUCCESS = "SUCCESS"
STATUS_FAILED = "FAILED"
STATUS_WAITING = "WAITING"


class PipelineSignalError(Exception):
    pass


class UpstreamSignalTimeoutError(PipelineSignalError):
    pass


class UpstreamSignalFailedError(PipelineSignalError):
    pass


class QualityGateError(Exception):
    pass


@dataclass
class QualityGateResult:
    gate_name: str
    passed: bool
    actual_value: float
    threshold_value: float
    comparison: str
    message: str


@dataclass
class WorkerSignal:
    worker_name: str
    execution_date: str
    status: str
    started_at: str
    finished_at: str
    metrics: Dict[str, Any]
    quality_gates: list[Dict[str, Any]]
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_quality_gate_result(
    gate_name: str,
    passed: bool,
    actual_value: float,
    threshold_value: float,
    comparison: str,
    message: str,
) -> Dict[str, Any]:
    return asdict(
        QualityGateResult(
            gate_name=gate_name,
            passed=passed,
            actual_value=actual_value,
            threshold_value=threshold_value,
            comparison=comparison,
            message=message,
        )
    )


def evaluate_min_threshold(
    gate_name: str,
    actual_value: float,
    threshold_value: float,
) -> Dict[str, Any]:
    passed = actual_value >= threshold_value
    return build_quality_gate_result(
        gate_name=gate_name,
        passed=passed,
        actual_value=actual_value,
        threshold_value=threshold_value,
        comparison=">=",
        message=f"{gate_name}: actual={actual_value:.4f}, threshold={threshold_value:.4f}",
    )


def raise_if_quality_gates_failed(quality_gates: list[Dict[str, Any]]) -> None:
    failed = [gate for gate in quality_gates if not gate["passed"]]
    if failed:
        rendered = "; ".join(
            f"{gate['gate_name']} actual={gate['actual_value']:.4f} threshold={gate['threshold_value']:.4f}"
            for gate in failed
        )
        raise QualityGateError(f"Quality gate failure(s): {rendered}")


def build_worker_signal(
    worker_name: str,
    execution_date: str,
    status: str,
    started_at: str,
    finished_at: str,
    metrics: Dict[str, Any],
    quality_gates: list[Dict[str, Any]],
    error_message: Optional[str] = None,
) -> Dict[str, Any]:
    return WorkerSignal(
        worker_name=worker_name,
        execution_date=execution_date,
        status=status,
        started_at=started_at,
        finished_at=finished_at,
        metrics=metrics,
        quality_gates=quality_gates,
        error_message=error_message,
    ).to_dict()


def signal_blob_path(execution_date: str, worker_name: str) -> str:
    return f"pipeline-signals/date={execution_date}/{worker_name}.json"


def write_signal_to_bucket(
    storage_client: Any,
    bucket_name: str,
    execution_date: str,
    worker_name: str,
    signal_payload: Dict[str, Any],
) -> str:
    blob_path = signal_blob_path(execution_date, worker_name)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(
        json.dumps(signal_payload, ensure_ascii=False, indent=2),
        content_type="application/json",
    )
    return blob_path


def read_signal_from_bucket(
    storage_client: Any,
    bucket_name: str,
    execution_date: str,
    worker_name: str,
) -> Optional[Dict[str, Any]]:
    blob_path = signal_blob_path(execution_date, worker_name)
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    if not blob.exists():
        return None
    content = blob.download_as_text()
    return json.loads(content)


def wait_for_upstream_signal(
    storage_client: Any,
    bucket_name: str,
    execution_date: str,
    upstream_worker_name: str,
    max_wait_seconds: int = 600,
    poll_interval_seconds: int = 15,
) -> Dict[str, Any]:
    waited = 0
    while waited <= max_wait_seconds:
        signal = read_signal_from_bucket(
            storage_client=storage_client,
            bucket_name=bucket_name,
            execution_date=execution_date,
            worker_name=upstream_worker_name,
        )
        if signal is not None:
            status = signal.get("status")
            if status == STATUS_SUCCESS:
                return signal
            if status == STATUS_FAILED:
                raise UpstreamSignalFailedError(
                    f"Upstream worker {upstream_worker_name} failed: {signal.get('error_message')}"
                )
            raise PipelineSignalError(
                f"Unsupported upstream status for {upstream_worker_name}: {status}"
            )

        time.sleep(poll_interval_seconds)
        waited += poll_interval_seconds

    raise UpstreamSignalTimeoutError(
        f"Timed out after {max_wait_seconds}s waiting for upstream signal {upstream_worker_name}"
    )