CREATE TABLE IF NOT EXISTS bundles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    lifecycle TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rules (
    bundle_id INTEGER NOT NULL,
    rule_id TEXT NOT NULL,
    hash TEXT NOT NULL,
    content TEXT NOT NULL,
    PRIMARY KEY (bundle_id, rule_id)
);

INSERT INTO bundles (id, name, version, lifecycle, created_at)
VALUES (1, 'enterprise-demo', '2025.09', 'active', '2025-09-15T00:00:00+00:00');

INSERT INTO rules (bundle_id, rule_id, hash, content)
VALUES
(
  1,
  'allow_small_legacy',
  'legacyhash1',
  '{"id":"allow_small_legacy","description":"allow","severity":"low","inviolable":false,"applies_to":["approve_vendor_payment"],"condition":{"field":"amount","lt":500},"decision":"ALLOW","reason":"legacy"}'
),
(
  1,
  'block_unverified_legacy',
  'legacyhash2',
  '{"id":"block_unverified_legacy","description":"block","severity":"high","inviolable":true,"applies_to":["approve_vendor_payment"],"condition":{"field":"amount","gte":500},"decision":"BLOCK","reason":"legacy"}'
);
