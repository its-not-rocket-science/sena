CREATE UNIQUE INDEX IF NOT EXISTS idx_bundles_one_active_per_name
    ON bundles(name)
    WHERE lifecycle = 'active';
