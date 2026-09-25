SCHEMA_VERSION = 1

MIGRATIONS = {
    1: """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);

CREATE TABLE program (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL,
    slug TEXT NOT NULL,
    description TEXT DEFAULT '',
    created TEXT NOT NULL
);

CREATE TABLE capture_session (
    id INTEGER PRIMARY KEY,
    started TEXT NOT NULL,
    mode TEXT,
    region TEXT,
    note TEXT
);

CREATE TABLE evidence (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL,
    phash TEXT,
    width INTEGER,
    height INTEGER,
    session_id INTEGER REFERENCES capture_session(id) ON DELETE SET NULL,
    captured_at TEXT NOT NULL
);

CREATE TABLE artifact (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    artifact_type TEXT NOT NULL,
    language TEXT DEFAULT '',
    version INTEGER NOT NULL,
    supersedes_id INTEGER REFERENCES artifact(id) ON DELETE SET NULL,
    is_current INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    transcription TEXT DEFAULT '',
    source_path TEXT,
    validation_tool TEXT,
    validation_ok INTEGER,
    validation_errors TEXT,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX ix_artifact_name ON artifact(name, is_current);

CREATE TABLE artifact_evidence (
    artifact_id INTEGER NOT NULL REFERENCES artifact(id) ON DELETE CASCADE,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    ord INTEGER NOT NULL DEFAULT 0,
    region TEXT,
    PRIMARY KEY (artifact_id, evidence_id)
);

CREATE TABLE entity (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES entity(id) ON DELETE SET NULL,
    attrs TEXT NOT NULL DEFAULT '{}',
    artifact_id INTEGER REFERENCES artifact(id) ON DELETE SET NULL,
    line_start INTEGER,
    line_end INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    origin TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX ix_entity_kind ON entity(kind);
CREATE INDEX ix_entity_name ON entity(name COLLATE NOCASE);

CREATE TABLE entity_source (
    entity_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    artifact_id INTEGER NOT NULL REFERENCES artifact(id) ON DELETE CASCADE,
    line_start INTEGER,
    line_end INTEGER
);
CREATE INDEX ix_entity_source ON entity_source(entity_id, artifact_id);

CREATE TABLE relation (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    from_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    to_id INTEGER NOT NULL REFERENCES entity(id) ON DELETE CASCADE,
    attrs TEXT NOT NULL DEFAULT '{}',
    artifact_id INTEGER REFERENCES artifact(id) ON DELETE CASCADE,
    line INTEGER,
    confidence REAL NOT NULL DEFAULT 1.0,
    origin TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX ix_relation_from ON relation(from_id, kind);
CREATE INDEX ix_relation_to ON relation(to_id, kind);

CREATE TABLE evidence_link (
    target_type TEXT NOT NULL,
    target_id INTEGER NOT NULL,
    evidence_id INTEGER NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    region TEXT,
    PRIMARY KEY (target_type, target_id, evidence_id)
);

CREATE TABLE finding (
    id INTEGER PRIMARY KEY,
    target_type TEXT,
    target_id INTEGER,
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT DEFAULT '',
    source TEXT DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    created TEXT NOT NULL
);

CREATE TABLE correction (
    id INTEGER PRIMARY KEY,
    target_type TEXT NOT NULL,
    target_id INTEGER,
    op TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    note TEXT DEFAULT '',
    active INTEGER NOT NULL DEFAULT 1,
    created TEXT NOT NULL
);

CREATE TABLE run (
    id INTEGER PRIMARY KEY,
    step TEXT NOT NULL,
    artifact_id INTEGER REFERENCES artifact(id) ON DELETE SET NULL,
    model TEXT,
    prompt_version TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost REAL,
    ms INTEGER,
    ok INTEGER NOT NULL DEFAULT 1,
    error TEXT,
    created TEXT NOT NULL
);
""",
}


def current_version(db) -> int:
    has_meta = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if not has_meta:
        return 0
    row = db.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    return int(row[0]) if row else 0


def migrate(db) -> int:
    version = current_version(db)
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"program.db schema v{version} is newer than this app (v{SCHEMA_VERSION})")
    for target in range(version + 1, SCHEMA_VERSION + 1):
        db.executescript(
            "BEGIN;" + MIGRATIONS[target]
            + f"INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', '{target}');COMMIT;"
        )
    return SCHEMA_VERSION
