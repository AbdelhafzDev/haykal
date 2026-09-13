"""Evidence-backed deterministic extraction from semantic scenes."""

from __future__ import annotations

import hashlib
import io
import json
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from PIL import Image, UnidentifiedImageError

from haykal.artifacts import ArtifactStore
from haykal.contracts.extraction import (
    ExtractedRecord,
    ExtractionField,
    ExtractionRequest,
    ExtractionResult,
    FieldEvidence,
    RecordAnchor,
    ScrollCheckpoint,
)
from haykal.contracts.scene import SemanticElement, SemanticScene
from haykal.contracts.selector import Selector
from haykal.selectors import SceneIndex, SelectorEvaluator
from haykal.text import normalize, parse_duration, parse_money, parse_number


class MissingRequiredSource(ValueError):
    """A scene lacks evidence explicitly required by the extraction request."""


class ExtractionContextMismatch(ValueError):
    """The extraction request names a different input scene."""


StopReason = Literal["end_of_list", "max_pages", "max_records", "max_ms", "no_new_records"]


@dataclass(frozen=True, slots=True)
class _RecordGroup:
    anchor: SemanticElement | None
    element_ids: set[str]


def _json_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _number(value: Decimal) -> int | float:
    return int(value) if value == value.to_integral_value() else float(value)


