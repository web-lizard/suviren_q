"""Project-aware Edge TTS voices, previews, and versioned narration jobs."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import re
import shutil
import subprocess
import threading
import time
import uuid as uuidlib
from pathlib import Path
from typing import Any, Callable

from .logging import log_event
from .paths import USER_DATA
from .repository import ProjectNotFoundError, ProjectRepository, utc_now


DEFAULT_VOICE = "ru-RU-SvetlanaNeural"
TTS_CHUNK_LIMIT = 2_400
RATE_PATTERN = re.compile(r"^[+-](?:100|[0-9]{1,2})%$")
PITCH_PATTERN = re.compile(r"^[+-](?:[0-9]{1,3})Hz$")
VOLUME_PATTERN = re.compile(r"^[+-](?:100|[0-9]{1,2})%$")
RATE_VALUES = {"-25%", "-10%", "+0%", "+15%", "+30%"}
PITCH_VALUES = {"-40Hz", "-25Hz", "-10Hz", "+0Hz", "+10Hz", "+25Hz", "+40Hz"}
TTS_UNAVAILABLE_MESSAGE = (
    "Модуль озвучки не запущен. Проверьте установку компонентов TTS."
)
TTS_FAILED_MESSAGE = (
    "Не удалось создать озвучку. Проверьте подключение к интернету и повторите."
)
FALLBACK_VOICES = [
    {
        "id": "ru-RU-DmitryNeural",
        "name": "Дмитрий",
        "friendly_name": "Microsoft Dmitry Online (Natural) - Russian (Russia)",
        "language": "ru",
        "locale": "ru-RU",
        "region": "RU",
        "gender": "Male",
        "suggested": True,
    },
    {
        "id": "ru-RU-SvetlanaNeural",
        "name": "Светлана",
        "friendly_name": "Microsoft Svetlana Online (Natural) - Russian (Russia)",
        "language": "ru",
        "locale": "ru-RU",
        "region": "RU",
        "gender": "Female",
        "suggested": True,
    },
]


class TtsUnavailableError(RuntimeError):
    """Raised when the configured TTS runtime cannot be imported."""


class TtsService:
    def __init__(self, repository: ProjectRepository) -> None:
        self.repository = repository
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()
        self._voice_cache: tuple[float, list[dict[str, Any]]] | None = None
        self._recover_interrupted_jobs()

    def _recover_interrupted_jobs(self) -> None:
        try:
            with self.repository.database.transaction() as connection:
                result = connection.execute(
                    """
                    UPDATE tts_jobs
                    SET status='failed', progress=0, finished_at=?,
                        error='TTS worker stopped before completion',
                        user_error='Предыдущая задача озвучки была прервана. Запустите её повторно.'
                    WHERE status IN ('queued', 'running')
                    """,
                    (utc_now(),),
                )
            if result.rowcount:
                log_event("tts_interrupted_jobs_recovered", count=result.rowcount)
        except Exception as exc:
            log_event("tts_job_recovery_failed", error=repr(exc))

    def dependency_status(self) -> dict[str, Any]:
        spec = importlib.util.find_spec("edge_tts")
        if spec is None:
            return {
                "available": False,
                "provider": "edge-tts",
                "message": TTS_UNAVAILABLE_MESSAGE,
            }
        try:
            import edge_tts

            version = getattr(edge_tts, "__version__", "")
        except Exception as exc:
            log_event("tts_startup_check_failed", error=repr(exc))
            return {
                "available": False,
                "provider": "edge-tts",
                "message": TTS_UNAVAILABLE_MESSAGE,
            }
        return {
            "available": True,
            "provider": "edge-tts",
            "version": version,
            "message": "Компонент озвучки готов.",
        }

    def require_available(self) -> None:
        status = self.dependency_status()
        if not status["available"]:
            log_event("tts_runtime_unavailable", status=status)
            raise TtsUnavailableError(TTS_UNAVAILABLE_MESSAGE)

    def normalize_settings(self, settings: dict[str, Any]) -> dict[str, str]:
        return self._normalized_settings(settings)

    def list_voices(self, *, refresh: bool = False) -> list[dict[str, Any]]:
        self.require_available()
        now = time.monotonic()
        if not refresh and self._voice_cache and now - self._voice_cache[0] < 21_600:
            return self._voice_cache[1]
        try:
            import edge_tts

            raw_voices = asyncio.run(edge_tts.list_voices())
            voices = []
            for raw in raw_voices:
                short_name = str(raw.get("ShortName") or "").strip()
                locale = str(raw.get("Locale") or "").strip()
                if not short_name:
                    continue
                language, _, region = locale.partition("-")
                technical_name = short_name.split("-", 2)[-1]
                for suffix in ("MultilingualNeural", "Neural"):
                    if technical_name.endswith(suffix):
                        technical_name = technical_name[: -len(suffix)]
                        break
                localized_names = {
                    "ru-RU-DmitryNeural": "Дмитрий",
                    "ru-RU-SvetlanaNeural": "Светлана",
                }
                display_name = localized_names.get(short_name, technical_name)
                voices.append(
                    {
                        "id": short_name,
                        "name": str(display_name),
                        "friendly_name": str(raw.get("FriendlyName") or ""),
                        "language": language,
                        "locale": locale,
                        "region": region,
                        "gender": str(raw.get("Gender") or ""),
                        "suggested": locale.casefold().startswith("ru-"),
                    }
                )
            voices.sort(
                key=lambda voice: (
                    not voice["suggested"],
                    voice["language"].casefold(),
                    voice["name"].casefold(),
                )
            )
            self._voice_cache = (now, voices)
            log_event("tts_voices_loaded", count=len(voices))
            return voices
        except Exception as exc:
            log_event("tts_voice_list_failed", error=repr(exc))
            voices = [dict(voice) for voice in FALLBACK_VOICES]
            self._voice_cache = (now, voices)
            return voices

    def preview(
        self, project_uuid: str, text: str, settings: dict[str, Any]
    ) -> dict[str, Any]:
        self.require_available()
        project = self.repository.get_project(project_uuid, include_details=True)
        clean_text = " ".join(str(text or "").split())[:500]
        if not clean_text:
            clean_text = (
                "Это короткая проба голоса Bookender Studio. "
                "Вы можете изменить скорость и высоту тона."
            )
        normalized = self._normalized_settings(settings)
        relative_output = (
            Path(project["project_folder"])
            / "temp"
            / f"voice-preview-{uuidlib.uuid4().hex}.mp3"
        ).as_posix()
        output = self._absolute_project_path(project, relative_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._synthesize(clean_text, output, normalized)
        except Exception as exc:
            output.unlink(missing_ok=True)
            log_event(
                "tts_preview_failed",
                project_uuid=project_uuid,
                voice=normalized["voice"],
                error=repr(exc),
            )
            raise RuntimeError(TTS_FAILED_MESSAGE) from exc
        result = {
            "file_path": relative_output,
            "voice": normalized["voice"],
            "rate": normalized["rate"],
            "pitch": normalized["pitch"],
            "volume": normalized["volume"],
            "duration": self._audio_duration(output),
            "file_size": output.stat().st_size,
            "temporary": True,
        }
        log_event(
            "tts_preview_ready",
            project_uuid=project_uuid,
            voice=normalized["voice"],
            file_size=result["file_size"],
        )
        return result

    def queue_chapter(
        self, project_uuid: str, chapter_id: int, *, start: bool = True
    ) -> dict[str, Any]:
        self.require_available()
        project = self.repository.get_project(project_uuid, include_details=True)
        chapter = next(
            (item for item in project["chapters"] if item["id"] == chapter_id),
            None,
        )
        if chapter is None:
            raise ProjectNotFoundError(f"{project_uuid}/chapter/{chapter_id}")
        if not chapter["content"].strip():
            raise ValueError("Пустую главу нельзя озвучить.")
        settings = self._normalized_settings(project.get("tts_settings") or {})
        job_uuid = str(uuidlib.uuid4())
        with self.repository.database.connect() as connection:
            version_number = int(
                connection.execute(
                    """
                    SELECT COALESCE(MAX(version_number), 0) + 1
                    FROM audio_assets
                    WHERE project_id=? AND chapter_id=?
                    """,
                    (project["id"], chapter_id),
                ).fetchone()[0]
            )
        relative_output = (
            Path(project["project_folder"])
            / "audio"
            / (
                f"chapter-{chapter_id}-v{version_number:03d}-"
                f"{chapter['content_hash'][:8]}-{job_uuid[:8]}.mp3"
            )
        ).as_posix()
        now = utc_now()
        with self.repository.database.transaction() as connection:
            connection.execute(
                """
                INSERT INTO tts_jobs(
                    uuid, project_id, chapter_id, status, provider, voice,
                    source_text_hash, output_path, created_at, job_kind, progress,
                    progress_done, progress_total
                ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, 'chapter', 0, 0, ?)
                """,
                (
                    job_uuid,
                    project["id"],
                    chapter_id,
                    settings["provider"],
                    settings["voice"],
                    chapter["content_hash"],
                    relative_output,
                    now,
                    len(self._split_text_chunks(chapter["content"])),
                ),
            )
        if start:
            thread = threading.Thread(
                target=self._run,
                args=(
                    job_uuid,
                    project_uuid,
                    chapter,
                    settings,
                    relative_output,
                    version_number,
                ),
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
            version_number=version_number,
        )
        return self.get_job(job_uuid)

    def queue_book(self, project_uuid: str) -> list[dict[str, Any]]:
        self.require_available()
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

    def build_video_master(self, project_uuid: str) -> dict[str, Any]:
        project = self.repository.get_project(project_uuid, include_details=True)
        audio_by_chapter: dict[int, dict[str, Any]] = {}
        for asset in project.get("audio_assets", []):
            chapter_id = int(asset.get("chapter_id") or 0)
            if not chapter_id:
                continue
            current = audio_by_chapter.get(chapter_id)
            asset_rank = (
                int(bool(asset.get("is_active"))),
                int(asset.get("version_number") or 0),
                int(asset["id"]),
            )
            current_rank = (
                int(bool(current and current.get("is_active"))),
                int((current or {}).get("version_number") or 0),
                int((current or {}).get("id") or 0),
            )
            if current is None or asset_rank > current_rank:
                audio_by_chapter[chapter_id] = asset

        selected: list[tuple[dict[str, Any], dict[str, Any], Path, float]] = []
        missing_chapter_ids: list[int] = []
        for chapter in project.get("chapters", []):
            asset = audio_by_chapter.get(int(chapter["id"]))
            if not asset or not asset.get("file_path"):
                missing_chapter_ids.append(int(chapter["id"]))
                continue
            path = self._absolute_project_path(project, str(asset["file_path"]))
            if not path.is_file():
                missing_chapter_ids.append(int(chapter["id"]))
                continue
            duration = float(asset.get("duration") or self._audio_duration(path) or 0)
            if duration <= 0:
                raise RuntimeError(f"Cannot determine duration of {path.name}")
            selected.append((chapter, asset, path, duration))
        if not selected:
            raise ValueError("У книги пока нет готовых озвучек для передачи в видео.")

        source_fingerprint = "|".join(
            f"{asset['id']}:{path.stat().st_size}:{path.stat().st_mtime_ns}"
            for _, asset, path, _ in selected
        )
        digest = uuidlib.uuid5(uuidlib.NAMESPACE_URL, source_fingerprint).hex[:12]
        if len(selected) == 1:
            relative_output = str(selected[0][1]["file_path"])
            output = selected[0][2]
        else:
            relative_output = (
                Path(project["project_folder"])
                / "video"
                / f"book-master-{digest}.mp3"
            ).as_posix()
            output = self._absolute_project_path(project, relative_output)
            output.parent.mkdir(parents=True, exist_ok=True)
            if not output.is_file() or output.stat().st_size <= 0:
                self._concat_mp3_files([item[2] for item in selected], output)

        cursor = 0.0
        chapters = []
        for chapter, asset, _, chapter_duration in selected:
            start = cursor
            cursor += chapter_duration
            chapters.append(
                {
                    "chapter_id": int(chapter["id"]),
                    "title": chapter["title"],
                    "text": chapter["content"],
                    "audio_asset_id": int(asset["id"]),
                    "start_seconds": round(start, 3),
                    "end_seconds": round(cursor, 3),
                    "duration_seconds": round(chapter_duration, 3),
                }
            )
        result = {
            "file_path": relative_output,
            "file_size": output.stat().st_size,
            "duration": round(cursor, 3),
            "chapters": chapters,
            "missing_chapter_ids": missing_chapter_ids,
            "source_asset_ids": [int(item[1]["id"]) for item in selected],
        }
        log_event(
            "book_video_master_ready",
            project_uuid=project_uuid,
            chapter_count=len(chapters),
            missing_chapter_count=len(missing_chapter_ids),
            output_path=relative_output,
            duration=result["duration"],
        )
        return result

    def _run(
        self,
        job_uuid: str,
        project_uuid: str,
        chapter: dict[str, Any],
        settings: dict[str, Any],
        relative_output: str,
        version_number: int,
    ) -> None:
        project_record = self.repository.get_project(
            project_uuid, include_details=False
        )
        output = self._absolute_project_path(project_record, relative_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with self.repository.database.transaction() as connection:
            connection.execute(
                """
                UPDATE tts_jobs
                SET status='running', progress=0.02, progress_done=0, started_at=?
                WHERE uuid=?
                """,
                (utc_now(), job_uuid),
            )
        try:
            last_saved_progress = 0.0
            chapter_chunk_count = len(self._split_text_chunks(chapter["content"]))

            def save_progress(
                completed: int, total: int, fraction: float
            ) -> None:
                nonlocal last_saved_progress
                progress = min(0.94, max(0.02, 0.02 + fraction * 0.92))
                if progress < 0.94 and progress - last_saved_progress < 0.015:
                    return
                last_saved_progress = progress
                with self.repository.database.transaction() as connection:
                    connection.execute(
                        """
                        UPDATE tts_jobs
                        SET progress=?, progress_done=?, progress_total=?
                        WHERE uuid=? AND status='running'
                        """,
                        (progress, completed, max(1, total), job_uuid),
                    )

            self._synthesize(
                chapter["content"],
                output,
                settings,
                progress_callback=save_progress,
            )
            save_progress(
                chapter_chunk_count,
                chapter_chunk_count,
                1.0,
            )
            duration = self._audio_duration(output)
            now = utc_now()
            with self.repository.database.transaction() as connection:
                project = connection.execute(
                    "SELECT id FROM projects WHERE uuid=?", (project_uuid,)
                ).fetchone()
                connection.execute(
                    """
                    UPDATE audio_assets SET is_active=0
                    WHERE project_id=? AND chapter_id=?
                    """,
                    (project["id"], chapter["id"]),
                )
                connection.execute(
                    """
                    INSERT INTO audio_assets(
                        project_id, chapter_id, file_path, generation_status,
                        voice, source_text_hash, created_at, updated_at,
                        title, rate, pitch, volume, version_number, is_active,
                        duration, file_size, metadata_json
                    ) VALUES (?, ?, ?, 'ready', ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                    """,
                    (
                        project["id"],
                        chapter["id"],
                        relative_output,
                        settings["voice"],
                        chapter["content_hash"],
                        now,
                        now,
                        f"{chapter['title']} · версия {version_number}",
                        settings["rate"],
                        settings["pitch"],
                        settings["volume"],
                        version_number,
                        duration,
                        output.stat().st_size,
                        json.dumps({"provider": settings["provider"]}),
                    ),
                )
                connection.execute(
                    """
                    UPDATE tts_jobs
                    SET status='done', progress=1,
                        progress_done=progress_total, finished_at=?,
                        error='', user_error=''
                    WHERE uuid=?
                    """,
                    (now, job_uuid),
                )
            log_event(
                "tts_job_finished",
                job_uuid=job_uuid,
                project_uuid=project_uuid,
                chapter_id=chapter["id"],
                output_path=relative_output,
                file_size=output.stat().st_size,
                duration=duration,
            )
        except Exception as exc:
            try:
                output.unlink(missing_ok=True)
            except OSError:
                pass
            user_error = (
                TTS_UNAVAILABLE_MESSAGE
                if isinstance(exc, (ImportError, ModuleNotFoundError, TtsUnavailableError))
                else TTS_FAILED_MESSAGE
            )
            with self.repository.database.transaction() as connection:
                connection.execute(
                    """
                    UPDATE tts_jobs
                    SET status='failed', progress=0, finished_at=?,
                        error=?, user_error=?
                    WHERE uuid=?
                    """,
                    (utc_now(), repr(exc), user_error, job_uuid),
                )
            log_event(
                "tts_job_failed",
                job_uuid=job_uuid,
                project_uuid=project_uuid,
                chapter_id=chapter["id"],
                error=repr(exc),
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
        version_number = int(
            Path(job["output_path"]).stem.split("-v", 1)[1].split("-", 1)[0]
        )
        self._run(
            job_uuid,
            job["project_uuid"],
            chapter,
            self._normalized_settings(project.get("tts_settings") or {}),
            job["output_path"],
            version_number,
        )

    @staticmethod
    def _normalized_settings(settings: dict[str, Any]) -> dict[str, str]:
        values = {
            "voice": str(settings.get("voice") or DEFAULT_VOICE).strip(),
            "rate": str(settings.get("rate") or "+0%").strip(),
            "pitch": str(settings.get("pitch") or "+0Hz").strip(),
            "volume": str(settings.get("volume") or "+0%").strip(),
            "provider": str(settings.get("provider") or "edge-tts").strip(),
        }
        if not RATE_PATTERN.fullmatch(values["rate"]) or values["rate"] not in RATE_VALUES:
            raise ValueError("Выбрано некорректное значение скорости речи.")
        if not PITCH_PATTERN.fullmatch(values["pitch"]) or values["pitch"] not in PITCH_VALUES:
            raise ValueError("Выбрано некорректное значение высоты тона.")
        if not VOLUME_PATTERN.fullmatch(values["volume"]):
            raise ValueError("Выбрано некорректное значение громкости.")
        if values["provider"] != "edge-tts":
            raise ValueError("Выбран неподдерживаемый TTS-провайдер.")
        return values

    @classmethod
    def _synthesize(
        cls,
        text: str,
        output: Path,
        settings: dict[str, str],
        progress_callback: Callable[[int, int, float], None] | None = None,
    ) -> None:
        chunks = cls._split_text_chunks(text)
        total = len(chunks)

        def report(completed: int, local_fraction: float = 0.0) -> None:
            if progress_callback is None:
                return
            overall = min(1.0, max(0.0, (completed + local_fraction) / total))
            progress_callback(completed, total, overall)

        report(0)
        if len(chunks) == 1:
            cls._synthesize_chunk(
                chunks[0],
                output,
                settings,
                progress_callback=lambda fraction: report(0, fraction),
            )
            report(1)
            return

        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required to join long TTS chapters")
        token = uuidlib.uuid4().hex
        parts = [
            output.with_name(f".{output.stem}-{token}-{index:04d}.mp3")
            for index in range(len(chunks))
        ]
        concat_file = output.with_name(f".{output.stem}-{token}-concat.txt")
        try:
            for index, (chunk, part) in enumerate(zip(chunks, parts)):
                cls._synthesize_chunk(
                    chunk,
                    part,
                    settings,
                    progress_callback=lambda fraction, done=index: report(
                        done, fraction
                    ),
                )
                report(index + 1)
            cls._concat_mp3_files(parts, output, concat_file=concat_file)
        finally:
            concat_file.unlink(missing_ok=True)
            for part in parts:
                part.unlink(missing_ok=True)

    @staticmethod
    def _concat_mp3_files(
        parts: list[Path],
        output: Path,
        *,
        concat_file: Path | None = None,
    ) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg is required to join audio files")
        owned_concat_file = concat_file is None
        concat_file = concat_file or output.with_name(
            f".{output.stem}-{uuidlib.uuid4().hex}-concat.txt"
        )
        try:
            concat_file.write_text(
                "\n".join(
                    f"file '{part.resolve().as_posix().replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                    for part in parts
                )
                + "\n",
                encoding="utf-8",
            )
            command = [
                ffmpeg,
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(output),
            ]
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(120, len(parts) * 30),
            )
            if result.returncode or not output.is_file() or output.stat().st_size <= 0:
                raise RuntimeError(
                    f"FFmpeg could not join audio files: {(result.stderr or result.stdout)[-800:]}"
                )
        finally:
            if owned_concat_file:
                concat_file.unlink(missing_ok=True)

    @staticmethod
    def _split_text_chunks(text: str, limit: int = TTS_CHUNK_LIMIT) -> list[str]:
        clean = str(text or "").strip()
        if not clean:
            return [""]
        chunks: list[str] = []
        while len(clean) > limit:
            minimum = max(1, int(limit * 0.55))
            window = clean[: limit + 1]
            candidates = [
                window.rfind(separator, minimum, limit + 1)
                for separator in ("\n\n", ". ", "! ", "? ", "; ", ", ", " ")
            ]
            cut = max(candidates)
            if cut < minimum:
                cut = limit
            elif window[cut : cut + 2] in {". ", "! ", "? ", "; ", ", "}:
                cut += 1
            chunk = clean[:cut].strip()
            if chunk:
                chunks.append(chunk)
            clean = clean[cut:].strip()
        if clean:
            chunks.append(clean)
        return chunks or [""]

    @staticmethod
    def _synthesize_chunk(
        text: str,
        output: Path,
        settings: dict[str, str],
        progress_callback: Callable[[float], None] | None = None,
    ) -> None:
        import edge_tts

        async def stream_to_file(communicate: Any) -> None:
            spoken_characters = 0
            with output.open("wb") as audio:
                async for message in communicate.stream():
                    if message["type"] == "audio":
                        audio.write(message["data"])
                    elif message["type"] in {"WordBoundary", "SentenceBoundary"}:
                        spoken_characters += len(str(message.get("text") or "")) + 1
                        if progress_callback:
                            progress_callback(
                                min(0.97, spoken_characters / max(1, len(text)))
                            )
                audio.flush()

        last_error: Exception | None = None
        for attempt in range(3):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    settings["voice"],
                    rate=settings["rate"],
                    volume=settings["volume"],
                    pitch=settings["pitch"],
                    boundary="SentenceBoundary",
                )
                asyncio.run(stream_to_file(communicate))
                if output.is_file() and output.stat().st_size > 0:
                    if progress_callback:
                        progress_callback(1.0)
                    return
                raise RuntimeError("TTS provider did not create an audio file")
            except Exception as exc:
                last_error = exc
                output.unlink(missing_ok=True)
                transient = type(exc).__name__ in {
                    "NoAudioReceived",
                    "ConnectionTimeoutError",
                    "WSServerHandshakeError",
                    "ClientConnectionError",
                }
                if not transient or attempt == 2:
                    raise
                time.sleep(attempt + 1)
        if last_error:
            raise last_error

    @staticmethod
    def _audio_duration(path: Path) -> float | None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe,
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=20,
            )
            value = float(result.stdout.strip()) if result.returncode == 0 else 0
            return round(value, 3) if value > 0 else None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    @staticmethod
    def _absolute_project_path(project: dict[str, Any], relative_path: str) -> Path:
        projects_root = (USER_DATA / "projects").resolve()
        project_root = (USER_DATA / project["project_folder"]).resolve()
        output = (USER_DATA / relative_path).resolve()
        try:
            project_root.relative_to(projects_root)
            output.relative_to(project_root)
        except ValueError as exc:
            raise ValueError("Некорректный путь файла озвучки.") from exc
        return output
