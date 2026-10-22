from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from haykal.production import (
    EvidenceGate,
    GateStatus,
    ModelArtifact,
    PerceptionContract,
    ProductionGateName,
    ScoreGateName,
    evaluate_production_manifest,
    load_production_manifest,
    production_manifest_digest,
)

MANIFEST = Path("config/production-acceptance.json")
EVIDENCE_SHA = "sha256:" + "a" * 64
REVISION = "b" * 40


def test_baseline_manifest_is_valid_but_fail_closed() -> None:
    manifest = load_production_manifest(MANIFEST)
    evaluation = evaluate_production_manifest(manifest)

    assert evaluation.production_eligible is False
    assert evaluation.score_95_evidence_complete is False
    assert evaluation.blocking_gates == (
        "omniparser_fallback",
        "eight_hour_soak",
        "regional_apps",
        "deployment_drill",
        "security_review",
    )
    assert evaluation.pending_score_gates == ("non_core_author", "external_benchmark")
    assert evaluation.manifest_sha256 == production_manifest_digest(manifest)


def test_passed_gate_requires_immutable_evidence() -> None:
    with pytest.raises(ValidationError, match="requires evidence_sha256"):
        EvidenceGate(status=GateStatus.PASSED, summary="unsupported claim")


def test_pending_gate_cannot_claim_evidence() -> None:
    with pytest.raises(ValidationError, match="cannot claim acceptance evidence"):
        EvidenceGate(
            status=GateStatus.PENDING,
            summary="not run",
            evidence_sha256=EVIDENCE_SHA,
            evidence_uri="reports/not-run.json",
        )


def test_omniparser_requires_mit_detector_and_captioner() -> None:
    detector = ModelArtifact(
        name="icon_detect_v3",
        role="detector",
        upstream_revision=REVISION,
        sha256=EVIDENCE_SHA,
        license="MIT",
    )
    with pytest.raises(ValidationError, match="one detector and one captioner"):
        PerceptionContract(
            primary="accessibility",
            fallback="omniparser_v2",
            model_artifacts=(detector,),
            offline_cache_required=True,
            network_download_allowed=False,
        )


def test_all_evidence_gates_derive_production_and_score_decisions() -> None:
    manifest = load_production_manifest(MANIFEST)
    passed = EvidenceGate(
        status=GateStatus.PASSED,
        summary="independent evidence passed",
        evidence_sha256=EVIDENCE_SHA,
        evidence_uri="reports/evidence.json",
    )
    detector = ModelArtifact(
        name="icon_detect_v3",
        role="detector",
        upstream_revision=REVISION,
        sha256=EVIDENCE_SHA,
        license="MIT",
    )
    captioner = ModelArtifact(
        name="icon_caption",
        role="captioner",
        upstream_revision=REVISION,
        sha256="sha256:" + "c" * 64,
        license="MIT",
    )
    complete = manifest.model_copy(
        update={
            "perception": PerceptionContract(
                primary="accessibility",
                fallback="omniparser_v2",
                model_artifacts=(detector, captioner),
                offline_cache_required=True,
                network_download_allowed=False,
            ),
            "production_gates": dict.fromkeys(ProductionGateName, passed),
            "score_gates": dict.fromkeys(ScoreGateName, passed),
        }
    )

    evaluation = evaluate_production_manifest(complete)
    assert evaluation.production_eligible is True
    assert evaluation.score_95_evidence_complete is True
    assert evaluation.blocking_gates == ()
    assert evaluation.pending_score_gates == ()
