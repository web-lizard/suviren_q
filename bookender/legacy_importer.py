"""Read-only discovery and idempotent import of every legacy book."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import unicodedata
import uuid as uuidlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .logging import log_event
from .paths import LEGACY_EDITOR, USER_DATA
from .repository import ProjectRepository, content_hash, json_text, utc_now


IMPORT_VERSION = 1
BOOK_NAMESPACE = uuidlib.UUID("bb42d658-62a9-44b4-b0eb-c406b849e654")


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[^\w-]+", "-", normalized, flags=re.UNICODE)
    return normalized.strip("-") or "legacy-book"


def stable_json_hash(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


@dataclass
class LegacyCandidate:
    path: Path
    slug: str
    title: str
    chapters: list[dict[str, Any]]
    voice: str
    saved_at: str
    source_hash: str
    text_chars: int
    score: tuple[int, str, int, int]
    metadata: dict[str, Any] = field(default_factory=dict)

    def inventory(self, root: Path, *, canonical: bool = False) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "chapter_count": len(self.chapters),
            "chapter_titles": [
                str(item.get("title") or f"Глава {index + 1}")
                for index, item in enumerate(self.chapters)
            ],
            "text_chars": self.text_chars,
            "saved_at": self.saved_at,
            "tts_voice": self.voice,
            "source_path": _relative(self.path, root),
            "source_hash": self.source_hash,
            "canonical": canonical,
        }


@dataclass
class LegacyBook:
    key: str
    canonical: LegacyCandidate
    duplicates: list[LegacyCandidate]

    def inventory(self, root: Path) -> dict[str, Any]:
        return {
            **self.canonical.inventory(root, canonical=True),
            "logical_key": self.key,
            "duplicate_sources": [
                item.inventory(root) for item in self.duplicates
            ],
        }


@dataclass
class DiscoveryResult:
    root: Path
    books: list[LegacyBook]
    damaged_files: list[dict[str, str]]
    scanned_json_files: int

    def inventory(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "legacy_root": str(self.root.resolve()),
            "logical_book_count": len(self.books),
            "scanned_json_files": self.scanned_json_files,
            "damaged_files": self.damaged_files,
            "books": [book.inventory(self.root) for book in self.books],
        }


class LegacyBookImporter:
    def __init__(
        self,
        repository: ProjectRepository,
        legacy_root: Path | str = LEGACY_EDITOR,
    ) -> None:
        self.repository = repository
        self.legacy_root = Path(legacy_root)

    def discover(self) -> DiscoveryResult:
        candidates: list[LegacyCandidate] = []
        damaged: list[dict[str, str]] = []
        json_files = sorted(self.legacy_root.rglob("*.json"))
        for path in json_files:
            # Dependency metadata and TTS status files are not book documents.
            lower = path.as_posix().lower()
            if "/_pydeps/" in lower or "/tts/status" in lower:
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                damaged.append(
                    {"path": _relative(path, self.legacy_root), "error": str(exc)}
                )
                continue
            candidate = self._candidate(path, value)
            if candidate:
                candidates.append(candidate)
        grouped: dict[str, list[LegacyCandidate]] = {}
        for candidate in candidates:
            key = unicodedata.normalize("NFKC", candidate.title).casefold().strip()
            grouped.setdefault(key, []).append(candidate)
        books: list[LegacyBook] = []
        for key, items in grouped.items():
            ordered = sorted(items, key=lambda item: item.score, reverse=True)
            books.append(
                LegacyBook(
                    key=key,
                    canonical=ordered[0],
                    duplicates=ordered[1:],
                )
            )
        books.sort(key=lambda item: item.canonical.title.casefold())
        return DiscoveryResult(
            root=self.legacy_root,
            books=books,
            damaged_files=damaged,
            scanned_json_files=len(json_files),
        )

    def write_inventory(self, destination: Path) -> DiscoveryResult:
        result = self.discover()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(result.inventory(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return result

    def import_all(self, *, copy_audio: bool = True) -> dict[str, Any]:
        discovery = self.discover()
        report: dict[str, Any] = {
            "started_at": utc_now(),
            "source": str(self.legacy_root.resolve()),
            "found": len(discovery.books),
            "imported": 0,
            "skipped": 0,
            "conflicts": 0,
            "errors": [],
            "books": [],
        }
        for book in discovery.books:
            try:
                item = self._import_book(book, copy_audio=copy_audio)
            except Exception as exc:
                item = {
                    "title": book.canonical.title,
                    "slug": book.canonical.slug,
                    "status": "error",
                    "error": str(exc),
                }
                report["errors"].append(item)
                log_event(
                    "legacy_import_failed",
                    title=book.canonical.title,
                    error=str(exc),
                )
            report["books"].append(item)
            status = item["status"]
            if status == "imported":
                report["imported"] += 1
            elif status == "conflict":
                report["conflicts"] += 1
            else:
                report["skipped"] += 1
        report["finished_at"] = utc_now()
        report["integrity_check"] = self.repository.database.integrity_check()
        return report

    def _candidate(self, path: Path, value: Any) -> LegacyCandidate | None:
        if not isinstance(value, dict):
            return None
        chapters = value.get("chapters")
        title = value.get("title")
        if not isinstance(title, str) or not isinstance(chapters, list):
            return None
        normalized_chapters: list[dict[str, Any]] = []
        for index, item in enumerate(chapters):
            if not isinstance(item, dict):
                continue
            # A real book chapter has text/content or at least an explicit title.
            if not any(key in item for key in ("text", "content", "title")):
                continue
            normalized_chapters.append(
                {
                    "id": str(item.get("id") or f"legacy-{index + 1}"),
                    "title": str(item.get("title") or f"Глава {index + 1}"),
                    "text": str(item.get("text", item.get("content", "")) or ""),
                    "collapsed": bool(item.get("collapsed", False)),
                }
            )
        if not normalized_chapters and chapters:
            return None
        slug = self._slug_from_path(path, title)
        saved_at = str(
            value.get("saved_at")
            or value.get("updated_at")
            or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
        )
        source_hash = stable_json_hash(
            {
                "title": title,
                "chapters": normalized_chapters,
                "voice": value.get("tts_voice", ""),
            }
        )
        path_score = self._path_score(path, slug)
        text_chars = sum(len(item["text"]) for item in normalized_chapters)
        metadata = {
            key: val
            for key, val in value.items()
            if key not in {"chapters", "title", "tts_voice"}
            and isinstance(val, (str, int, float, bool, type(None)))
        }
        return LegacyCandidate(
            path=path,
            slug=slug,
            title=title.strip() or "Без названия",
            chapters=normalized_chapters,
            voice=str(value.get("tts_voice") or ""),
            saved_at=saved_at,
            source_hash=source_hash,
            text_chars=text_chars,
            score=(path_score, saved_at, len(normalized_chapters), text_chars),
            metadata=metadata,
        )

    def _slug_from_path(self, path: Path, title: str) -> str:
        parts = list(path.parts)
        lowered = [part.casefold() for part in parts]
        for index, part in enumerate(lowered[:-1]):
            if part == "books" and index + 1 < len(parts) - 1:
                candidate = parts[index + 1]
                if candidate.casefold() not in {"backups", "archive"}:
                    return slugify(candidate)
        return slugify(title)

    def _path_score(self, path: Path, slug: str) -> int:
        rel = _relative(path, self.legacy_root).casefold()
        canonical_data = f"data/books/{slug}/book.json"
        if rel == canonical_data:
            return 1000
        if rel.endswith(f"/data/books/{slug}/book.json"):
            return 900
        if rel == f"storage/books/{slug}/book.json":
            return 800
        if "/books/" in rel and rel.endswith("/book.json"):
            return 700
        if "backup" in rel or ".bak" in path.name.casefold():
            return 100
        if path.name.casefold() == "book.json":
            return 500
        return 200

    def _import_book(
        self, book: LegacyBook, *, copy_audio: bool
    ) -> dict[str, Any]:
        source = book.canonical
        identifier = f"legacy-book:{source.slug}"
        destination_hash = stable_json_hash(
            [
                {
                    "legacy_id": chapter["id"],
                    "title": chapter["title"],
                    "content_hash": content_hash(chapter["text"]),
                    "position": position,
                }
                for position, chapter in enumerate(source.chapters)
            ]
        )
        with self.repository.database.connect() as connection:
            previous = connection.execute(
                """
                SELECT * FROM legacy_imports
                WHERE source_type='legacy_book' AND source_identifier=?
                """,
                (identifier,),
            ).fetchone()
            if previous and previous["source_hash"] == source.source_hash:
                result = self._result(
                    source,
                    "skipped",
                    int(previous["destination_project_id"]),
                    "already_imported",
                )
                if copy_audio:
                    result["audio_assets"] = self._sync_existing_audio(
                        int(previous["destination_project_id"]), source
                    )
                return result
            if previous:
                current_hash = self._destination_hash(
                    connection, int(previous["destination_project_id"])
                )
                if current_hash != previous["destination_hash"]:
                    return self._result(
                        source,
                        "conflict",
                        int(previous["destination_project_id"]),
                        "source_changed_after_local_edits",
                    )
                # Updating a changed source is deliberately explicit. The safe
                # default keeps the imported local project intact.
                return self._result(
                    source,
                    "conflict",
                    int(previous["destination_project_id"]),
                    "source_changed_safe_update_required",
                )

        project_uuid = str(uuidlib.uuid5(BOOK_NAMESPACE, identifier))
        folder = self.repository._project_folder(project_uuid)
        project_root = self.repository.ensure_project_folders(folder)
        now = utc_now()
        with self.repository.database.transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO projects(
                    uuid, title, author, description, project_kind, status,
                    project_folder, created_at, updated_at
                ) VALUES (?, ?, '', '', 'book', 'active', ?, ?, ?)
                """,
                (project_uuid, source.title, folder, now, now),
            )
            project_id = int(cursor.lastrowid)
            book_cursor = connection.execute(
                """
                INSERT INTO books(
                    project_id, title, language, created_at, updated_at
                ) VALUES (?, ?, 'ru', ?, ?)
                """,
                (project_id, source.title, now, now),
            )
            book_id = int(book_cursor.lastrowid)
            chapter_ids: dict[str, int] = {}
            for position, chapter in enumerate(source.chapters):
                chapter_cursor = connection.execute(
                    """
                    INSERT INTO chapters(
                        book_id, legacy_id, title, content, position,
                        created_at, updated_at, content_hash
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        book_id,
                        chapter["id"],
                        chapter["title"],
                        chapter["text"],
                        position,
                        now,
                        now,
                        content_hash(chapter["text"]),
                    ),
                )
                chapter_ids[chapter["id"]] = int(chapter_cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO tts_settings(
                    project_id, voice, provider, settings_json, updated_at
                ) VALUES (?, ?, 'edge-tts', ?, ?)
                """,
                (
                    project_id,
                    source.voice,
                    json_text({"legacy": source.metadata}),
                    now,
                ),
            )
            audio_count = self._import_audio(
                connection,
                project_id,
                chapter_ids,
                source,
                project_root,
                copy_audio=copy_audio,
            )
            connection.execute(
                """
                INSERT INTO legacy_imports(
                    source_type, source_path, source_identifier,
                    destination_project_id, source_hash, destination_hash,
                    status, details_json, imported_at, import_version
                ) VALUES (
                    'legacy_book', ?, ?, ?, ?, ?, 'imported', ?, ?, ?
                )
                """,
                (
                    _relative(source.path, self.legacy_root),
                    identifier,
                    project_id,
                    source.source_hash,
                    destination_hash,
                    json_text(
                        {
                            "duplicate_sources": len(book.duplicates),
                            "audio_assets": audio_count,
                            "chapter_count": len(source.chapters),
                            "text_chars": source.text_chars,
                        }
                    ),
                    now,
                    IMPORT_VERSION,
                ),
            )
        log_event(
            "legacy_book_imported",
            project_uuid=project_uuid,
            legacy_slug=source.slug,
            chapters=len(source.chapters),
            text_chars=source.text_chars,
        )
        return {
            **self._result(source, "imported", project_id, "ok"),
            "project_uuid": project_uuid,
            "audio_assets": audio_count,
        }

    def _sync_existing_audio(
        self, project_id: int, source: LegacyCandidate
    ) -> int:
        with self.repository.database.transaction() as connection:
            project = connection.execute(
                "SELECT project_folder FROM projects WHERE id=?", (project_id,)
            ).fetchone()
            if project is None:
                return 0
            chapter_ids = {
                str(row["legacy_id"] or ""): int(row["id"])
                for row in connection.execute(
                    """
                    SELECT c.id, c.legacy_id FROM chapters c
                    JOIN books b ON b.id=c.book_id
                    WHERE b.project_id=?
                    """,
                    (project_id,),
                ).fetchall()
            }
            return self._import_audio(
                connection,
                project_id,
                chapter_ids,
                source,
                USER_DATA / project["project_folder"],
                copy_audio=True,
            )

    def _import_audio(
        self,
        connection: Any,
        project_id: int,
        chapter_ids: dict[str, int],
        source: LegacyCandidate,
        project_root: Path,
        *,
        copy_audio: bool,
    ) -> int:
        audio_root = self.legacy_root / "audio" / "books" / source.slug
        if not audio_root.exists():
            return 0
        count = 0
        for source_file in sorted(audio_root.rglob("*")):
            if not source_file.is_file() or source_file.suffix.casefold() not in {
                ".mp3",
                ".wav",
                ".m4a",
                ".flac",
                ".ogg",
                ".opus",
            }:
                continue
            target = (
                project_root
                / "audio"
                / "legacy"
                / source_file.relative_to(audio_root)
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            if copy_audio and not target.exists():
                shutil.copy2(source_file, target)
            stored_path = (
                target.relative_to(USER_DATA).as_posix()
                if copy_audio
                else f"external:{source_file.resolve()}"
            )
            chapter_id = next(
                (
                    value
                    for legacy_id, value in chapter_ids.items()
                    if legacy_id and legacy_id.casefold() in source_file.name.casefold()
                ),
                None,
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO audio_assets(
                    project_id, chapter_id, file_path, generation_status,
                    voice, created_at, updated_at
                ) VALUES (?, ?, ?, 'ready', ?, ?, ?)
                """,
                (
                    project_id,
                    chapter_id,
                    stored_path,
                    source.voice,
                    utc_now(),
                    utc_now(),
                ),
            )
            count += 1
        return count

    def _destination_hash(self, connection: Any, project_id: int) -> str:
        rows = connection.execute(
            """
            SELECT c.legacy_id, c.title, c.content_hash, c.position
            FROM chapters c JOIN books b ON b.id=c.book_id
            WHERE b.project_id=? AND c.archived_at IS NULL
            ORDER BY c.position, c.id
            """,
            (project_id,),
        ).fetchall()
        return stable_json_hash([dict(row) for row in rows])

    def _result(
        self,
        source: LegacyCandidate,
        status: str,
        project_id: int,
        reason: str,
    ) -> dict[str, Any]:
        return {
            "title": source.title,
            "slug": source.slug,
            "status": status,
            "reason": reason,
            "project_id": project_id,
            "chapters": len(source.chapters),
            "text_chars": source.text_chars,
            "source_hash": source.source_hash,
            "source_path": _relative(source.path, self.legacy_root),
        }
