-- Persistent cursor and run timestamps for the independent catalog refresh worker.
CREATE TABLE IF NOT EXISTS sh_refresh_scheduler (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    product_cursor INTEGER NOT NULL DEFAULT 0 CHECK (product_cursor >= 0),
    last_started_at TIMESTAMPTZ,
    last_finished_at TIMESTAMPTZ,
    last_error TEXT
);
