"""Non-blocking chapter narration jobs."""

from __future__ import annotations

import asyncio
import threading
import uuid as uuidlib
from pathlib import Path
from typing import Any

from .logging import log_event
from .paths import USER_DATA
from .repository import ProjectNotFoundError, ProjectRepository, utc_now


class TtsService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

    def queue_chapter(
        self, project_uuid: str, chapter_id: int, *, start: bool = True
    ) -> dict[str, Any]:
        project = self.repository.get_project(project_uuid, include_details=True)
        chapter = next(
            (item for item in project["chapters"] if item["id"] == chapter_id),
            None,
        )
        if chapter is None:
            raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
        settings = project.get("tts_settings") or {}
        voice = str(settings.get("voice") or "ru-RU-SvetlanaNeural")
        job_uuid = str(uuidlib.uuid4())
        relative_output = (
            Path(project["project_folder"])
            / "audio"
            / f"chapter-{chapter_id}-{chapter['content_hash'][:12]}.mp3"
        ).as_posix()
        now = utc_now()
        with self.repository.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO tts_jobs(
                    uuid, project_id, chapter_id, status, provider, voice,
                    source_text_hash, output_path, created_at
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?)
                """,
                (
                    job_uuid,
                    project["id"],
                    chapter_id,
                    str(settings.get("provider") or "edge-tts"),
                    voice,
                    chapter["content_hash"],
                    relative_output,
                    now,
                ),
            )
        if start:
            thread = threading.Thread(
                target=self._run,
                args=(job_uuid, project_uuid, chapter, settings, relative_output),
                name=f"bookender-tts-{job_uuid[:8]}",
                daemon=True,
            )
            with self._lock:
                self._threads[job_uuid] = thread
            thread.start()
        log_event(
            "tts_job_queued",
            job_uuid=job_uuid,
            project_uuid=project_uuid,
            chapter_id=chapter_id,
            source_text_hash=chapter["content_hash"],
        )
        return self.get_job(job_uuid)

    def queue_book(self, project_uuid: str) -> list[dict[str, Any]]:
        project = self.repository.get_project(project_uuid, include_details=True)
        jobs = [
            self.queue_chapter(project_uuid, chapter["id"], start=False)
            for chapter in project["chapters"]
            if chapter["content"].strip()
        ]
        if not jobs:
            return []
        batch_id = f"batch-{uuidlib.uuid4()}"
        thread = threading.Thread(
            target=self._run_batch,
            args=(batch_id, [job["uuid"] for job in jobs]),
            name=f"bookender-tts-{batch_id[:14]}",
            daemon=True,
        )
        with self._lock:
            self._threads[batch_id] = thread
        thread.start()
        log_event(
            "tts_book_queued",
            batch_id=batch_id,
            project_uuid=project_uuid,
            chapter_count=len(jobs),
        )
        return jobs

    def get_job(self, job_uuid: str) -> dict[str, Any]:
        with self.repository.database.connect() as connection:
            row = connection.execute(
                """
                SELECT j.*, p.uuid AS project_uuid
                FROM tts_jobs j JOIN projects p ON p.id=j.project_id
                WHERE j.uuid=?
                """,
                (job_uuid,),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError(f"tts-job/{job_uuid}")
            return dict(row)

    def list_jobs(self, project_uuid: str) -> list[dict[str, Any]]:
        with self.repository.database.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT j.* FROM tts_jobs j
                    JOIN projects p ON p.id=j.project_id
                    WHERE p.uuid=? ORDER BY j.created_at DESC
                    """,
                    (project_uuid,),
                ).fetchall()
            ]

    def _run(
        self,
        job_uuid: str,
        project_uuid: str,
        chapter: dict[str, Any],
        settings: dict[str, Any],
        relative_output: str,
    ) -> None:
        output = USER_DATA / relative_output
        output.parent.mkdir(parents=True, exist_ok=True)
        with self.repository.database.transaction() as connection:
            connection.execute(
                "UPDATE tts_jobs SET status='running', started_at=? WHERE uuid=?",
                (utc_now(), job_uuid),
            )
        try:
            import edge_tts

            communicate = edge_tts.Communicate(
                chapter["content"],
                str(settings.get("voice") or "ru-RU-SvetlanaNeural"),
                rate=str(settings.get("rate") or "+0%"),
                volume=str(settings.get("volume") or "+0%"),
                pitch=str(settings.get("pitch") or "+0Hz"),
            )
            asyncio.run(communicate.save(str(output)))
            now = utc_now()
            with self.repository.database.transaction() as connection:
                project = connection.execute(
                    "SELECT id FROM projects WHERE uuid=?", (project_uuid,)
                ).fetchone()
                connection.execute(
                    """
                    INSERT INTO audio_assets(
                        project_id, chapter_id, file_path, generation_status,
                        voice, source_text_hash, created_at, updated_at
                    ) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?)
                    ON CONFLICT(project_id, file_path) DO UPDATE SET
                        generation_status='ready',
                        source_text_hash=excluded.source_text_hash,
                        updated_at=excluded.updated_at
                    """,
                    (
                        project["id"],
                        chapter["id"],
                        relative_output,
                        str(settings.get("voice") or "ru-RU-SvetlanaNeural"),
                        chapter["content_hash"],
                        now,
                        now,
                    ),
                )
                connection.execute(
                    """
                    UPDATE tts_jobs
                    SET status='done', finished_at=?, error=''
                    WHERE uuid=?
                    """,
                    (now, job_uuid),
                )
            log_event(
                "tts_job_finished",
                job_uuid=job_uuid,
                project_uuid=project_uuid,
                chapter_id=chapter["id"],
            )
        except Exception as exc:
            with self.repository.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE tts_jobs
                    SET status='failed', finished_at=?, error=?
                    WHERE uuid=?
                    """,
                    (utc_now(), str(exc), job_uuid),
                )
            log_event(
                "tts_job_failed",
                job_uuid=job_uuid,
                project_uuid=project_uuid,
                chapter_id=chapter["id"],
                error=str(exc),
            )
        finally:
            with self._lock:
                self._threads.pop(job_uuid, None)

    def _run_batch(self, batch_id: str, job_uuids: list[str]) -> None:
        try:
            for job_uuid in job_uuids:
                self._run_from_database(job_uuid)
        finally:
            with self._lock:
                self._threads.pop(batch_id, None)

    def _run_from_database(self, job_uuid: str) -> None:
        job = self.get_job(job_uuid)
        project = self.repository.get_project(
            job["project_uuid"], include_details=True
        )
        chapter = next(
            item for item in project["chapters"] if item["id"] == job["chapter_id"]
        )
        self._run(
            job_uuid,
            job["project_uuid"],
            chapter,
            project.get("tts_settings") or {},
            job["output_path"],
        )
