# Bundle Signing and Immutable Release Manifests

SENA policy bundles can now be treated as signed release artifacts instead of mutable folder contents.

## What is signed

Each release uses `release-manifest.json` with:

- `bundle_name` and `version` (bundle identity)
- Per-file digests (`file_digests`)
- Aggregate digest (`aggregate_sha256`)
- Creation timestamp (`created_at`)
- Signer metadata (`signer.key_id`, `signer.algorithm`, `signer.signature`, `signer.signed_at`, optional signer name)
- Optional `compatibility_notes` and `migration_notes`

The signature is computed over a canonical JSON form of the manifest with `signature` and `signed_at` blanked.

## Trust model (explicit)

- Primitive: `HMAC-SHA256` using shared secret keys in a local keyring directory.
- Each trusted signer key is stored as `<key_id>.key`.
- Verification resolves the key by `signer.key_id` from the keyring.
- Strict mode requires a valid signed manifest; relaxed mode permits unsigned bundles for local/dev workflows.
- No hidden trust store: key files and manifest files are explicit inputs.

## Operator workflow

1. Generate manifest:

```bash
python -m sena.cli.main bundle-release generate-manifest \
  --policy-dir ./bundle \
  --output ./bundle/release-manifest.json \
  --key-id ops
```

2. Sign manifest:

```bash
python -m sena.cli.main bundle-release sign-manifest \
  --manifest-path ./bundle/release-manifest.json \
  --key-file ./keyring/ops.key
```

3. Verify manifest:

```bash
python -m sena.cli.main bundle-release verify-manifest \
  --policy-dir ./bundle \
  --manifest-path ./bundle/release-manifest.json \
  --keyring-dir ./keyring \
  --strict
```

4. Register with strict enforcement:

```bash
python -m sena.cli.main registry --sqlite-path /tmp/policy.db register \
  --policy-dir ./bundle \
  --bundle-name enterprise-compliance-controls \
  --bundle-version 2026.04.1 \
  --signature-strict \
  --keyring-dir ./keyring
```

## API strict mode

Set:

- `SENA_BUNDLE_SIGNATURE_STRICT=true`
- `SENA_BUNDLE_SIGNATURE_KEYRING_DIR=/path/to/keyring`
- Optional `SENA_BUNDLE_RELEASE_MANIFEST_FILENAME` (default `release-manifest.json`)

In strict mode, bundle registration fails if verification fails, and active promotion validation also fails for bundles without verified signatures.

## Why enterprise buyers care

This adds release provenance and tamper evidence for control changes:

- auditable signer identity (`key_id`)
- immutable digest evidence at promotion time
- deterministic verification in CI/CD and runtime
- optional strict gate for regulated environments, while preserving local developer velocity
