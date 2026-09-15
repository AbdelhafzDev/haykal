from __future__ import annotations

from pathlib import Path

import pytest

from haykal.hardening import report_digest, run_storage_reliability


@pytest.mark.asyncio
async def test_bounded_reliability_harness_reports_expected_chaos(tmp_path: Path) -> None:
    report = await run_storage_reliability(
        duration_s=0.05,
        workers=2,
        chaos_every=3,
        state_directory=tmp_path,
    )

    assert report.operations > 0
    assert report.injected_interruptions > 0
    assert report.detected_faults == report.injected_interruptions
    assert report.unexpected_failures == 0
    assert report.artifact_integrity_failures == 0
    assert report.samples
    assert report.peak_open_descriptors > 0
    assert report.peak_rss_bytes <= report.limits["max_rss_bytes"]
    assert report.state_bytes <= report.limits["max_state_bytes"]
    assert report.peak_open_descriptors <= report.limits["max_open_descriptors"]
    assert report.p95_ms <= report.limits["max_p95_ms"]
    assert report.thirty_minute_gate_eligible is False
    assert report.eight_hour_gate_eligible is False
    assert report_digest(report).startswith("sha256:")


@pytest.mark.asyncio
async def test_reliability_harness_rejects_unbounded_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        await run_storage_reliability(duration_s=0)
