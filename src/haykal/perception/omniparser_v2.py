"""Pinned, offline-only OmniParser V2 inference adapter.

The YOLOv9 decoding follows Microsoft's MIT-licensed OmniParser implementation,
but this module intentionally excludes the older Ultralytics detector and the
upstream demo/server dependency graph.
"""

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from importlib.resources import as_file, files
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal, Protocol, cast
from urllib.parse import quote
from urllib.request import urlopen

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .adapters import AdapterIdentity, OmniParserAdapter, Runner

Sha256 = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
GitRevision = Annotated[str, Field(pattern=r"^[0-9a-f]{40}$")]
ModelGroup = Literal["detector", "captioner", "processor"]


class OmniParserCacheError(RuntimeError):
    """The offline model cache is missing, corrupt, or unsafe."""


class OptionalDependencyMissing(RuntimeError):
    """The explicitly requested OmniParser runtime extra is unavailable."""


class PinnedModelFile(BaseModel):
    """One immutable file in the offline cache."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    group: ModelGroup
    repository: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
    revision: GitRevision
    remote_path: Annotated[str, Field(min_length=1)]
    local_path: Annotated[str, Field(min_length=1)]
    sha256: Sha256
    size: Annotated[int, Field(gt=0)]
    license: Literal["MIT", "Apache-2.0"]

    @model_validator(mode="after")
    def reject_unsafe_paths(self) -> PinnedModelFile:
        for raw in (self.remote_path, self.local_path):
            path = PurePosixPath(raw)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("model paths must be relative and cannot traverse")
        return self


class OmniParserModelManifest(BaseModel):
    """All executable model and processor inputs required at runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"]
    name: Literal["microsoft/OmniParser-v2.0"]
    upstream_revision: GitRevision
    source_repository: Literal["https://github.com/microsoft/OmniParser"]
    source_commit: GitRevision
    files: tuple[PinnedModelFile, ...]

    @model_validator(mode="after")
    def require_complete_unique_groups(self) -> OmniParserModelManifest:
        local_paths = [item.local_path for item in self.files]
        if len(local_paths) != len(set(local_paths)):
            raise ValueError("model cache local paths must be unique")
        groups = {item.group for item in self.files}
        if groups != {"detector", "captioner", "processor"}:
            raise ValueError("model cache requires detector, captioner, and processor groups")
        if any(
            item.group != "processor" and item.revision != self.upstream_revision
            for item in self.files
        ):
            raise ValueError("OmniParser model files must use the declared upstream revision")
        if any(
            item.group in {"detector", "captioner"} and item.license != "MIT" for item in self.files
        ):
            raise ValueError("OmniParser detector and captioner files must be MIT")
        return self


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _safe_cache_path(root: Path, relative: str) -> Path:
    path = root.joinpath(*PurePosixPath(relative).parts)
    try:
        path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise OmniParserCacheError(f"model cache path escapes cache root: {relative}") from exc
    current = root
    for part in PurePosixPath(relative).parts:
        current /= part
        if current.is_symlink():
            raise OmniParserCacheError(f"model cache path contains a symlink: {relative}")
    return path


def load_model_manifest(path: str | Path) -> OmniParserModelManifest:
    """Read the strict model-cache manifest."""

    return OmniParserModelManifest.model_validate_json(Path(path).read_text(encoding="utf-8"))


def packaged_model_manifest() -> OmniParserModelManifest:
    """Load the immutable manifest bundled into the installed wheel."""

    resource = files("haykal.perception").joinpath("data/omniparser-v2.json")
    if not resource.is_file():
        development = Path(__file__).resolve().parents[3] / "config/models/omniparser-v2.json"
        if development.is_file():
            return load_model_manifest(development)
        raise OmniParserCacheError("the packaged OmniParser model manifest is missing")
    with as_file(resource) as path:
        return load_model_manifest(path)


