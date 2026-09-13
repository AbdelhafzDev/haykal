"""Verified, portable backups for one local Haykal state directory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath


class BackupError(RuntimeError):
    pass


class StateBackup:
    INCLUDED_DIRECTORIES = ("artifacts", "skill-objects")
    DATABASE = "runtime.sqlite3"

    @staticmethod
    def _digest(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return f"sha256:{digest.hexdigest()}"

    def create(self, state_directory: str | Path, output: str | Path) -> dict[str, object]:
        state = Path(state_directory).resolve()
        destination = Path(output).resolve()
        if not state.is_dir():
            raise BackupError("state directory does not exist")
        destination.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_archive = tempfile.mkstemp(
            prefix=".haykal-backup-", suffix=".tar.gz", dir=destination.parent
        )
        os.close(descriptor)
        try:
            with tempfile.TemporaryDirectory(prefix="haykal-backup-stage-") as temporary:
                stage = Path(temporary) / "state"
                stage.mkdir()
                database = state / self.DATABASE
                if database.exists():
                    with (
                        closing(sqlite3.connect(database)) as source,
                        closing(sqlite3.connect(stage / self.DATABASE)) as target,
                    ):
                        source.backup(target)
                for name in self.INCLUDED_DIRECTORIES:
                    source_directory = state / name
                    if source_directory.is_dir():
                        shutil.copytree(source_directory, stage / name)
                files = sorted(path for path in stage.rglob("*") if path.is_file())
                manifest: dict[str, object] = {
                    "schema_version": "1.0",
                    "created_at": datetime.now(UTC).isoformat(),
                    "files": {
                        path.relative_to(stage).as_posix(): {
                            "sha256": self._digest(path),
                            "size": path.stat().st_size,
                        }
                        for path in files
                    },
                }
                (stage / "backup-manifest.json").write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with tarfile.open(temporary_archive, "w:gz", format=tarfile.PAX_FORMAT) as archive:
                    for path in sorted(stage.rglob("*")):
                        archive.add(
                            path, arcname=path.relative_to(stage).as_posix(), recursive=False
                        )
            os.replace(temporary_archive, destination)
        finally:
            if os.path.exists(temporary_archive):
                os.unlink(temporary_archive)
        return {
            **manifest,
            "archive": str(destination),
            "archive_sha256": self._digest(destination),
        }

    def restore(self, archive: str | Path, destination: str | Path) -> dict[str, object]:
        source = Path(archive).resolve()
        target = Path(destination).resolve()
        if not source.is_file():
            raise BackupError("backup archive does not exist")
        if target.exists() and any(target.iterdir()):
            raise BackupError("restore destination must be empty")
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".haykal-restore-", dir=target.parent) as temporary:
            stage = Path(temporary)
            with tarfile.open(source, "r:gz") as bundle:
                members = bundle.getmembers()
                for member in members:
                    relative = PurePosixPath(member.name)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise BackupError("backup contains an unsafe path")
                    if member.issym() or member.islnk() or member.isdev():
                        raise BackupError("backup contains an unsupported entry")
                    output = stage.joinpath(*relative.parts)
                    if member.isdir():
                        output.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        output.parent.mkdir(parents=True, exist_ok=True)
                        stream = bundle.extractfile(member)
                        if stream is None:
                            raise BackupError("backup member could not be read")
                        with output.open("wb") as destination_stream:
                            shutil.copyfileobj(stream, destination_stream)
            manifest_path = stage / "backup-manifest.json"
            if not manifest_path.is_file():
                raise BackupError("backup manifest is missing")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_files = manifest.get("files")
            if not isinstance(expected_files, dict):
                raise BackupError("backup manifest is invalid")
            actual_files = {
                path.relative_to(stage).as_posix()
                for path in stage.rglob("*")
                if path.is_file() and path != manifest_path
            }
            if actual_files != set(expected_files):
                raise BackupError("backup contents do not match the manifest")
            for name, metadata in expected_files.items():
                if not isinstance(name, str) or not isinstance(metadata, dict):
                    raise BackupError("backup manifest entry is invalid")
                restored = stage.joinpath(*PurePosixPath(name).parts)
                if metadata.get("sha256") != self._digest(restored):
                    raise BackupError(f"backup integrity check failed for {name}")
            target.mkdir(mode=0o700, exist_ok=True)
            for path in stage.iterdir():
                if path.name != "backup-manifest.json":
                    shutil.move(str(path), target / path.name)
        return {
            "schema_version": "1.0",
            "archive_sha256": self._digest(source),
            "restored_files": len(expected_files),
            "destination": str(target),
        }
