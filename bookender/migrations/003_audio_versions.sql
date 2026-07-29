ALTER TABLE audio_assets ADD COLUMN title TEXT NOT NULL DEFAULT '';
ALTER TABLE audio_assets ADD COLUMN rate TEXT NOT NULL DEFAULT '+0%';
ALTER TABLE audio_assets ADD COLUMN pitch TEXT NOT NULL DEFAULT '+0Hz';
ALTER TABLE audio_assets ADD COLUMN volume TEXT NOT NULL DEFAULT '+0%';
ALTER TABLE audio_assets ADD COLUMN version_number INTEGER NOT NULL DEFAULT 1;
ALTER TABLE audio_assets ADD COLUMN is_active INTEGER NOT NULL DEFAULT 0;
ALTER TABLE audio_assets ADD COLUMN file_size INTEGER NOT NULL DEFAULT 0;
ALTER TABLE audio_assets ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

ALTER TABLE tts_jobs ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'chapter';
ALTER TABLE tts_jobs ADD COLUMN progress REAL NOT NULL DEFAULT 0;
ALTER TABLE tts_jobs ADD COLUMN user_error TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_audio_chapter_created
    ON audio_assets(project_id, chapter_id, created_at DESC);
CREATE INDEX idx_audio_chapter_active
    ON audio_assets(project_id, chapter_id, is_active);
