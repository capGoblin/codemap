CREATE TABLE traces (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    entry TEXT NOT NULL,
    commit_sha TEXT,
    dirty INTEGER NOT NULL,
    status TEXT NOT NULL,
    mode TEXT NOT NULL,
    created_at TEXT NOT NULL,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0
);

CREATE TABLE nodes (
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    id TEXT NOT NULL,
    level INTEGER NOT NULL,
    parent_id TEXT,
    ord INTEGER NOT NULL,
    title TEXT NOT NULL,
    does TEXT NOT NULL,
    input TEXT NOT NULL,
    output TEXT NOT NULL,
    boundary_reason TEXT NOT NULL,
    anchors TEXT NOT NULL,
    effects TEXT NOT NULL,
    parallel_group INTEGER,
    stale INTEGER NOT NULL DEFAULT 0,
    warnings TEXT NOT NULL,
    PRIMARY KEY (trace_id, id)
);
CREATE INDEX nodes_order ON nodes (trace_id, level, parent_id, ord);

CREATE TABLE edges (
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    PRIMARY KEY (trace_id, source_id, target_id, kind)
);

CREATE TABLE hops (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    hop TEXT NOT NULL
);
CREATE INDEX hops_trace ON hops (trace_id);

CREATE TABLE walk_effects (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    effect TEXT NOT NULL
);
CREATE INDEX walk_effects_trace ON walk_effects (trace_id);

CREATE TABLE events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trace_id TEXT NOT NULL,
    event TEXT NOT NULL
);
CREATE INDEX events_trace ON events (trace_id, id);

CREATE TABLE model_calls (
    key TEXT PRIMARY KEY,
    response TEXT NOT NULL
);

CREATE TABLE symbols (
    content_hash TEXT PRIMARY KEY,
    symbols TEXT NOT NULL
);

CREATE TABLE verdicts (
    key TEXT PRIMARY KEY,
    verdict TEXT NOT NULL,
    evidence TEXT NOT NULL,
    suggested TEXT
);
