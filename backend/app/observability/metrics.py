from prometheus_client import CollectorRegistry, Counter, Histogram


REGISTRY = CollectorRegistry()

HTTP_REQUESTS = Counter(
    "guardian_http_requests",
    "HTTP requests handled by the gateway, grouped by bounded request labels.",
    ("area", "method", "status_class"),
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION = Histogram(
    "guardian_http_request_duration_seconds",
    "End-to-end HTTP request duration in seconds.",
    ("area", "method", "status_class"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10),
    registry=REGISTRY,
)
RATE_LIMIT_REJECTIONS = Counter(
    "guardian_rate_limit_rejections",
    "Requests rejected because a configured rate-limit bucket was empty.",
    registry=REGISTRY,
)
UPSTREAM_ERRORS = Counter(
    "guardian_upstream_errors",
    "Errors encountered while forwarding requests to an upstream service.",
    ("error_type",),
    registry=REGISTRY,
)


def request_area(path: str) -> str:
    """Map arbitrary paths to a small, fixed set of metric labels."""
    if path == "/metrics":
        return "metrics"
    if path == "/health/live" or path == "/health/ready":
        return "health"
    if path == "/admin" or path.startswith("/admin/"):
        return "admin"
    return "gateway"


def normalized_method(method: str) -> str:
    method = method.upper()
    return method if method in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"} else "OTHER"


def record_request(area: str, method: str, status_code: int, duration_seconds: float) -> None:
    labels = (area, normalized_method(method), f"{status_code // 100}xx")
    HTTP_REQUESTS.labels(*labels).inc()
    HTTP_REQUEST_DURATION.labels(*labels).observe(duration_seconds)


def dashboard_summary() -> dict[str, int | float]:
    """Return aggregate values from the same process-local metrics exposed at /metrics."""
    request_metric = next(iter(HTTP_REQUESTS.collect()))
    rejection_metric = next(iter(RATE_LIMIT_REJECTIONS.collect()))
    upstream_metric = next(iter(UPSTREAM_ERRORS.collect()))
    duration_metric = next(iter(HTTP_REQUEST_DURATION.collect()))

    requests = sum(sample.value for sample in request_metric.samples if sample.name.endswith("_total"))
    rejection_count = rejection_metric.samples[0].value
    upstream_samples = upstream_metric.samples
    upstream_error_count = sum(sample.value for sample in upstream_samples if sample.name.endswith("_total"))
    timeout_count = sum(
        sample.value
        for sample in upstream_samples
        if sample.name.endswith("_total") and sample.labels.get("error_type") == "timeout"
    )

    histogram_samples = duration_metric.samples
    duration_sum = sum(sample.value for sample in histogram_samples if sample.name.endswith("_sum"))
    duration_count = sum(sample.value for sample in histogram_samples if sample.name.endswith("_count"))
    average_latency = duration_sum / duration_count if duration_count else 0.0
    target = duration_count * 0.95
    cumulative = 0.0
    p95_latency = 0.0
    if duration_count:
        bucket_counts: dict[float, float] = {}
        for sample in histogram_samples:
            if sample.name.endswith("_bucket") and sample.labels["le"] != "+Inf":
                upper_bound = float(sample.labels["le"])
                bucket_counts[upper_bound] = bucket_counts.get(upper_bound, 0.0) + sample.value
        for upper_bound, count in sorted(bucket_counts.items()):
            cumulative = count
            if cumulative >= target:
                p95_latency = upper_bound
                break
        if cumulative < target:
            p95_latency = 10.0

    return {
        "requests_total": int(requests),
        "rate_limit_rejections_total": int(rejection_count),
        "upstream_errors_total": int(upstream_error_count),
        "upstream_timeouts_total": int(timeout_count),
        "average_latency_seconds": average_latency,
        "p95_latency_seconds": p95_latency,
    }
