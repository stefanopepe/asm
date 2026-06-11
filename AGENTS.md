# ASM Development Guide For AI Agents

This guide provides comprehensive instructions for AI agents working on the ASM codebase. It covers the architecture, development workflows, and critical guidelines for effective contributions.

## Project Overview
Strata ASM (Anchor State Machine) is the core component of the Strata protocol. The ASM processes L1 blocks, routes transactions to pluggable subprotocols, applies deterministic state transitions, emits manifests/logs and persists state through a worker service.

## Architecture Memory

Before working on Alpen integration, signet checkpointing, or ASM verification flows, read:

- `docs/architecture-memory/alpen-ee-to-signet-checkpoint.md`

That document is the persistent working memory for the current traced path from a new Alpen EE block to signet checkpoint publication and final ASM verification.
