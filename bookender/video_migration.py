"""One-time registration of the existing JSON video project in SQLite."""

from __future__ import annotations

import hashlib
import json
import unicodedata
import uuid as uuidlib
from pathlib import Path
from typing import Any

from .paths import ROOT, USER_DATA
from .repository import ProjectRepository, json_text, utc_now


VIDEO_NAMESPACE = uuidlib.UUID("538872a7-f3a5-4028-a0c8-256c803bd462")


def _cyrillic_score(value: str) -> int:
    return sum("CYRILLIC" in unicodedata.name(char, "") for char in value)


def repair_mojibake(value: str) -> str:
    candidates = [value]
    for source_encoding, target_encoding in (
        ("latin1", "utf-8"),
        ("latin1", "cp1251"),
        ("cp1251", "utf-8"),
    ):
        try:
            candidates.append(value.encode(source_encoding).decode(target_encoding))
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return max(candidates, key=lambda item: (_cyrillic_score(item), -item.count("�")))


def repair_strings(value: Any) -> Any:
    if isinstance(value, str):
        return repair_mojibake(value)
    if isinstance(value, list):
        return [repair_strings(item) for item in value]
    if isinstance(value, dict):
        return {key: repair_strings(item) for key, item in value.items()}
    return value


class LegacyVideoMigrator:
    def __init__(
        self,
        repository: ProjectRepository,
        project_path: Path | str = ROOT / "_suviren_q_build" / "editor-project.json",
    ) -> None:
        self.repository = repository
        self.project_path = Path(project_path)

    def migrate(self) -> dict[str, Any]:
        if not self.project_path.exists():
            return {"status": "missing", "path": str(self.project_path)}
        raw = self.project_path.read_bytes()
        source_hash = hashlib.sha256(raw).hexdigest()
        payload = repair_strings(json.loads(raw.decode("utf-8-sig")))
        identifier = "legacy-video:existing-editor-project"
        with self.repository.database.connect() as connection:
            previous = connection.execute(
                """
                SELECT * FROM legacy_imports
                WHERE source_type='legacy_video' AND source_identifier=?
                """,
                (identifier,),
            ).fetchone()
            if previous:
                project = connection.execute(
                    "SELECT uuid FROM projects WHERE id=?",
                    (previous["destination_project_id"],),
                ).fetchone()
                return {
                    "status": "skipped",
                    "reason": "already_migrated",
                    "project_uuid": project["uuid"] if project else None,
                    "source_hash": source_hash,
                }
        project_uuid = str(uuidlib.uuid5(VIDEO_NAMESPACE, identifier))
        title = str(payload.get("title") or "Существующий видеопроект")
        project = self.repository.create_project(
            title=title,
            author=str(payload.get("author") or ""),
            project_kind="video",
            create_book=False,
            project_uuid=project_uuid,
        )
        edition = self.repository.save_video_edition(project_uuid, payload)
        now = utc_now()
        with self.repository.database.transaction() as connection:
            project_row = connection.execute(
                "SELECT id FROM projects WHERE uuid=?", (project_uuid,)
            ).fetchone()
            project_id = int(project_row["id"])
            for material in payload.get("materials", []):
                if not isinstance(material, dict):
                    continue
                original = str(material.get("serverPath") or "")
                if not original:
                    continue
                material_type = str(material.get("type") or "")
                stored_path = f"external:{original.replace(chr(92), '/')}"
                if material_type == "audio":
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO audio_assets(
                            project_id, file_path, generation_status,
                            created_at, updated_at
                        ) VALUES (?, ?, 'ready', ?, ?)
                        """,
                        (project_id, stored_path, now, now),
                    )
                elif material_type in {"image", "video"}:
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO visual_assets(
                            project_id, file_path, asset_type, title,
                            metadata_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            project_id,
                            stored_path,
                            material_type,
                            str(material.get("name") or ""),
                            json_text({"legacy_material_id": material.get("id")}),
                            now,
                        ),
                    )
            connection.execute(
                """
                INSERT INTO legacy_imports(
                    source_type, source_path, source_identifier,
                    destination_project_id, source_hash, destination_hash,
                    status, details_json, imported_at, import_version
                ) VALUES (
                    'legacy_video', ?, ?, ?, ?, ?, 'imported', ?, ?, 1
                )
                """,
                (
                    self.project_path.relative_to(ROOT).as_posix(),
                    identifier,
                    project_id,
                    source_hash,
                    source_hash,
                    json_text(
                        {
                            "edition_id": edition["id"],
                            "materials": len(payload.get("materials", [])),
                            "chapters": len(payload.get("chapters", [])),
                            "scenes": len(payload.get("scenes", [])),
                            "compatibility_source": str(self.project_path),
                        }
                    ),
                    now,
                ),
            )
        return {
            "status": "imported",
            "project_uuid": project["uuid"],
            "edition_id": edition["id"],
            "source_hash": source_hash,
            "materials": len(payload.get("materials", [])),
            "chapters": len(payload.get("chapters", [])),
            "scenes": len(payload.get("scenes", [])),
        }