class ExtractionEngine:
    def __init__(
        self,
        *,
        artifact_store: ArtifactStore | None = None,
        element_dictionary: dict[str, Selector] | None = None,
    ) -> None:
        self._artifacts = artifact_store
        self._dictionary = element_dictionary or {}

    def extract_scene(
        self,
        request: ExtractionRequest,
        scene: SemanticScene,
        *,
        screenshot_png: bytes | None = None,
        page: int = 0,
    ) -> ExtractionResult:
        if request.scene_id is not None and request.scene_id != scene.scene_id:
            raise ExtractionContextMismatch(
                f"request scene {request.scene_id!r} does not match {scene.scene_id!r}"
            )
        return self.extract_scenes(
            request,
            [scene],
            screenshots={scene.scene_id: screenshot_png} if screenshot_png else {},
            first_page=page,
        )

    def extract_scenes(
        self,
        request: ExtractionRequest,
        scenes: Sequence[SemanticScene],
        *,
        screenshots: dict[str, bytes] | None = None,
        first_page: int = 0,
    ) -> ExtractionResult:
        if not scenes:
            raise ValueError("extraction requires at least one scene")
        started = time.monotonic()
        screenshots = screenshots or {}
        all_records: list[ExtractedRecord] = []
        dropped: list[dict[str, object]] = []
        seen: set[str] = set()
        used_scenes: list[str] = []
        stop_reason: StopReason = "end_of_list"
        source_exhausted = True
        truncated = False
        max_pages = request.scroll.max_pages if request.scroll else 1

        for offset, scene in enumerate(scenes[:max_pages]):
            self._require_sources(request, scene)
            if (
                request.limits.max_ms is not None
                and (time.monotonic() - started) * 1000 >= request.limits.max_ms
            ):
                stop_reason = "max_ms"
                source_exhausted = False
                truncated = True
                break
            used_scenes.append(scene.scene_id)
            groups = self._groups(request, scene)
            page_records: list[ExtractedRecord] = []
            for group_index, group in enumerate(groups):
                record, record_drops = self._bind_group(
                    request,
                    scene,
                    group,
                    screenshot_png=screenshots.get(scene.scene_id),
                    page=first_page + offset,
                    group_index=group_index,
                )
                dropped.extend(record_drops)
                if record is None:
                    continue
                dedupe_signature = self._dedupe_signature(request, record)
                if dedupe_signature in seen:
                    continue
                seen.add(dedupe_signature)
                page_records.append(record)
                all_records.append(record)
                if (
                    request.limits.max_records is not None
                    and len(all_records) >= request.limits.max_records
                ):
                    stop_reason = "max_records"
                    source_exhausted = False
                    truncated = True
                    break
            if stop_reason == "max_records":
                break
            if offset > 0 and not page_records:
                stop_reason = "no_new_records"
                source_exhausted = False
                truncated = True
                break
        else:
            if len(scenes) > max_pages:
                stop_reason = "max_pages"
                source_exhausted = False
                truncated = True

        effective = scenes[max(0, len(used_scenes) - 1)]
        extraction_payload = {
            "request": request.model_dump(mode="json"),
            "scenes": used_scenes,
            "records": [record.model_dump(mode="json") for record in all_records],
        }
        return ExtractionResult(
            extraction_id=f"ext_{_json_digest(extraction_payload).removeprefix('sha256:')[:20]}",
            input_scene_id=scenes[0].scene_id,
            effective_scene_id=effective.scene_id,
            scenes=used_scenes or [scenes[0].scene_id],
            request_satisfied=bool(all_records) and not dropped,
            source_exhausted=source_exhausted,
            truncated=truncated,
            stop_reason=stop_reason,
            records=all_records,
            dropped_records=dropped,
        )

    def _require_sources(self, request: ExtractionRequest, scene: SemanticScene) -> None:
        available = {"accessibility", *scene.quality.fallbacks_used}
        for element in scene.elements:
            for evidence in element.properties.values():
                available.update(source.split(":", 1)[0] for source in evidence.sources)
        missing = set(request.require_sources) - available
        if missing:
            raise MissingRequiredSource(
                f"scene {scene.scene_id!r} lacks required sources: {', '.join(sorted(missing))}"
            )

    def _groups(self, request: ExtractionRequest, scene: SemanticScene) -> list[_RecordGroup]:
        evaluator = SelectorEvaluator(scene, element_dictionary=self._dictionary)
        index = evaluator.index
        grouping = request.group
        if grouping.by == "single":
            if grouping.root is None:
                return [_RecordGroup(None, set(index.by_id))]
            roots = [match.element for match in evaluator.resolve(grouping.root)]
            return [_RecordGroup(root, index.descendants(root)) for root in roots[:1]]
        if grouping.by == "ancestry":
            assert grouping.record is not None
            anchors = [match.element for match in evaluator.resolve(grouping.record)]
            return [_RecordGroup(anchor, index.descendants(anchor)) for anchor in anchors]
        root_ids = self._root_scope(grouping.root, evaluator, index)
        if grouping.by == "rows":
            assert grouping.band_px is not None
            candidates = [
                element
                for element in scene.elements
                if element.id in root_ids
                and element.state.visible
                and element.role not in {"container", "list", "webview"}
            ]
            return self._row_groups(candidates, grouping.band_px)
        parent_ids = (
            {match.element.id for match in evaluator.resolve(grouping.root)}
            if grouping.root is not None
            else {element.id for element in scene.elements if element.parent is None}
        )
        return self._repeat_groups(grouping.record, evaluator, index, root_ids, parent_ids)

    def _root_scope(
        self,
        selector: Selector | None,
        evaluator: SelectorEvaluator,
        index: SceneIndex,
    ) -> set[str]:
        if selector is None:
            return set(index.by_id)
        roots = [match.element for match in evaluator.resolve(selector)]
        return set().union(*(index.descendants(root) for root in roots)) if roots else set()

    def _repeat_groups(
        self,
        record_selector: Selector | None,
        evaluator: SelectorEvaluator,
        index: SceneIndex,
        root_ids: set[str],
        parent_ids: set[str],
    ) -> list[_RecordGroup]:
        if record_selector is not None:
            anchors = [
                match.element for match in evaluator.resolve(record_selector, scope_ids=root_ids)
            ]
        else:
            anchors = [
                element
                for element in index.scene.elements
                if element.id in root_ids and element.parent in parent_ids
            ]
            signatures = Counter(self._shape(element, index) for element in anchors)
            anchors = [
                element for element in anchors if signatures[self._shape(element, index)] >= 2
            ]
        return [_RecordGroup(anchor, index.descendants(anchor)) for anchor in anchors]

    def _shape(self, element: SemanticElement, index: SceneIndex) -> tuple[str, ...]:
        child_roles = sorted(child.role for child in index.children.get(element.id, []))
        return (element.role, *child_roles)

    def _row_groups(self, candidates: list[SemanticElement], band_px: int) -> list[_RecordGroup]:
        rows: list[list[SemanticElement]] = []
        for element in sorted(
            candidates,
            key=lambda item: (
                (item.bounds.top + item.bounds.bottom) / 2,
                item.bounds.left,
                item.id,
            ),
        ):
            center = (element.bounds.top + element.bounds.bottom) / 2
            if not rows:
                rows.append([element])
                continue
            prior_centers = [(item.bounds.top + item.bounds.bottom) / 2 for item in rows[-1]]
            if abs(center - sum(prior_centers) / len(prior_centers)) <= band_px:
                rows[-1].append(element)
            else:
                rows.append([element])
        return [
            _RecordGroup(
                min(row, key=lambda item: (item.bounds.left, item.id)),
                {item.id for item in row},
            )
            for row in rows
        ]

    def _bind_group(
        self,
        request: ExtractionRequest,
        scene: SemanticScene,
        group: _RecordGroup,
        *,
        screenshot_png: bytes | None,
        page: int,
        group_index: int,
    ) -> tuple[ExtractedRecord | None, list[dict[str, object]]]:
        evaluator = SelectorEvaluator(scene, element_dictionary=self._dictionary)
        fields: dict[str, object | None] = {}
        evidence: dict[str, FieldEvidence | None] = {}
        ambiguities: list[dict[str, object]] = []
        missing_required: list[str] = []
        for name, field in request.fields.items():
            matches = evaluator.resolve(field.selector, scope_ids=group.element_ids)
            if len(matches) > 1:
                fields[name] = None
                evidence[name] = None
                ambiguities.append(
                    {
                        "field": name,
                        "reason": "multiple_matches",
                        "candidate_element_ids": [item.element.id for item in matches],
                    }
                )
            elif not matches:
                if field.type == "boolean" and field.default_when_absent is not None:
                    fields[name] = {
                        "value": field.default_when_absent,
                        "raw": None,
                        "defaulted": True,
                    }
                else:
                    fields[name] = None
                evidence[name] = None
            else:
                element = matches[0].element
                try:
                    parsed = self._parse_field(
                        field,
                        element,
                        screenshot_png=screenshot_png,
                    )
                except ValueError as exc:
                    parsed = None
                    ambiguities.append(
                        {
                            "field": name,
                            "reason": "parse_error",
                            "element_id": element.id,
                            "detail": str(exc),
                        }
                    )
                fields[name] = self._protect(parsed, field.privacy)
                evidence[name] = self._field_evidence(scene, element, field)
            if field.required and fields[name] is None:
                missing_required.append(name)

        if missing_required:
            return None, [
                {
                    "group": group_index,
                    "reason": "required_field_missing",
                    "fields": missing_required,
                    "ambiguities": ambiguities,
                }
            ]
        anchor = self._anchor(scene, group.anchor, page=page)
        record_payload = {"fields": fields, "anchor": anchor.model_dump() if anchor else None}
        return (
            ExtractedRecord(
                record_id=f"rec:{_json_digest(record_payload)}",
                fields=fields,
                evidence=evidence,
                anchor=anchor,
                ambiguities=ambiguities,
            ),
            [],
        )

    def _parse_field(
        self,
        field: ExtractionField,
        element: SemanticElement,
        *,
        screenshot_png: bytes | None,
    ) -> object:
        if field.type == "image_crop":
            return self._image_crop(element, screenshot_png)
        raw = element.text or element.label
        if not raw:
            raise ValueError("matched element has no textual value")
        if field.type == "text":
            return {"raw": raw, "normalized": normalize(raw)}
        if field.type == "number":
            number_value = parse_number(raw)
            return {
                "value": _number(number_value.value),
                "raw": raw,
                "digits": number_value.digits,
            }
        if field.type == "money":
            money_value = parse_money(raw)
            return {
                "amount": _number(money_value.amount),
                "currency": money_value.currency,
                "raw": raw,
                "digits": money_value.digits,
            }
        if field.type == "rating":
            rating_value = parse_number(raw)
            scale = field.scale or 5
            if rating_value.value < 0 or rating_value.value > scale:
                raise ValueError(f"rating is outside declared scale {scale}")
            return {
                "value": _number(rating_value.value),
                "scale": scale,
                "raw": raw,
            }
        if field.type == "duration":
            duration_value = parse_duration(raw)
            return {
                "min_minutes": duration_value.min_minutes,
                "max_minutes": duration_value.max_minutes,
                "raw": raw,
                "digits": duration_value.digits,
            }
        return self._parse_boolean(field, raw)

    def _parse_boolean(self, field: ExtractionField, raw: str) -> object:
        normalized = normalize(raw)
        true_tokens = [normalize(value) for value in (field.true_tokens or ["true", "نعم"])]
        false_tokens = [normalize(value) for value in (field.false_tokens or ["false", "لا"])]
        if normalized in true_tokens:
            return {"value": True, "raw": raw, "defaulted": False}
        if normalized in false_tokens:
            return {"value": False, "raw": raw, "defaulted": False}
        raise ValueError("text does not match a declared boolean token")

    def _image_crop(self, element: SemanticElement, screenshot_png: bytes | None) -> object:
        if screenshot_png is None or self._artifacts is None:
            raise ValueError("image_crop requires screenshot bytes and artifact store")
        try:
            with Image.open(io.BytesIO(screenshot_png)) as image:
                image.load()
                if (
                    element.bounds.left < 0
                    or element.bounds.top < 0
                    or element.bounds.right > image.width
                    or element.bounds.bottom > image.height
                ):
                    raise ValueError("element bounds exceed screenshot")
                crop = image.crop(
                    (
                        element.bounds.left,
                        element.bounds.top,
                        element.bounds.right,
                        element.bounds.bottom,
                    )
                )
                output = io.BytesIO()
                crop.save(output, format="PNG")
        except UnidentifiedImageError as exc:
            raise ValueError("screenshot is not a valid image") from exc
        stored = self._artifacts.put(output.getvalue())
        return {"artifact": stored.digest}

    def _field_evidence(
        self,
        scene: SemanticScene,
        element: SemanticElement,
        field: ExtractionField,
    ) -> FieldEvidence:
        property_names = ["bounds"] if field.type == "image_crop" else ["text", "label"]
        sources = sorted(
            {
                source
                for name in property_names
                if name in element.properties
                for source in element.properties[name].sources
            }
        )
        if not sources:
            sources = sorted(
                {source for evidence in element.properties.values() for source in evidence.sources}
            )
        return FieldEvidence(
            scene_id=scene.scene_id,
            element_ids=[element.id],
            sources=sources,
        )

    def _protect(self, value: object | None, privacy: str) -> object | None:
        if value is None or privacy == "public":
            return value
        if privacy == "secret":
            return {"present": True, "digest": _json_digest(value)}
        raw = value.get("raw") if isinstance(value, dict) else str(value)
        visible = str(raw or "")[-2:]
        return {"masked": f"••••{visible}" if visible else "••••"}

    def _anchor(
        self, scene: SemanticScene, element: SemanticElement | None, *, page: int
    ) -> RecordAnchor | None:
        if element is None:
            return None
        fingerprint = _json_digest(element.fingerprint.model_dump(mode="json"))
        return RecordAnchor(
            element_id=element.id,
            scene_revision=scene.revision,
            fingerprint=fingerprint,
            scroll_checkpoint=ScrollCheckpoint(
                container=None,
                page=page,
                visible_signature=scene.digest,
            ),
        )

    def _dedupe_signature(self, request: ExtractionRequest, record: ExtractedRecord) -> str:
        if not request.dedupe_by:
            return record.record_id
        return _json_digest({name: record.fields.get(name) for name in request.dedupe_by})