def model_manifest_digest(manifest: OmniParserModelManifest) -> str:
    """Address the complete executable model input set."""

    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def model_group_digest(manifest: OmniParserModelManifest, group: ModelGroup) -> str:
    """Address one logical detector, captioner, or processor bundle."""

    payload = [
        {
            "local_path": item.local_path,
            "sha256": item.sha256,
            "size": item.size,
        }
        for item in manifest.files
        if item.group == group
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def verify_model_cache(
    cache_root: str | Path,
    manifest: OmniParserModelManifest,
) -> tuple[Path, ...]:
    """Verify every cached byte before importing or constructing a model."""

    root = Path(cache_root).expanduser().resolve()
    verified: list[Path] = []
    for item in manifest.files:
        path = _safe_cache_path(root, item.local_path)
        if not path.is_file():
            raise OmniParserCacheError(f"model cache file is absent or unsafe: {item.local_path}")
        if path.stat().st_size != item.size:
            raise OmniParserCacheError(f"model cache size mismatch: {item.local_path}")
        if _sha256_file(path) != item.sha256:
            raise OmniParserCacheError(f"model cache digest mismatch: {item.local_path}")
        verified.append(path)
    return tuple(verified)


Download = Callable[[str, Path, int], None]


def _download(url: str, output: Path, expected_size: int) -> None:
    written = 0
    with urlopen(url, timeout=60) as response, output.open("xb") as stream:
        while chunk := response.read(1024 * 1024):
            written += len(chunk)
            if written > expected_size:
                raise OmniParserCacheError("model download exceeded its pinned size")
            stream.write(chunk)
    if written != expected_size:
        raise OmniParserCacheError("model download did not match its pinned size")


def prepare_model_cache(
    cache_root: str | Path,
    manifest: OmniParserModelManifest,
    *,
    downloader: Download = _download,
) -> tuple[Path, ...]:
    """Populate an offline cache from immutable revisions, then verify it."""

    root = Path(cache_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for item in manifest.files:
        output = _safe_cache_path(root, item.local_path)
        if (
            output.is_file()
            and output.stat().st_size == item.size
            and _sha256_file(output) == item.sha256
        ):
            continue
        output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = output.with_name(f".{output.name}.partial")
        if temporary.exists():
            temporary.unlink()
        remote = quote(item.remote_path, safe="/")
        url = f"https://huggingface.co/{item.repository}/resolve/{item.revision}/{remote}"
        try:
            downloader(url, temporary, item.size)
            if _sha256_file(temporary) != item.sha256:
                raise OmniParserCacheError(f"download digest mismatch: {item.local_path}")
            os.replace(temporary, output)
            output.chmod(0o600)
        finally:
            if temporary.exists():
                temporary.unlink()
    return verify_model_cache(root, manifest)


class InferenceEngine(Protocol):
    """Small injection seam for deterministic tests and the optional ML stack."""

    def infer(self, screenshot: bytes) -> Sequence[Mapping[str, object]]: ...


EngineFactory = Callable[[Path, OmniParserModelManifest, str], InferenceEngine]


class OmniParserV2Runner:
    """Lazy, process-local runner that never downloads at inference time."""

    def __init__(
        self,
        *,
        cache_root: str | Path,
        manifest: OmniParserModelManifest,
        device: str = "cuda",
        engine_factory: EngineFactory | None = None,
    ) -> None:
        self._cache_root = Path(cache_root).expanduser().resolve()
        self._manifest = manifest
        self._device = device
        self._factory = engine_factory or _TorchOmniParserEngine
        self._engine: InferenceEngine | None = None
        self._lock = threading.Lock()
        verify_model_cache(self._cache_root, manifest)

    @property
    def identity(self) -> AdapterIdentity:
        return AdapterIdentity(
            name="omniparser-v2",
            version=self._manifest.upstream_revision,
            model_digest=model_manifest_digest(self._manifest),
            weights_digest=model_group_digest(self._manifest, "detector"),
        )

    def __call__(self, screenshot: bytes) -> Sequence[Mapping[str, object]]:
        engine = self._engine
        if engine is None:
            with self._lock:
                engine = self._engine
                if engine is None:
                    engine = self._factory(self._cache_root, self._manifest, self._device)
                    self._engine = engine
        return engine.infer(screenshot)


def build_omniparser_v2_adapter(
    *,
    cache_root: str | Path,
    manifest_path: str | Path | None = None,
    device: str = "cuda",
    timeout_s: float = 30.0,
    engine_factory: EngineFactory | None = None,
) -> OmniParserAdapter:
    """Build the ordinary Haykal vision adapter from pinned local inputs."""

    manifest = (
        load_model_manifest(manifest_path)
        if manifest_path is not None
        else packaged_model_manifest()
    )
    runner = OmniParserV2Runner(
        cache_root=cache_root,
        manifest=manifest,
        device=device,
        engine_factory=engine_factory,
    )
    return OmniParserAdapter(
        identity=runner.identity,
        runner=cast(Runner, runner),
        timeout_s=timeout_s,
    )


class _TorchOmniParserEngine:
    """Minimal detector/caption path with no upstream demo dependencies."""

    _strides = (8, 16, 32)

    def __init__(self, root: Path, manifest: OmniParserModelManifest, device: str) -> None:
        del manifest
        try:
            self._np = importlib.import_module("numpy")
            self._torch = importlib.import_module("torch")
            self._ops = importlib.import_module("torchvision.ops")
            transformers = importlib.import_module("transformers")
        except ImportError as exc:
            raise OptionalDependencyMissing(
                "OmniParser requires the haykal-runtime[omniparser] extra"
            ) from exc
        if device == "cuda" and not self._torch.cuda.is_available():
            raise OptionalDependencyMissing("CUDA was requested but is unavailable")
        self._device = self._torch.device(device)
        detector_path = root / "icon_detect_v3/model.pt"
        caption_path = root / "icon_caption"
        processor_path = root / "florence_processor"
        self._detector = self._torch.jit.load(str(detector_path), map_location=self._device).eval()
        config = transformers.AutoConfig.from_pretrained(
            processor_path,
            trust_remote_code=True,
            local_files_only=True,
        )
        dtype = self._torch.float16 if self._device.type == "cuda" else self._torch.float32
        self._captioner = transformers.AutoModelForCausalLM.from_pretrained(
            caption_path,
            config=config,
            torch_dtype=dtype,
            trust_remote_code=True,
            local_files_only=True,
        ).to(self._device)
        self._processor = transformers.AutoProcessor.from_pretrained(
            processor_path,
            trust_remote_code=True,
            local_files_only=True,
        )

    def infer(self, screenshot: bytes) -> Sequence[Mapping[str, object]]:
        with Image.open(io.BytesIO(screenshot)) as source:
            image = source.convert("RGB")
        boxes, scores = self._detect(image)
        captions = self._caption(image, boxes)
        return [
            {
                "id": str(index),
                "bounds": [round(value) for value in box],
                "role": "button",
                "label": caption or None,
                "confidence": round(float(score), 6),
            }
            for index, (box, score, caption) in enumerate(zip(boxes, scores, captions, strict=True))
        ]

    def _detect(self, image: Image.Image) -> tuple[list[list[float]], list[float]]:
        torch = self._torch
        width = ((image.width + 31) // 32) * 32
        height = ((image.height + 31) // 32) * 32
        scale = min(width / image.width, height / image.height)
        resized_width = int(image.width * scale)
        resized_height = int(image.height * scale)
        pad_left = (width - resized_width) // 2
        pad_top = (height - resized_height) // 2
        resized = image.resize((resized_width, resized_height), Image.Resampling.LANCZOS)
        padded = Image.new("RGB", (width, height), (114, 114, 114))
        padded.paste(resized, (pad_left, pad_top))
        array = self._np.asarray(padded, dtype=self._np.float32).transpose(2, 0, 1) / 255.0
        tensor = torch.from_numpy(array).unsqueeze(0).to(self._device)
        inference_context: Any = (
            torch.autocast(device_type="cuda", dtype=torch.float16)
            if self._device.type == "cuda"
            else nullcontext()
        )
        with torch.inference_mode(), inference_context, torch.jit.optimized_execution(False):
            outputs = self._detector(tensor)
            class_scores, decoded = self._decode(outputs)
        scores, class_ids = class_scores[0].max(dim=-1)
        valid = scores > 0.05
        scores = scores[valid]
        class_ids = class_ids[valid]
        boxes = decoded[0][valid]
        boxes[:, [0, 2]] = (boxes[:, [0, 2]] - pad_left) / scale
        boxes[:, [1, 3]] = (boxes[:, [1, 3]] - pad_top) / scale
        keep = self._ops.batched_nms(boxes, scores, class_ids, 0.1)[:300]
        boxes = boxes[keep]
        scores = scores[keep]
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clamp(0, image.width)
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clamp(0, image.height)
        return boxes.detach().cpu().tolist(), scores.detach().cpu().tolist()

    def _decode(self, outputs: Any) -> tuple[Any, Any]:
        torch = self._torch
        class_logits: list[Any] = []
        decoded_boxes: list[Any] = []
        for output_index, stride in zip(range(0, len(outputs), 2), self._strides, strict=True):
            layer_logits, layer_distances = outputs[output_index : output_index + 2]
            batch_size, _, height, width = layer_logits.shape
            logits = layer_logits.permute(0, 2, 3, 1).reshape(batch_size, -1, layer_logits.shape[1])
            distances = layer_distances.permute(0, 2, 3, 1).reshape(batch_size, -1, 4) * stride
            grid_y, grid_x = torch.meshgrid(
                torch.arange(height, device=self._device),
                torch.arange(width, device=self._device),
                indexing="ij",
            )
            anchors = (torch.stack((grid_x, grid_y), dim=-1).reshape(-1, 2) + 0.5) * stride
            left_top, right_bottom = distances.chunk(2, dim=-1)
            decoded_boxes.append(torch.cat((anchors - left_top, anchors + right_bottom), dim=-1))
            class_logits.append(logits)
        return torch.cat(class_logits, dim=1).sigmoid(), torch.cat(decoded_boxes, dim=1)

    def _caption(self, image: Image.Image, boxes: list[list[float]]) -> list[str]:
        if not boxes:
            return []
        crops = [
            image.crop(
                (
                    round(box[0]),
                    round(box[1]),
                    round(box[2]),
                    round(box[3]),
                )
            ).resize((64, 64))
            for box in boxes
        ]
        captions: list[str] = []
        for start in range(0, len(crops), 32):
            batch = crops[start : start + 32]
            inputs = self._processor(
                images=batch,
                text=["<CAPTION>"] * len(batch),
                return_tensors="pt",
                do_resize=False,
            ).to(device=self._device)
            with self._torch.inference_mode():
                generated = self._captioner.generate(
                    input_ids=inputs["input_ids"],
                    pixel_values=inputs["pixel_values"],
                    max_new_tokens=20,
                    num_beams=1,
                    do_sample=False,
                )
            captions.extend(
                value.strip()
                for value in self._processor.batch_decode(generated, skip_special_tokens=True)
            )
        return captions
