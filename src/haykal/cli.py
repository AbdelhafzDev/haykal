"""Haykal authoring, runtime, and protocol entry point."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

import uvicorn
import yaml

from haykal.artifacts import ArtifactStore
from haykal.authoring import lint_skill, replay_skill
from haykal.benchmarks import load_manifest, run_benchmark
from haykal.contracts import ExtractionRequest, Selector, SemanticScene, Skill
from haykal.contracts.action import ResolutionPolicy
from haykal.extraction import ExtractionEngine
from haykal.hardening import (
    Diagnostics,
    RedactionPolicy,
    RetentionPolicy,
    RetentionService,
    StateBackup,
    TraceReportExporter,
    build_license_report,
    build_sbom,
    report_digest,
    run_storage_reliability,
)
from haykal.resolver import AmbiguousTarget, TargetResolutionError, TargetResolver
from haykal.runtime import build_runtime
from haykal.skills import PublisherKeyPair, SkillRegistry, TrustPolicy, sign_skill
from haykal.traces import TraceStore
from haykal.transports.http import IdempotencyStore, SessionRegistry, create_app
from haykal.transports.mcp import create_mcp_server
from haykal.workflows import ApprovalService, RunJournal, SkillEngine


def _load(path: str | Path) -> object:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _write(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _scene(args: argparse.Namespace) -> int:
    async def run() -> SemanticScene:
        session = build_runtime(
            serial=args.device,
            session_id=f"cli_{uuid.uuid4().hex}",
            state_directory=args.state_dir,
        )
        await session.open()
        try:
            return await session.observe()
        finally:
            await session.close()

    scene = asyncio.run(run())
    if args.sparse:
        scene = scene.model_copy(
            update={
                "elements": [
                    element
                    for element in scene.elements
                    if element.label or element.text or element.actions
                ]
            }
        )
    if args.json:
        _write(scene.model_dump(mode="json"))
    else:
        print("ID\tROLE\tLABEL/TEXT\tRESOURCE ID\tBOUNDS\tSOURCES")
        for element in scene.elements:
            sources = sorted(
                {source for evidence in element.properties.values() for source in evidence.sources}
            )
            bounds = element.bounds
            print(
                f"{element.id}\t{element.role}\t{element.label or element.text or ''}\t"
                f"{element.resource_id or ''}\t"
                f"{bounds.left},{bounds.top},{bounds.right},{bounds.bottom}\t"
                f"{','.join(sources)}"
            )
    return 0


def _resolve(args: argparse.Namespace) -> int:
    scene = SemanticScene.model_validate(_load(args.scene))
    selector = Selector.model_validate(json.loads(args.selector))
    resolver = TargetResolver()
    try:
        decision = resolver.resolve_selector(
            selector,
            scene,
            action_kind=args.kind,
            policy=ResolutionPolicy(
                minimum_score=args.minimum_score,
                ambiguity_margin=args.ambiguity_margin,
            ),
        )
        _write(
            {
                "accepted": True,
                "target": decision.target.model_dump(mode="json"),
                "ranked": [
                    {
                        "element_id": item.element.id,
                        "score": item.score,
                        "reasons": item.reasons,
                    }
                    for item in decision.ranked
                ],
            }
        )
        return 0
    except AmbiguousTarget as exc:
        _write({"accepted": False, "error": "ambiguous_target", "alternatives": exc.alternatives})
    except TargetResolutionError as exc:
        _write({"accepted": False, "error": type(exc).__name__, "detail": str(exc)})
    return 2


def _extract(args: argparse.Namespace) -> int:
    scene = SemanticScene.model_validate(_load(args.scene))
    request = ExtractionRequest.model_validate(_load(args.request)).model_copy(
        update={"scene_id": scene.scene_id}
    )
    result = ExtractionEngine().extract_scene(request, scene)
    _write(result.model_dump(mode="json"))
    return 0 if result.request_satisfied else 2


def _lint(args: argparse.Namespace) -> int:
    _skill, issues = lint_skill(_load(args.skill))
    _write({"valid": not issues, "issues": [issue.as_dict() for issue in issues]})
    return 0 if not issues else 2


def _replay(args: argparse.Namespace) -> int:
    skill, issues = lint_skill(_load(args.skill))
    if skill is None or issues:
        _write({"passed": False, "issues": [issue.as_dict() for issue in issues]})
        return 2
    result = replay_skill(skill, args.fixtures)
    _write(result)
    return 0 if result["passed"] else 2


def _serve(args: argparse.Namespace) -> int:
    root = Path(args.state_dir)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        loopback = ipaddress.ip_address(args.host).is_loopback
    except ValueError:
        loopback = args.host.casefold() == "localhost"
    if not loopback and not args.allow_remote_behind_tls:
        raise ValueError(
            "remote bind requires --allow-remote-behind-tls and external TLS termination"
        )
    if args.approver_token is not None and args.approver_token == args.token:
        raise ValueError("caller and approver credentials must be different")
    traces = TraceStore(root / "runtime.sqlite3")

    async def factory(session_id: str, serial: str) -> Any:
        return build_runtime(
            serial=serial,
            session_id=session_id,
            state_directory=root,
        )

    registry = SessionRegistry(factory)
    engine = None
    if args.trust_policy:
        trust = _trust_policy(args.trust_policy)
        if not args.approval_secret or not args.approver_token:
            raise ValueError("skill serving requires --approval-secret and --approver-token")
        skills = SkillRegistry(
            root / "runtime.sqlite3",
            root / "skill-objects",
            trust_policy=trust,
        )
        engine = SkillEngine(
            registry=skills,
            journal=RunJournal(root / "runtime.sqlite3"),
            approvals=ApprovalService(
                root / "runtime.sqlite3", signing_secret=args.approval_secret.encode()
            ),
            traces=traces,
            sessions=registry.get,
        )
    app = create_app(
        sessions=registry,
        idempotency=IdempotencyStore(root / "runtime.sqlite3"),
        traces=traces,
        bearer_token=args.token,
        skill_engine=engine,
        approver_token=args.approver_token,
        diagnostics=Diagnostics(root),
        redaction_policy=_redaction_policy(args.redaction_policy),
    )
    uvicorn.run(app, host=args.host, port=args.port)
    return 0


def _trust_policy(path: str | Path) -> TrustPolicy:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    publishers = payload.get("publishers", payload) if isinstance(payload, dict) else None
    if not isinstance(publishers, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in publishers.items()
    ):
        raise ValueError("trust policy must map publisher names to Ed25519 public keys")
    return TrustPolicy(publishers)


def _skill_keygen(args: argparse.Namespace) -> int:
    keys = PublisherKeyPair.generate()
    _write(
        {
            "publisher": args.publisher,
            "private_key": keys.private_key,
            "public_key": keys.public_key,
        }
    )
    return 0


def _skill_sign(args: argparse.Namespace) -> int:
    skill = Skill.model_validate(_load(args.skill))
    raw_key = Path(args.private_key).read_text(encoding="utf-8").strip()
    try:
        key_document = json.loads(raw_key)
    except json.JSONDecodeError:
        private_key = raw_key
    else:
        if not isinstance(key_document, dict) or not isinstance(
            key_document.get("private_key"), str
        ):
            raise ValueError("private key document has no private_key")
        private_key = key_document["private_key"]
    signed = sign_skill(skill, publisher=args.publisher, private_key=private_key)
    Path(args.output).write_text(
        yaml.safe_dump(
            signed.model_dump(mode="json", by_alias=True, exclude_none=True),
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    _write({"output": str(Path(args.output).resolve()), "digest": signed.metadata.content_digest})
    return 0


def _skill_publish(args: argparse.Namespace) -> int:
    root = Path(args.state_dir)
    registry = SkillRegistry(
        root / "runtime.sqlite3",
        root / "skill-objects",
        trust_policy=_trust_policy(args.trust_policy),
    )
    skill = registry.publish(_load(args.skill))
    _write(
        {
            "skill": f"{skill.metadata.name}@{skill.metadata.version}",
            "digest": skill.metadata.content_digest,
        }
    )
    return 0


def _benchmark(args: argparse.Namespace) -> int:
    manifest = load_manifest(args.manifest)
    results = asyncio.run(run_benchmark(manifest, args.out))
    _write({"completed": len(results), "report": str(Path(args.out).resolve())})
    return 0


def _diagnostics(args: argparse.Namespace) -> int:
    report = Diagnostics(args.state_dir).run()
    _write(report.as_dict())
    return 2 if report.status == "unhealthy" else 0


def _redaction_policy(path: str | None) -> RedactionPolicy:
    return RedactionPolicy.model_validate(_load(path)) if path else RedactionPolicy()


def _trace_export(args: argparse.Namespace) -> int:
    root = Path(args.state_dir)
    exported = TraceReportExporter(
        TraceStore(root / "runtime.sqlite3"), ArtifactStore(root / "artifacts")
    ).export(args.trace_id, args.output, _redaction_policy(args.policy))
    _write(
        {
            "trace_id": exported.trace_id,
            "destination": str(exported.destination),
            "events": exported.events,
            "artifacts_exported": exported.artifacts_exported,
            "artifacts_omitted": exported.artifacts_omitted,
            "digest": exported.digest,
        }
    )
    return 0


def _retention(args: argparse.Namespace) -> int:
    root = Path(args.state_dir)
    policy = RetentionPolicy(trace_days=args.trace_days, artifact_days=args.artifact_days)
    result = RetentionService(
        TraceStore(root / "runtime.sqlite3"), ArtifactStore(root / "artifacts")
    ).apply(policy, dry_run=not args.apply)
    _write(result)
    return 0


def _backup(args: argparse.Namespace) -> int:
    _write(StateBackup().create(args.state_dir, args.output))
    return 0


def _restore(args: argparse.Namespace) -> int:
    _write(StateBackup().restore(args.archive, args.destination))
    return 0


def _sbom(args: argparse.Namespace) -> int:
    sbom = build_sbom(args.project_root)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.licenses:
        license_path = Path(args.licenses)
        license_path.parent.mkdir(parents=True, exist_ok=True)
        license_path.write_text(build_license_report(sbom), encoding="utf-8")
    components = sbom.get("components", [])
    _write(
        {
            "sbom": str(output.resolve()),
            "components": len(components) if isinstance(components, list) else 0,
        }
    )
    return 0


def _hardening_run(args: argparse.Namespace) -> int:
    report = asyncio.run(
        run_storage_reliability(
            duration_s=args.duration_s,
            workers=args.workers,
            chaos_every=args.chaos_every,
            state_directory=args.output_state,
        )
    )
    payload = report.as_dict()
    payload["report_digest"] = report_digest(report)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    _write(payload)
    return 0 if report.unexpected_failures == 0 else 2


def _mcp(args: argparse.Namespace) -> int:
    async def run() -> None:
        root = Path(args.state_dir)
        session = build_runtime(
            serial=args.device,
            session_id=args.session_id,
            state_directory=root,
        )
        await session.open()
        try:
            engine = None
            if args.trust_policy:
                if not args.approval_secret:
                    raise ValueError("skill MCP requires --approval-secret")
                database = root / "runtime.sqlite3"
                traces = TraceStore(database)
                engine = SkillEngine(
                    registry=SkillRegistry(
                        database,
                        root / "skill-objects",
                        trust_policy=_trust_policy(args.trust_policy),
                    ),
                    journal=RunJournal(database),
                    approvals=ApprovalService(
                        database,
                        signing_secret=args.approval_secret.encode(),
                    ),
                    traces=traces,
                    sessions=lambda session_id: (
                        session
                        if session_id == args.session_id
                        else (_raise_unknown_session(session_id))
                    ),
                )
            server = create_mcp_server(
                lambda session_id: (
                    session
                    if session_id == args.session_id
                    else (_raise_unknown_session(session_id))
                ),
                skill_engine=engine,
                approval_principal=args.approval_principal,
            )
            await server.run_stdio_async()
        finally:
            await session.close()

    asyncio.run(run())
    return 0


def _raise_unknown_session(session_id: str) -> Any:
    raise LookupError(f"session {session_id!r} was not found")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="haykal")
    parser.add_argument(
        "--state-dir",
        default=os.environ.get("HAYKAL_STATE_DIR", ".haykal"),
        help="durable runtime directory",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    scene = commands.add_parser("scene", help="capture a semantic scene")
    scene.add_argument("--device", required=True)
    scene.add_argument("--json", action="store_true")
    scene.add_argument("--sparse", action="store_true")
    scene.set_defaults(handler=_scene)

    resolve = commands.add_parser("resolve", help="dry-run selector resolution")
    resolve.add_argument("--dry-run", action="store_true", required=True)
    resolve.add_argument("--scene", required=True)
    resolve.add_argument("--selector", required=True)
    resolve.add_argument("--kind", choices=["tap", "input_text", "swipe"], default="tap")
    resolve.add_argument("--minimum-score", type=float, default=0.8)
    resolve.add_argument("--ambiguity-margin", type=float, default=0.1)
    resolve.set_defaults(handler=_resolve)

    extract = commands.add_parser("extract", help="dry-run an extraction request")
    extract.add_argument("--dry-run", action="store_true", required=True)
    extract.add_argument("--scene", required=True)
    extract.add_argument("--request", required=True)
    extract.set_defaults(handler=_extract)

    lint = commands.add_parser("lint", help="validate a skill offline")
    lint.add_argument("skill")
    lint.set_defaults(handler=_lint)

    replay = commands.add_parser("replay", help="replay a skill against scenes")
    replay.add_argument("skill")
    replay.add_argument("--fixtures", required=True)
    replay.set_defaults(handler=_replay)

    benchmark = commands.add_parser("benchmark", help="run the pinned comparative harness")
    benchmark.add_argument("--manifest", required=True)
    benchmark.add_argument("--out", required=True)
    benchmark.set_defaults(handler=_benchmark)

    diagnostics = commands.add_parser("diagnostics", help="inspect runtime health without secrets")
    diagnostics.set_defaults(handler=_diagnostics)

    trace_export = commands.add_parser("trace-export", help="write a redacted static trace report")
    trace_export.add_argument("trace_id")
    trace_export.add_argument("--output", required=True)
    trace_export.add_argument("--policy")
    trace_export.set_defaults(handler=_trace_export)

    retention = commands.add_parser("retention", help="preview or apply trace/artifact retention")
    retention.add_argument("--trace-days", type=int, default=7)
    retention.add_argument("--artifact-days", type=int, default=7)
    retention.add_argument("--apply", action="store_true")
    retention.set_defaults(handler=_retention)

    backup = commands.add_parser("backup", help="create a verified state backup")
    backup.add_argument("--output", required=True)
    backup.set_defaults(handler=_backup)

    restore = commands.add_parser("restore", help="restore a backup into an empty directory")
    restore.add_argument("archive")
    restore.add_argument("--destination", required=True)
    restore.set_defaults(handler=_restore)

    sbom = commands.add_parser("sbom", help="generate CycloneDX and license evidence")
    sbom.add_argument("--project-root", default=".")
    sbom.add_argument("--output", required=True)
    sbom.add_argument("--licenses")
    sbom.set_defaults(handler=_sbom)

    hardening = commands.add_parser(
        "hardening-run", help="run bounded storage load/soak/chaos evidence"
    )
    hardening.add_argument("--duration-s", type=float, required=True)
    hardening.add_argument("--workers", type=int, default=4)
    hardening.add_argument("--chaos-every", type=int, default=37)
    hardening.add_argument("--output")
    hardening.add_argument("--output-state")
    hardening.set_defaults(handler=_hardening_run)

    serve = commands.add_parser("serve", help="serve authenticated HTTP/SSE")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8421)
    serve.add_argument("--token", default=os.environ.get("HAYKAL_API_TOKEN"), required=False)
    serve.add_argument("--approver-token", default=os.environ.get("HAYKAL_APPROVER_TOKEN"))
    serve.add_argument("--approval-secret", default=os.environ.get("HAYKAL_APPROVAL_SECRET"))
    serve.add_argument("--trust-policy", default=os.environ.get("HAYKAL_TRUST_POLICY"))
    serve.add_argument("--redaction-policy", default=os.environ.get("HAYKAL_REDACTION_POLICY"))
    serve.add_argument("--allow-remote-behind-tls", action="store_true")
    serve.set_defaults(handler=_serve)

    keygen = commands.add_parser("skill-keygen", help="generate an Ed25519 publisher key pair")
    keygen.add_argument("--publisher", required=True)
    keygen.set_defaults(handler=_skill_keygen)

    sign = commands.add_parser("skill-sign", help="sign one immutable skill version")
    sign.add_argument("skill")
    sign.add_argument("--publisher", required=True)
    sign.add_argument("--private-key", required=True)
    sign.add_argument("--output", required=True)
    sign.set_defaults(handler=_skill_sign)

    publish = commands.add_parser("skill-publish", help="verify and publish a signed skill")
    publish.add_argument("skill")
    publish.add_argument("--trust-policy", required=True)
    publish.set_defaults(handler=_skill_publish)

    mcp = commands.add_parser("mcp", help="serve MCP v2 over stdio")
    mcp.add_argument("--device", required=True)
    mcp.add_argument("--session-id", default="default")
    mcp.add_argument("--trust-policy", default=os.environ.get("HAYKAL_TRUST_POLICY"))
    mcp.add_argument("--approval-secret", default=os.environ.get("HAYKAL_APPROVAL_SECRET"))
    mcp.add_argument("--approval-principal")
    mcp.set_defaults(handler=_mcp)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "serve" and not args.token:
        print("haykal serve requires --token or HAYKAL_API_TOKEN", file=sys.stderr)
        return 2
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
