"""Transactional data access for books, projects, media and video editions."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .database import BookenderDatabase
from .logging import log_event
from .paths import BACKUPS_DIR, PROJECTS_DIR, USER_DATA, ensure_user_directories


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_value(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def row_dict(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


class ProjectNotFoundError(LookupError):
    pass


class ProjectRepository:
    def __init__(self, database: BookenderDatabase | None = None) -> None:
        self.database = database or BookenderDatabase()

    def initialize(self) -> list[int]:
        return self.database.migrate()

    def _project_folder(self, project_uuid: str) -> str:
        return f"projects/{project_uuid}"

    def ensure_project_folders(self, project_folder: str) -> Path:
        root = USER_DATA / project_folder
        for name in ("audio", "images", "video", "exports", "temp"):
            (root / name).mkdir(parents=True, exist_ok=True)
        return root

    def create_project(
        self,
        *,
        title: str,
        author: str = "",
        description: str = "",
        project_kind: str = "book",
        language: str = "ru",
        voice: str = "",
        create_book: bool | None = None,
        create_first_chapter: bool = False,
        project_uuid: str | None = None,
    ) -> dict[str, Any]:
        if project_kind not in {"book", "video", "hybrid"}:
            raise ValueError(f"Unsupported project kind: {project_kind}")
        title = title.strip() or "Без названия"
        project_uuid = project_uuid or str(uuidlib.uuid4())
        folder = self._project_folder(project_uuid)
        self.ensure_project_folders(folder)
        now = utc_now()
        if create_book is None:
            create_book = project_kind in {"book", "hybrid"}
        with self.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects(
                    uuid, title, author, description, project_kind, status,
                    project_folder, created_at, updated_at, last_opened_at
                ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, ?)
                """,
                (
                    project_uuid,
                    title,
                    author.strip(),
                    description.strip(),
                    project_kind,
                    folder,
                    now,
                    now,
                    now,
                ),
            )
            project_id = int(cursor.lastrowid)
            if create_book:
                book_cursor = connection.execute(
                    """
                    INSERT INTO books(
                        project_id, title, author, description, language,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        title,
                        author.strip(),
                        description.strip(),
                        language or "ru",
                        now,
                        now,
                    ),
                )
                if create_first_chapter:
                    connection.execute(
                        """
                        INSERT INTO chapters(
                            book_id, title, content, position, created_at,
                            updated_at, content_hash
                        ) VALUES (?, 'Глава 1', '', 0, ?, ?, ?)
                        """,
                        (int(book_cursor.lastrowid), now, now, content_hash("")),
                    )
                connection.execute(
                    """
                    INSERT INTO tts_settings(
                        project_id, voice, updated_at
                    ) VALUES (?, ?, ?)
                    """,
                    (project_id, voice, now),
                )
            self._set_app_state(connection, "active_project_uuid", project_uuid)
        log_event(
            "project_created",
            project_uuid=project_uuid,
            project_kind=project_kind,
        )
        return self.get_project(project_uuid, include_details=True)

    def list_projects(
        self,
        *,
        search: str = "",
        kind: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        conditions = ["p.deleted_at IS NULL"]
        values: list[Any] = []
        if not include_archived:
            conditions.append("p.archived_at IS NULL")
        if search:
            conditions.append("(p.title LIKE ? OR p.author LIKE ?)")
            needle = f"%{search}%"
            values.extend((needle, needle))
        if kind:
            conditions.append("p.project_kind = ?")
            values.append(kind)
        sql = f"""
            SELECT p.*,
                   EXISTS(SELECT 1 FROM books b WHERE b.project_id=p.id) AS has_book,
                   EXISTS(SELECT 1 FROM video_editions v WHERE v.project_id=p.id) AS has_video,
                   (SELECT COUNT(*) FROM chapters c JOIN books b ON b.id=c.book_id
                     WHERE b.project_id=p.id AND c.archived_at IS NULL) AS chapter_count
            FROM projects p
            WHERE {' AND '.join(conditions)}
            ORDER BY p.last_opened_at DESC, p.updated_at DESC, p.title COLLATE NOCASE
        """
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(sql, values).fetchall()]

    def get_project(
        self, project_uuid: str, *, include_details: bool = False
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE uuid=? AND deleted_at IS NULL",
                (project_uuid,),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(project_uuid)
            project = dict(row)
            if include_details:
                book = connection.execute(
                    "SELECT * FROM books WHERE project_id=?", (row["id"],)
                ).fetchone()
                project["book"] = dict(book) if book else None
                if book:
                    project["chapters"] = [
                        dict(chapter)
                        for chapter in connection.execute(
                            """
                            SELECT * FROM chapters
                            WHERE book_id=? AND archived_at IS NULL
                            ORDER BY position, id
                            """,
                            (book["id"],),
                        ).fetchall()
                    ]
                else:
                    project["chapters"] = []
                tts = connection.execute(
                    "SELECT * FROM tts_settings WHERE project_id=?",
                    (row["id"],),
                ).fetchone()
                project["tts_settings"] = dict(tts) if tts else None
                chapter_hashes = {
                    int(chapter["id"]): chapter["content_hash"]
                    for chapter in project["chapters"]
                }
                project["audio_assets"] = []
                for asset_row in connection.execute(
                    """
                    SELECT * FROM audio_assets
                    WHERE project_id=?
                    ORDER BY chapter_id, created_at DESC, id DESC
                    """,
                    (row["id"],),
                ).fetchall():
                    asset = dict(asset_row)
                    current_hash = chapter_hashes.get(int(asset["chapter_id"] or 0))
                    asset["is_stale"] = bool(
                        current_hash
                        and asset["source_text_hash"]
                        and asset["source_text_hash"] != current_hash
                    )
                    project["audio_assets"].append(asset)
                project["visual_assets"] = [
                    dict(asset)
                    for asset in connection.execute(
                        "SELECT * FROM visual_assets WHERE project_id=? ORDER BY id",
                        (row["id"],),
                    ).fetchall()
                ]
                project["video_editions"] = [
                    self._video_row(connection, edition)
                    for edition in connection.execute(
                        """
                        SELECT * FROM video_editions
                        WHERE project_id=? ORDER BY updated_at DESC, id
                        """,
                        (row["id"],),
                    ).fetchall()
                ]
            return project

    def open_project(self, project_uuid: str) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE projects SET last_opened_at=?, updated_at=updated_at
                WHERE uuid=? AND deleted_at IS NULL
                """,
                (now, project_uuid),
            )
            if not result.rowcount:
                raise ProjectNotFoundError(project_uuid)
            self._set_app_state(connection, "active_project_uuid", project_uuid)
        log_event("project_opened", project_uuid=project_uuid)
        return self.get_project(project_uuid, include_details=True)

    def active_project_uuid(self) -> str | None:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value_json FROM app_state WHERE key='active_project_uuid'"
            ).fetchone()
            return json_value(row["value_json"]) if row else None

    def update_project(
        self,
        project_uuid: str,
        *,
        title: str | None = None,
        author: str | None = None,
        description: str | None = None,
    ) -> dict[str, Any]:
        updates: list[str] = []
        values: list[Any] = []
        for column, value in (
            ("title", title),
            ("author", author),
            ("description", description),
        ):
            if value is not None:
                updates.append(f"{column}=?")
                values.append(value.strip())
        if not updates:
            return self.get_project(project_uuid, include_details=True)
        updates.append("updated_at=?")
        values.append(utc_now())
        values.append(project_uuid)
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT id FROM projects WHERE uuid=? AND deleted_at IS NULL",
                (project_uuid,),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(project_uuid)
            connection.execute(
                f"UPDATE projects SET {', '.join(updates)} WHERE uuid=?", values
            )
            if title is not None:
                connection.execute(
                    "UPDATE books SET title=?, updated_at=? WHERE project_id=?",
                    (title.strip() or "Без названия", utc_now(), row["id"]),
                )
            if author is not None:
                connection.execute(
                    "UPDATE books SET author=?, updated_at=? WHERE project_id=?",
                    (author.strip(), utc_now(), row["id"]),
                )
            if description is not None:
                connection.execute(
                    "UPDATE books SET description=?, updated_at=? WHERE project_id=?",
                    (description.strip(), utc_now(), row["id"]),
                )
        return self.get_project(project_uuid, include_details=True)

    def archive_project(self, project_uuid: str, archived: bool = True) -> None:
        now = utc_now()
        with self.database.transaction() as connection:
            result = connection.execute(
                """
                UPDATE projects
                SET status=?, archived_at=?, updated_at=?
                WHERE uuid=? AND deleted_at IS NULL
                """,
                ("archived" if archived else "active", now if archived else None, now, project_uuid),
            )
            if not result.rowcount:
                raise ProjectNotFoundError(project_uuid)
        log_event("project_archived" if archived else "project_restored", project_uuid=project_uuid)

    def create_book_part(
        self,
        project_uuid: str,
        *,
        title: str | None = None,
        language: str = "ru",
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            project = connection.execute(
                "SELECT * FROM projects WHERE uuid=? AND deleted_at IS NULL",
                (project_uuid,),
            ).fetchone()
            if project is None:
                raise ProjectNotFoundError(project_uuid)
            existing = connection.execute(
                "SELECT id FROM books WHERE project_id=?", (project["id"],)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """
                    INSERT INTO books(
                        project_id, title, author, description, language,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project["id"],
                        title or project["title"],
                        project["author"],
                        project["description"],
                        language,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO tts_settings(project_id, updated_at) VALUES (?, ?)",
                    (project["id"], now),
                )
                connection.execute(
                    "UPDATE projects SET project_kind='hybrid', updated_at=? WHERE id=?",
                    (now, project["id"]),
                )
        return self.get_project(project_uuid, include_details=True)

    def create_chapter(
        self, project_uuid: str, *, title: str = "", content: str = ""
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            book = self._book_for_project(connection, project_uuid)
            position = int(
                connection.execute(
                    "SELECT COALESCE(MAX(position), -1)+1 FROM chapters WHERE book_id=?",
                    (book["id"],),
                ).fetchone()[0]
            )
            cursor = connection.execute(
                """
                INSERT INTO chapters(
                    book_id, title, content, position, created_at, updated_at,
                    content_hash
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    book["id"],
                    title.strip() or f"Глава {position + 1}",
                    content,
                    position,
                    now,
                    now,
                    content_hash(content),
                ),
            )
            self._touch_project(connection, book["project_id"], now)
            chapter_id = int(cursor.lastrowid)
        return self.get_chapter(project_uuid, chapter_id)

    def get_chapter(self, project_uuid: str, chapter_id: int) -> dict[str, Any]:
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT c.* FROM chapters c
                JOIN books b ON b.id=c.book_id
                JOIN projects p ON p.id=b.project_id
                WHERE p.uuid=? AND c.id=? AND c.archived_at IS NULL
                """,
                (project_uuid, chapter_id),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
            return dict(row)

    def update_chapter(
        self,
        project_uuid: str,
        chapter_id: int,
        *,
        title: str | None = None,
        content: str | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            book = self._book_for_project(connection, project_uuid)
            chapter = connection.execute(
                "SELECT * FROM chapters WHERE id=? AND book_id=? AND archived_at IS NULL",
                (chapter_id, book["id"]),
            ).fetchone()
            if chapter is None:
                raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
            next_title = chapter["title"] if title is None else (title.strip() or chapter["title"])
            next_content = chapter["content"] if content is None else content
            connection.execute(
                """
                UPDATE chapters
                SET title=?, content=?, content_hash=?, updated_at=?
                WHERE id=?
                """,
                (
                    next_title,
                    next_content,
                    content_hash(next_content),
                    now,
                    chapter_id,
                ),
            )
            connection.execute(
                "UPDATE books SET updated_at=? WHERE id=?", (now, book["id"])
            )
            self._touch_project(connection, book["project_id"], now)
        log_event(
            "chapter_saved",
            project_uuid=project_uuid,
            chapter_id=chapter_id,
            content_hash=content_hash(next_content),
        )
        return self.get_chapter(project_uuid, chapter_id)

    def reorder_chapters(self, project_uuid: str, chapter_ids: Iterable[int]) -> None:
        ids = [int(value) for value in chapter_ids]
        with self.database.transaction() as connection:
            book = self._book_for_project(connection, project_uuid)
            existing = {
                int(row["id"])
                for row in connection.execute(
                    "SELECT id FROM chapters WHERE book_id=? AND archived_at IS NULL",
                    (book["id"],),
                ).fetchall()
            }
            if set(ids) != existing or len(ids) != len(existing):
                raise ValueError("Chapter order must contain every active chapter exactly once")
            # Use negative values first to avoid the UNIQUE(book_id, position) index.
            for position, chapter_id in enumerate(ids):
                connection.execute(
                    "UPDATE chapters SET position=? WHERE id=?",
                    (-position - 1, chapter_id),
                )
            now = utc_now()
            for position, chapter_id in enumerate(ids):
                connection.execute(
                    "UPDATE chapters SET position=?, updated_at=? WHERE id=?",
                    (position, now, chapter_id),
                )
            self._touch_project(connection, book["project_id"], now)

    def archive_chapter(self, project_uuid: str, chapter_id: int) -> None:
        now = utc_now()
        with self.database.transaction() as connection:
            book = self._book_for_project(connection, project_uuid)
            result = connection.execute(
                "UPDATE chapters SET archived_at=?, updated_at=? WHERE id=? AND book_id=?",
                (now, now, chapter_id, book["id"]),
            )
            if not result.rowcount:
                raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
            remaining = [
                int(row["id"])
                for row in connection.execute(
                    """
                    SELECT id FROM chapters
                    WHERE book_id=? AND archived_at IS NULL ORDER BY position, id
                    """,
                    (book["id"],),
                ).fetchall()
            ]
            connection.execute(
                "UPDATE chapters SET position=? WHERE id=?",
                (1_000_000 + chapter_id, chapter_id),
            )
            for position, item_id in enumerate(remaining):
                connection.execute(
                    "UPDATE chapters SET position=? WHERE id=?",
                    (-position - 1, item_id),
                )
            for position, item_id in enumerate(remaining):
                connection.execute(
                    "UPDATE chapters SET position=? WHERE id=?", (position, item_id)
                )
            self._touch_project(connection, book["project_id"], now)

    def update_tts_settings(
        self, project_uuid: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            values = {
                "voice": str(settings.get("voice", "")),
                "rate": str(settings.get("rate", "+0%")),
                "pitch": str(settings.get("pitch", "+0Hz")),
                "volume": str(settings.get("volume", "+0%")),
                "provider": str(settings.get("provider", "edge-tts")),
                "settings_json": json_text(settings.get("extra", {})),
            }
            connection.execute(
                """
                INSERT INTO tts_settings(
                    project_id, voice, rate, pitch, volume, provider,
                    settings_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    voice=excluded.voice, rate=excluded.rate,
                    pitch=excluded.pitch, volume=excluded.volume,
                    provider=excluded.provider,
                    settings_json=excluded.settings_json,
                    updated_at=excluded.updated_at
                """,
                (
                    project["id"],
                    values["voice"],
                    values["rate"],
                    values["pitch"],
                    values["volume"],
                    values["provider"],
                    values["settings_json"],
                    now,
                ),
            )
            self._touch_project(connection, project["id"], now)
        return self.get_project(project_uuid, include_details=True)["tts_settings"]

    def update_audio_asset(
        self,
        project_uuid: str,
        asset_id: int,
        *,
        title: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            asset = connection.execute(
                """
                SELECT * FROM audio_assets
                WHERE id=? AND project_id=?
                """,
                (asset_id, project["id"]),
            ).fetchone()
            if asset is None:
                raise ProjectNotFoundError(f"{project_uuid}/audio/{asset_id}")
            if is_active:
                connection.execute(
                    """
                    UPDATE audio_assets SET is_active=0, updated_at=?
                    WHERE project_id=? AND chapter_id IS ?
                    """,
                    (now, project["id"], asset["chapter_id"]),
                )
            updates = ["updated_at=?"]
            values: list[Any] = [now]
            if title is not None:
                updates.append("title=?")
                values.append(title.strip() or Path(asset["file_path"]).stem)
            if is_active is not None:
                updates.append("is_active=?")
                values.append(1 if is_active else 0)
            values.extend((asset_id, project["id"]))
            connection.execute(
                f"UPDATE audio_assets SET {', '.join(updates)} WHERE id=? AND project_id=?",
                values,
            )
            updated = connection.execute(
                "SELECT * FROM audio_assets WHERE id=?", (asset_id,)
            ).fetchone()
        return dict(updated)

    def delete_audio_asset(self, project_uuid: str, asset_id: int) -> dict[str, Any]:
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            asset = connection.execute(
                "SELECT * FROM audio_assets WHERE id=? AND project_id=?",
                (asset_id, project["id"]),
            ).fetchone()
            if asset is None:
                raise ProjectNotFoundError(f"{project_uuid}/audio/{asset_id}")
            connection.execute(
                "DELETE FROM audio_assets WHERE id=? AND project_id=?",
                (asset_id, project["id"]),
            )
            if asset["is_active"] and asset["chapter_id"] is not None:
                replacement = connection.execute(
                    """
                    SELECT id FROM audio_assets
                    WHERE project_id=? AND chapter_id=?
                    ORDER BY created_at DESC, id DESC LIMIT 1
                    """,
                    (project["id"], asset["chapter_id"]),
                ).fetchone()
                if replacement:
                    connection.execute(
                        "UPDATE audio_assets SET is_active=1 WHERE id=?",
                        (replacement["id"],),
                    )
        file_path = str(asset["file_path"])
        removed = False
        if not file_path.startswith("external:"):
            projects_root = (USER_DATA / "projects").resolve()
            path = (USER_DATA / file_path).resolve()
            try:
                path.relative_to(projects_root)
                path.unlink(missing_ok=True)
                removed = True
            except (OSError, ValueError):
                log_event(
                    "audio_asset_file_delete_failed",
                    project_uuid=project_uuid,
                    asset_id=asset_id,
                    file_path=file_path,
                )
        log_event(
            "audio_asset_deleted",
            project_uuid=project_uuid,
            asset_id=asset_id,
            file_removed=removed,
        )
        return {"deleted": True, "file_removed": removed}

    def add_chapter_visual_asset(
        self,
        project_uuid: str,
        chapter_id: int,
        *,
        file_path: str,
        title: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            chapter = connection.execute(
                """
                SELECT c.id FROM chapters c
                JOIN books b ON b.id=c.book_id
                WHERE c.id=? AND b.project_id=? AND c.archived_at IS NULL
                """,
                (chapter_id, project["id"]),
            ).fetchone()
            if chapter is None:
                raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
            cursor = connection.execute(
                """
                INSERT INTO visual_assets(
                    project_id, chapter_id, file_path, asset_type, title,
                    metadata_json, created_at
                ) VALUES (?, ?, ?, 'chapter-image', ?, ?, ?)
                """,
                (
                    project["id"],
                    chapter_id,
                    file_path,
                    title.strip() or Path(file_path).stem,
                    json_text(metadata or {}),
                    now,
                ),
            )
            self._touch_project(connection, project["id"], now)
            asset = connection.execute(
                "SELECT * FROM visual_assets WHERE id=?",
                (int(cursor.lastrowid),),
            ).fetchone()
        log_event(
            "chapter_visual_added",
            project_uuid=project_uuid,
            chapter_id=chapter_id,
            asset_id=asset["id"],
            file_path=file_path,
        )
        return dict(asset)

    def remove_chapter_visual_asset(
        self, project_uuid: str, chapter_id: int
    ) -> dict[str, Any]:
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            assets = connection.execute(
                """
                SELECT * FROM visual_assets
                WHERE project_id=? AND chapter_id=? AND asset_type='chapter-image'
                ORDER BY id DESC
                """,
                (project["id"], chapter_id),
            ).fetchall()
            if not assets:
                return {"deleted": False, "file_removed": False}
            connection.execute(
                """
                DELETE FROM visual_assets
                WHERE project_id=? AND chapter_id=? AND asset_type='chapter-image'
                """,
                (project["id"], chapter_id),
            )
            self._touch_project(connection, project["id"], utc_now())
        removed_files = 0
        for asset in assets:
            path = (USER_DATA / str(asset["file_path"])).resolve()
            try:
                path.relative_to((USER_DATA / "projects").resolve())
                path.unlink(missing_ok=True)
                removed_files += 1
            except (OSError, ValueError):
                log_event(
                    "chapter_visual_file_delete_failed",
                    project_uuid=project_uuid,
                    chapter_id=chapter_id,
                    file_path=asset["file_path"],
                )
        return {
            "deleted": True,
            "deleted_assets": len(assets),
            "removed_files": removed_files,
        }

    def save_video_edition(
        self,
        project_uuid: str,
        payload: dict[str, Any],
        *,
        edition_id: int | None = None,
    ) -> dict[str, Any]:
        now = utc_now()
        with self.database.transaction() as connection:
            project = self._project_row(connection, project_uuid)
            if edition_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO video_editions(
                        project_id, title, edition_kind, settings_json,
                        created_at, updated_at
                    ) VALUES (?, ?, 'audiobook', ?, ?, ?)
                    """,
                    (
                        project["id"],
                        str(payload.get("title") or project["title"]),
                        json_text(payload),
                        now,
                        now,
                    ),
                )
                edition_id = int(cursor.lastrowid)
            else:
                result = connection.execute(
                    """
                    UPDATE video_editions
                    SET title=?, settings_json=?, updated_at=?
                    WHERE id=? AND project_id=?
                    """,
                    (
                        str(payload.get("title") or project["title"]),
                        json_text(payload),
                        now,
                        edition_id,
                        project["id"],
                    ),
                )
                if not result.rowcount:
                    raise ProjectNotFoundError(
                        f"{project_uuid}/video-edition/{edition_id}"
                    )
                connection.execute(
                    "DELETE FROM timeline_items WHERE video_edition_id=?",
                    (edition_id,),
                )
            self._store_timeline(connection, edition_id, payload)
            if project["project_kind"] == "book":
                connection.execute(
                    "UPDATE projects SET project_kind='hybrid' WHERE id=?",
                    (project["id"],),
                )
            self._touch_project(connection, project["id"], now)
        log_event(
            "timeline_saved",
            project_uuid=project_uuid,
            video_edition_id=edition_id,
        )
        return self.get_video_edition(project_uuid, edition_id)

    def get_video_edition(
        self, project_uuid: str, edition_id: int | None = None
    ) -> dict[str, Any]:
        with self.database.connect() as connection:
            project = self._project_row(connection, project_uuid)
            if edition_id is None:
                row = connection.execute(
                    """
                    SELECT * FROM video_editions
                    WHERE project_id=? ORDER BY updated_at DESC, id DESC LIMIT 1
                    """,
                    (project["id"],),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT * FROM video_editions WHERE id=? AND project_id=?",
                    (edition_id, project["id"]),
                ).fetchone()
            if row is None:
                raise ProjectNotFoundError(f"{project_uuid}/video-edition")
            return self._video_row(connection, row)

    def create_video_edition(
        self, project_uuid: str, *, title: str | None = None
    ) -> dict[str, Any]:
        project = self.get_project(project_uuid, include_details=True)
        chapters = [
            {
                "id": f"chapter-{chapter['id']}",
                "chapterId": chapter["id"],
                "title": chapter["title"],
                # Until narration duration is known, keep a valid provisional
                # one-second slot. The video editor can retime it later.
                "start_seconds": index,
                "end_seconds": index + 1,
            }
            for index, chapter in enumerate(project.get("chapters", []))
        ]
        payload = {
            "schemaVersion": 2,
            "title": title or project["title"],
            "author": project["author"],
            "materials": [],
            "chapters": chapters,
            "scenes": [],
            "layers": {},
            "renderPreset": "balanced",
        }
        return self.save_video_edition(project_uuid, payload)

    def duplicate_project(self, project_uuid: str) -> dict[str, Any]:
        source = self.get_project(project_uuid, include_details=True)
        duplicate = self.create_project(
            title=f"{source['title']} — копия",
            author=source["author"],
            description=source["description"],
            project_kind=source["project_kind"],
            language=(source.get("book") or {}).get("language", "ru"),
            voice=(source.get("tts_settings") or {}).get("voice", ""),
            create_book=source.get("book") is not None,
        )
        for chapter in source.get("chapters", []):
            self.create_chapter(
                duplicate["uuid"],
                title=chapter["title"],
                content=chapter["content"],
            )
        for edition in source.get("video_editions", []):
            self.save_video_edition(duplicate["uuid"], edition["settings"])
        return self.get_project(duplicate["uuid"], include_details=True)

    def backup_project(self, project_uuid: str) -> Path:
        ensure_user_directories()
        project = self.get_project(project_uuid, include_details=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = BACKUPS_DIR / f"{project_uuid}-{stamp}"
        destination.mkdir(parents=True, exist_ok=False)
        project_root = USER_DATA / project["project_folder"]
        if project_root.exists():
            shutil.copytree(project_root, destination / "files", dirs_exist_ok=True)
        export = self._project_export(project)
        export_path = destination / "project.json"
        export_path.write_text(
            json.dumps(export, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        files = []
        for path in sorted(destination.rglob("*")):
            if path.is_file():
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                files.append(
                    {
                        "path": path.relative_to(destination).as_posix(),
                        "bytes": path.stat().st_size,
                        "sha256": digest,
                    }
                )
        manifest = {
            "project_uuid": project_uuid,
            "created_at": utc_now(),
            "files": files,
        }
        manifest_text = json.dumps(manifest, ensure_ascii=False, indent=2)
        (destination / "manifest.json").write_text(manifest_text, encoding="utf-8")
        manifest_hash = hashlib.sha256(manifest_text.encode("utf-8")).hexdigest()
        with self.database.transaction() as connection:
            project_row = self._project_row(connection, project_uuid)
            connection.execute(
                """
                INSERT INTO backup_history(
                    project_id, backup_path, manifest_hash, created_at
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    project_row["id"],
                    destination.relative_to(USER_DATA).as_posix(),
                    manifest_hash,
                    utc_now(),
                ),
            )
        log_event(
            "project_backup_created",
            project_uuid=project_uuid,
            backup_path=str(destination),
        )
        return destination

    def _project_export(self, project: dict[str, Any]) -> dict[str, Any]:
        result = dict(project)
        for edition in result.get("video_editions", []):
            edition.pop("settings_json", None)
        if result.get("tts_settings"):
            result["tts_settings"].pop("settings_json", None)
        return result

    def _video_row(self, connection: Any, row: Any) -> dict[str, Any]:
        value = dict(row)
        value["settings"] = json_value(value.pop("settings_json"), {})
        value["timeline_items"] = [
            {
                **dict(item),
                "settings": json_value(item["settings_json"], {}),
            }
            for item in connection.execute(
                """
                SELECT * FROM timeline_items
                WHERE video_edition_id=? ORDER BY position, id
                """,
                (row["id"],),
            ).fetchall()
        ]
        for item in value["timeline_items"]:
            item.pop("settings_json", None)
        return value

    def _store_timeline(
        self, connection: Any, edition_id: int, payload: dict[str, Any]
    ) -> None:
        position = 0
        for chapter in payload.get("chapters", []):
            if not isinstance(chapter, dict):
                continue
            connection.execute(
                """
                INSERT INTO timeline_items(
                    video_edition_id, chapter_id, item_type, track,
                    start_time, end_time, position, settings_json
                ) VALUES (?, ?, 'chapter', 'chapters', ?, ?, ?, ?)
                """,
                (
                    edition_id,
                    chapter.get("chapterId"),
                    float(chapter.get("start_seconds") or 0),
                    float(chapter.get("end_seconds") or 0),
                    position,
                    json_text(chapter),
                ),
            )
            position += 1
        for scene in payload.get("scenes", []):
            if not isinstance(scene, dict):
                continue
            connection.execute(
                """
                INSERT INTO timeline_items(
                    video_edition_id, item_type, track, start_time, end_time,
                    position, settings_json
                ) VALUES (?, 'scene', 'scenes', ?, ?, ?, ?)
                """,
                (
                    edition_id,
                    float(scene.get("start") or 0),
                    float(scene.get("end") or 0),
                    position,
                    json_text(scene),
                ),
            )
            position += 1

    def _set_app_state(
        self, connection: Any, key: str, value: Any
    ) -> None:
        connection.execute(
            """
            INSERT INTO app_state(key, value_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value_json=excluded.value_json, updated_at=excluded.updated_at
            """,
            (key, json_text(value), utc_now()),
        )

    def _project_row(self, connection: Any, project_uuid: str) -> Any:
        row = connection.execute(
            "SELECT * FROM projects WHERE uuid=? AND deleted_at IS NULL",
            (project_uuid,),
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(project_uuid)
        return row

    def _book_for_project(self, connection: Any, project_uuid: str) -> Any:
        row = connection.execute(
            """
            SELECT b.* FROM books b JOIN projects p ON p.id=b.project_id
            WHERE p.uuid=? AND p.deleted_at IS NULL
            """,
            (project_uuid,),
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError(f"{project_uuid}/book")
        return row

    def _touch_project(self, connection: Any, project_id: int, now: str) -> None:
        connection.execute(
            "UPDATE projects SET updated_at=? WHERE id=?", (now, project_id)
        )
