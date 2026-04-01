ALTER TABLE bundle_history ADD COLUMN policy_diff_summary TEXT;
ALTER TABLE bundle_history ADD COLUMN evidence_json TEXT;
ALTER TABLE bundle_history ADD COLUMN break_glass INTEGER NOT NULL DEFAULT 0;
ALTER TABLE bundle_history ADD COLUMN audit_marker TEXT;
