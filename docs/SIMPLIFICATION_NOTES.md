# Simplification Notes (Policy, Lifecycle, Audit)

This note documents targeted simplifications that reduce accidental framework complexity while preserving the supported path.

## Scope of this change

Focused modules:
- `src/sena/policy/lifecycle.py`
- `src/sena/services/bundle_service.py`
- `src/sena/cli/main.py`
- `src/sena/audit/storage.py`

## 1) Promotion gate policy assembly is now centralized

### Before
Promotion gate policy assembly logic was duplicated in two separate call paths:
- API/service path (`BundleService._effective_gate_policy`)
- CLI path (`_run_registry_promote`)

Each path merged defaults and threshold overrides independently.

### After
A single function, `build_promotion_gate_policy(...)`, is now responsible for combining:
- default gate settings
- optional max-changed override
- optional transition regression overrides
- optional `BLOCKED->APPROVED` override

Both service and CLI paths call this shared function.

### Complexity removed
- duplicate merge logic
- drift risk between CLI and service behavior
- parallel policy-construction concepts in lifecycle callers

## 2) Regression transition counting now uses one helper

### Before
Outcome transition counting logic was inlined where needed.

### After
`_count_transition_changes(...)` in lifecycle provides one implementation for counting `BEFORE->AFTER` simulation transitions during promotion gate evaluation.

### Complexity removed
- repeated low-level scanning logic
- harder-to-audit transition-budget behavior

## 3) Audit storage contract simplified and duplicated lookup removed

### Before
`AuditStorage` used an abstract base class, while concrete storage implementations repeated common record-id lookup and fallback id creation logic.

### After
- `AuditStorage` is now a `Protocol` (structural contract, less framework ceremony).
- Common helpers now handle:
  - storage id generation (`_storage_entry_id`)
  - record lookup by accepted id fields (`_read_record_by_id`)

### Complexity removed
- unnecessary inheritance machinery for a simple interface
- repeated lookup code in local and sqlite storage paths
- repeated id fallback code across storage backends

## Supported behavior preserved

- Promotion gate outcomes and configuration compatibility are preserved.
- CLI promotion flow still supports all prior threshold and regression override options.
- Audit storage backend behavior remains the same for local, sqlite append-only, S3 object-lock, and Azure immutable blob modes.

## Mental model improvement (request -> decision -> audit artifact)

The supported path is now easier to trace because:
1. Promotion gate policy is built once consistently.
2. Transition-budget enforcement uses one counting implementation.
3. Audit record id handling and lookup are implemented once and reused.
