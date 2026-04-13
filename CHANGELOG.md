# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Centralized package and API versioning via `sena.__version__`.
- Added a release helper script (`scripts/bump_version.py`) for deterministic version bumps.

### Changed
- Tightened default product surface to deterministic Jira + ServiceNow approval decisioning with replayable audit evidence across README, docs indexing, package metadata, and API descriptions.
- Added machine-readable product surface inventory at `product_surface_inventory.yaml` and a reclassification report at `docs/PRODUCT_SURFACE_RECLASSIFICATION_REPORT.md`.
- Demoted non-core cookbook/labs/demo materials behind `docs/EXPERIMENTAL_INDEX.md` and added explicit deprecation/historical banners for stale planning content.
- Repositioned product documentation (README, control plane, architecture) around deterministic governance claims and added explicit alpha maturity boundaries.
- Standardized project version declarations to `0.3.0`.
- Reconciled product story across README, roadmap, and core architecture/control-plane docs around one wedge: deterministic policy governance for Jira + ServiceNow approval workflows.
- Standardized integration labeling across docs: Jira + ServiceNow as supported; generic webhook + Slack as experimental.
- Added canonical positioning decision record: `docs/PRODUCT_POSITIONING_DECISIONS.md`.
- Toned down maturity language to reflect alpha status with explicit pilot-ready criteria and non-goals.


## [0.3.0] - 2026-03-31

### Added
- Version consistency audit outcomes documented in repository metadata and docs.
