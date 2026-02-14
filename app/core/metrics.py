from __future__ import annotations

import statistics
import time
from collections import deque
from threading import Lock
from typing import Deque


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._request_count = 0
        self._error_count = 0
        self._latencies: Deque[float] = deque(maxlen=1000)
        self._status_window: Deque[int] = deque(maxlen=200)
        self._tool_counts: dict[str, int] = {}
        self._tool_latencies: dict[str, Deque[float]] = {}
        self._llm_requests = 0
        self._llm_failures = 0
        self._team_v1_runs = 0
        self._team_v1_partial_runs = 0
        self._team_v1_member_failures: dict[str, int] = {}
        self._team_v1_member_latencies: dict[str, Deque[float]] = {}
        self._team_handoffs = 0
        self._team_shared_state_violations = 0
        self._team_artifacts = 0
        self._agent_errors: dict[str, int] = {}
        self._started_at = time.time()

    def observe_request(self, status: int, latency_ms: float) -> None:
        with self._lock:
            self._request_count += 1
            if status >= 500:
                self._error_count += 1
            self._latencies.append(latency_ms)
            self._status_window.append(status)

    def observe_tool(self, tool_name: str, latency_ms: float) -> None:
        with self._lock:
            self._tool_counts[tool_name] = self._tool_counts.get(tool_name, 0) + 1
            bucket = self._tool_latencies.setdefault(tool_name, deque(maxlen=500))
            bucket.append(latency_ms)

    def observe_llm(self, success: bool) -> None:
        with self._lock:
            self._llm_requests += 1
            if not success:
                self._llm_failures += 1

    def observe_team_v1_run(self, *, partial: bool) -> None:
        with self._lock:
            self._team_v1_runs += 1
            if partial:
                self._team_v1_partial_runs += 1

    def observe_team_v1_member(self, member_id: str, latency_ms: float, *, success: bool) -> None:
        with self._lock:
            bucket = self._team_v1_member_latencies.setdefault(member_id, deque(maxlen=500))
            bucket.append(latency_ms)
            if not success:
                self._team_v1_member_failures[member_id] = (
                    self._team_v1_member_failures.get(member_id, 0) + 1
                )

    def observe_team_handoff(self, count: int = 1) -> None:
        with self._lock:
            self._team_handoffs += max(0, int(count))

    def observe_team_shared_state_violation(self, count: int = 1) -> None:
        with self._lock:
            self._team_shared_state_violations += max(0, int(count))

    def observe_team_artifact(self, count: int = 1) -> None:
        with self._lock:
            self._team_artifacts += max(0, int(count))

    def observe_agent_error(self, error_code: str) -> None:
        code = str(error_code or "UNKNOWN")
        with self._lock:
            self._agent_errors[code] = self._agent_errors.get(code, 0) + 1

    def export_prometheus(self) -> str:
        with self._lock:
            uptime = time.time() - self._started_at
            p95 = _percentile(self._latencies, 95)
            p99 = _percentile(self._latencies, 99)
            error_rate = _error_rate(self._status_window)
            lines = [
                f"inventory_uptime_seconds {uptime:.2f}",
                f"inventory_requests_total {self._request_count}",
                f"inventory_requests_errors_total {self._error_count}",
                f"inventory_request_latency_p95_ms {p95:.2f}",
                f"inventory_request_latency_p99_ms {p99:.2f}",
                f"inventory_request_error_rate {error_rate:.4f}",
                f"inventory_llm_requests_total {self._llm_requests}",
                f"inventory_llm_failures_total {self._llm_failures}",
                f"inventory_team_v1_runs_total {self._team_v1_runs}",
                f"inventory_team_v1_partial_total {self._team_v1_partial_runs}",
                f"inventory_team_handoff_total {self._team_handoffs}",
                f"inventory_team_shared_state_violations_total {self._team_shared_state_violations}",
                f"inventory_team_artifacts_total {self._team_artifacts}",
            ]
            for tool, count in sorted(self._tool_counts.items()):
                tool_p95 = _percentile(self._tool_latencies.get(tool, deque()), 95)
                lines.append(f"inventory_tool_calls_total{{tool=\"{tool}\"}} {count}")
                lines.append(
                    f"inventory_tool_latency_p95_ms{{tool=\"{tool}\"}} {tool_p95:.2f}"
                )
            for member_id, latencies in sorted(self._team_v1_member_latencies.items()):
                member_p95 = _percentile(latencies, 95)
                failures = self._team_v1_member_failures.get(member_id, 0)
                lines.append(
                    f"inventory_team_v1_member_failures_total{{member=\"{member_id}\"}} {failures}"
                )
                lines.append(
                    f"inventory_team_v1_member_latency_p95_ms{{member=\"{member_id}\"}} {member_p95:.2f}"
                )
            for code, count in sorted(self._agent_errors.items()):
                lines.append(f"inventory_agent_errors_total{{code=\"{code}\"}} {count}")
        return "\n".join(lines) + "\n"

    def error_rate_exceeded(self, threshold: float, min_requests: int) -> bool:
        with self._lock:
            if len(self._status_window) < min_requests:
                return False
            return _error_rate(self._status_window) > threshold

    def current_error_rate(self) -> tuple[float, int]:
        with self._lock:
            return _error_rate(self._status_window), len(self._status_window)

    def llm_error_rate_exceeded(self, threshold: float, min_requests: int) -> bool:
        with self._lock:
            if self._llm_requests < min_requests:
                return False
            return (self._llm_failures / self._llm_requests) > threshold

    def current_llm_error_rate(self) -> tuple[float, int]:
        with self._lock:
            if self._llm_requests == 0:
                return 0.0, 0
            return self._llm_failures / self._llm_requests, self._llm_requests


metrics = Metrics()


def _percentile(values: Deque[float], percentile: int) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = int(round((percentile / 100) * (len(ordered) - 1)))
    return float(ordered[index])


def _error_rate(values: Deque[int]) -> float:
    if not values:
        return 0.0
    errors = sum(1 for status in values if status >= 500)
    return errors / len(values)
