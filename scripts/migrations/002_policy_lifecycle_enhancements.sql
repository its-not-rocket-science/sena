ALTER TABLE bundles ADD COLUMN release_id TEXT;
ALTER TABLE bundles ADD COLUMN created_by TEXT NOT NULL DEFAULT 'system';
ALTER TABLE bundles ADD COLUMN creation_reason TEXT;
ALTER TABLE bundles ADD COLUMN promoted_at TEXT;
ALTER TABLE bundles ADD COLUMN promoted_by TEXT;
ALTER TABLE bundles ADD COLUMN promotion_reason TEXT;
ALTER TABLE bundles ADD COLUMN source_bundle_id INTEGER;
ALTER TABLE bundles ADD COLUMN integrity_digest TEXT;
ALTER TABLE bundles ADD COLUMN compatibility_notes TEXT;
ALTER TABLE bundles ADD COLUMN release_notes TEXT;
ALTER TABLE bundles ADD COLUMN migration_notes TEXT;
ALTER TABLE bundles ADD COLUMN validation_artifact TEXT;

UPDATE bundles SET release_id = version WHERE release_id IS NULL;
UPDATE bundles SET integrity_digest = '' WHERE integrity_digest IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_bundles_name_version ON bundles(name, version);
CREATE INDEX IF NOT EXISTS idx_bundles_name_release_id ON bundles(name, release_id);

CREATE TABLE IF NOT EXISTS bundle_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bundle_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    from_lifecycle TEXT,
    to_lifecycle TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    replaced_bundle_id INTEGER,
    validation_artifact TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (bundle_id) REFERENCES bundles(id) ON DELETE CASCADE,
    FOREIGN KEY (replaced_bundle_id) REFERENCES bundles(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_bundle_history_bundle_id ON bundle_history(bundle_id);
CREATE INDEX IF NOT EXISTS idx_bundle_history_created_at ON bundle_history(created_at);
