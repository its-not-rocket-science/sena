# Kubernetes Demo One-Pager (Experimental Surface)

> **Status note:** this Kubernetes material is a demo/evaluation surface, not SENA’s primary supported integration story for the current phase.

## Why this demo exists

This demo illustrates SENA’s deterministic evaluation and audit verification mechanics in a compact workflow.

## Demo flow

An AI agent recommends scaling a Kubernetes deployment from 3 to 10 replicas. A policy enforcing `max replicas = 5` returns `BLOCKED`, and the response carries proof material that can be externally verified.

## What this demonstrates truthfully

1. Deterministic policy evaluation.
2. Hash-linked audit recording.
3. External verification workflow.

## What this does not imply

- Kubernetes is not the primary product wedge in current docs.
- This demo does not supersede the supported Jira + ServiceNow integration depth claims.
