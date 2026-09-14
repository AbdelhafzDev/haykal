"""Self-contained, redacted static trace export."""

from __future__ import annotations

import hashlib
import html
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import UnidentifiedImageError

from haykal.artifacts import ArtifactStore
from haykal.traces import TraceStore

from .privacy import RedactionPolicy, Redactor


@dataclass(frozen=True, slots=True)
class TraceExport:
    trace_id: str
    destination: Path
    events: int
    artifacts_exported: int
    artifacts_omitted: int
    digest: str


class TraceReportExporter:
    def __init__(self, traces: TraceStore, artifacts: ArtifactStore) -> None:
        self.traces = traces
        self.artifacts = artifacts

    def export(
        self,
        trace_id: str,
        destination: str | Path,
        policy: RedactionPolicy,
    ) -> TraceExport:
        events = self.traces.read(trace_id)
        if not events:
            raise LookupError(f"trace {trace_id!r} was not found")
        target = Path(destination).resolve()
        if target.exists() and any(target.iterdir()):
            raise FileExistsError("trace export destination must be empty")
        target.parent.mkdir(parents=True, exist_ok=True)
        redactor = Redactor(policy)
        exported = 0
        omitted = 0
        with tempfile.TemporaryDirectory(prefix=".haykal-trace-", dir=target.parent) as temporary:
            stage = Path(temporary)
            asset_directory = stage / "artifacts"
            rendered_events: list[dict[str, object]] = []
            for event in events:
                payload = redactor.redact_event(event)
                included: list[dict[str, object]] = []
                for digest in event.artifacts:
                    if not policy.include_images:
                        omitted += 1
                        continue
                    try:
                        raw = self.artifacts.get(digest)
                        safe = redactor.redact_image(raw, artifact=digest)
                    except (FileNotFoundError, UnidentifiedImageError) as exc:
                        raise ValueError(f"artifact {digest} cannot be safely exported") from exc
                    safe_digest = hashlib.sha256(safe).hexdigest()
                    asset_directory.mkdir(parents=True, exist_ok=True)
                    filename = f"{safe_digest}.png"
                    (asset_directory / filename).write_bytes(safe)
                    included.append(
                        {
                            "source_digest": digest,
                            "export_digest": f"sha256:{safe_digest}",
                            "path": f"artifacts/{filename}",
                        }
                    )
                    exported += 1
                payload["artifacts"] = included
                rendered_events.append(payload)
            trace_document = {
                "schema_version": "1.0",
                "trace_id": trace_id,
                "redaction_policy": policy.name,
                "events": rendered_events,
            }
            encoded = json.dumps(
                trace_document, ensure_ascii=False, indent=2, sort_keys=True
            ).encode()
            (stage / "trace.json").write_bytes(encoded + b"\n")
            (stage / "index.html").write_text(
                self._html(trace_id, rendered_events, policy.name), encoding="utf-8"
            )
            manifest = {
                "schema_version": "1.0",
                "trace_id": trace_id,
                "trace_sha256": f"sha256:{hashlib.sha256(encoded).hexdigest()}",
                "redaction_policy": policy.name,
                "events": len(events),
                "artifacts_exported": exported,
                "artifacts_omitted": omitted,
            }
            (stage / "manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            target.mkdir(mode=0o700, exist_ok=True)
            for path in stage.iterdir():
                shutil.move(str(path), target / path.name)
        digest = f"sha256:{hashlib.sha256((target / 'manifest.json').read_bytes()).hexdigest()}"
        return TraceExport(trace_id, target, len(events), exported, omitted, digest)

    @staticmethod
    def _html(trace_id: str, events: list[dict[str, object]], policy_name: str) -> str:
        rows: list[str] = []
        for event in events:
            payload = html.escape(
                json.dumps(event.get("payload", {}), ensure_ascii=False, indent=2)
            )
            rows.append(
                "<section><h2>"
                f"{html.escape(str(event.get('sequence')))} · "
                f"{html.escape(str(event.get('event_type')))}</h2>"
                f"<p>{html.escape(str(event.get('occurred_at')))}</p>"
                f"<pre>{payload}</pre></section>"
            )
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Haykal trace</title><style>
body{font:15px system-ui;max-width:960px;margin:2rem auto;padding:0 1rem;color:#17202a}
section{border:1px solid #d5d8dc;border-radius:8px;padding:1rem;margin:1rem 0}
h1,h2{line-height:1.2}h2{font-size:1rem}pre{white-space:pre-wrap;overflow-wrap:anywhere}
</style></head><body>""" + (
            f"<h1>Trace {html.escape(trace_id)}</h1>"
            f"<p>Redaction policy: {html.escape(policy_name)}. This report needs no database.</p>"
            + "".join(rows)
            + "</body></html>\n"
        )
