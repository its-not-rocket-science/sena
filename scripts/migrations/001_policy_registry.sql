CREATE TABLE IF NOT EXISTS bundles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bundles_name_lifecycle_created
    ON bundles(name, lifecycle, created_at);

CREATE TABLE IF NOT EXISTS rules (
    bundle_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (bundle_id, rule_id),
    FOREIGN KEY (bundle_id) REFERENCES bundles(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_rules_bundle_id ON rules(bundle_id);
