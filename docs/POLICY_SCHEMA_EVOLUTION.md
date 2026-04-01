# Policy Schema Evolution

SENA now treats policy bundle schema evolution as a managed process.

## Why this exists

Policy bundles are long-lived artifacts. Without explicit schema/version migration tooling, teams end up hand-editing YAML and risking accidental runtime breakage.

This document describes:

- explicit bundle schema versioning,
- migration workflows,
- compatibility verification,
- deprecation warnings and operator actions.

## Schema versions

Current supported bundle schema versions:

- `1` (supported but deprecated)
- `2` (current)

Manifest field:

```yaml
schema_version: "2"
```

### Schema v2 additions

Schema v2 formalizes runtime compatibility metadata:

```yaml
runtime_compatibility:
  min_evaluator_version: "0.3.0"
  max_evaluator_version: "1.0.0"
```

## CLI commands

### Inspect schema version

```bash
python -m sena.cli.main policy schema-version --policy-dir ./policies
```

Output includes bundle schema version and deprecation warnings.

### Dry-run migration

```bash
python -m sena.cli.main policy migrate --policy-dir ./policies --dry-run
```

Dry-run output includes per-file unified diffs so operators can review exact changes before writing.

### Apply migration

```bash
python -m sena.cli.main policy migrate --policy-dir ./policies
```

### Verify runtime compatibility

```bash
python -m sena.cli.main policy verify-compatibility --policy-dir ./policies
```

Optional override:

```bash
python -m sena.cli.main policy verify-compatibility \
  --policy-dir ./policies \
  --runtime-version 0.4.1
```

## Migration behavior

Migration v1 -> v2 performs deterministic transformations:

1. Sets `schema_version` to `"2"`.
2. Adds default `runtime_compatibility` if missing.
3. Migrates deprecated rule field `action` to `applies_to` (single-item list) when encountered.

## Deprecation warnings

If a bundle uses schema version `1`, SENA surfaces a warning that schema v1 is deprecated and should be migrated.

## Operator guidance

Recommended rollout:

1. Run `policy schema-version` across all bundles.
2. Run `policy migrate --dry-run` and attach outputs to change review.
3. Apply `policy migrate` in a branch and commit generated diffs.
4. Run `policy verify-compatibility` in CI using your target runtime version.
5. Validate behavior using `policy test` and scenario simulation before promotion.

This turns policy evolution into an auditable, repeatable process instead of manual edits.
