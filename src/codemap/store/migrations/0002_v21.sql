ALTER TABLE nodes ADD COLUMN summary TEXT NOT NULL DEFAULT '';

CREATE TABLE node_details (
    trace_id TEXT NOT NULL REFERENCES traces(id) ON DELETE CASCADE,
    node_id TEXT NOT NULL,
    explain TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (trace_id, node_id)
);
