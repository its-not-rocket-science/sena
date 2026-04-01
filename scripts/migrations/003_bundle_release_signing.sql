ALTER TABLE bundles ADD COLUMN release_manifest_path TEXT;
ALTER TABLE bundles ADD COLUMN signature_verification_strict INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bundles ADD COLUMN signature_verified INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bundles ADD COLUMN signature_error TEXT;
ALTER TABLE bundles ADD COLUMN signature_key_id TEXT;
ALTER TABLE bundles ADD COLUMN signature_verified_at TEXT;
