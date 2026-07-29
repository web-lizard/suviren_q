CREATE TABLE projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    project_kind TEXT NOT NULL CHECK (project_kind IN ('book', 'video', 'hybrid')),
    status TEXT NOT NULL DEFAULT 'active',
    project_folder TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_opened_at TEXT,
    archived_at TEXT,
    deleted_at TEXT
);

CREATE TABLE books (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'ru',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE chapters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    book_id INTEGER NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    legacy_id TEXT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    archived_at TEXT,
    UNIQUE(book_id, position)
);

CREATE TABLE tts_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id) ON DELETE CASCADE,
    voice TEXT NOT NULL DEFAULT '',
    rate TEXT NOT NULL DEFAULT '+0%',
    pitch TEXT NOT NULL DEFAULT '+0Hz',
    volume TEXT NOT NULL DEFAULT '+0%',
    provider TEXT NOT NULL DEFAULT 'edge-tts',
    settings_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE audio_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    duration REAL,
    generation_status TEXT NOT NULL DEFAULT 'ready',
    voice TEXT NOT NULL DEFAULT '',
    source_text_hash TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, file_path)
);

CREATE TABLE visual_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    file_path TEXT NOT NULL,
    asset_type TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE(project_id, file_path)
);

CREATE TABLE video_editions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    edition_kind TEXT NOT NULL DEFAULT 'audiobook',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE timeline_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_edition_id INTEGER NOT NULL REFERENCES video_editions(id) ON DELETE CASCADE,
    chapter_id INTEGER REFERENCES chapters(id) ON DELETE SET NULL,
    asset_id INTEGER,
    item_type TEXT NOT NULL,
    track TEXT NOT NULL,
    start_time REAL NOT NULL DEFAULT 0,
    end_time REAL NOT NULL DEFAULT 0,
    position INTEGER NOT NULL,
    settings_json TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE project_settings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    namespace TEXT NOT NULL,
    key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    UNIQUE(project_id, namespace, key)
);

CREATE TABLE legacy_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_identifier TEXT NOT NULL,
    destination_project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    source_hash TEXT NOT NULL,
    destination_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'imported',
    details_json TEXT NOT NULL DEFAULT '{}',
    imported_at TEXT NOT NULL,
    import_version INTEGER NOT NULL,
    UNIQUE(source_type, source_identifier)
);

CREATE TABLE app_state (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX idx_projects_updated ON projects(updated_at DESC);
CREATE INDEX idx_chapters_book_position ON chapters(book_id, position);
CREATE INDEX idx_audio_project_chapter ON audio_assets(project_id, chapter_id);
CREATE INDEX idx_video_project ON video_editions(project_id);
CREATE INDEX idx_timeline_edition_position ON timeline_items(video_edition_id, position);
