CREATE TABLE tts_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'queued',
    provider TEXT NOT NULL DEFAULT 'edge-tts',
    voice TEXT NOT NULL DEFAULT '',
    source_text_hash TEXT NOT NULL,
    output_path TEXT NOT NULL,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE backup_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    backup_path TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX idx_tts_jobs_project_status ON tts_jobs(project_id, status);
