# Alpen EE To Signet Checkpoint

## Purpose

This document is a persistent working memory for future work that crosses:

- Alpen EE block production
- Strata OL submission and block production
- signet checkpoint publication
- ASM verification of the published checkpoint

It captures the current end-to-end architecture as traced on 2026-06-11.

## Scope And Caveat

This memory is based on:

- this ASM repository
- the current public `alpenlabs/alpen` `main` branch as inspected on 2026-06-11

Do not assume older testnet-II Docker layouts or older `docker-compose*.yml` naming are still authoritative. The current mental model should be derived from the code paths below, not from obsolete compose or README text.

## Core Conclusion

When a new Alpen EE block is added, the path to a signet checkpoint is:

1. `alpen-client` builds EE blocks locally.
2. EE blocks are grouped into batches.
3. The batch DA payload is prepared and published to signet using the EE DA pipeline.
4. The proof pipeline produces the proof material for the batch.
5. `alpen-client` submits a `SnarkAccountUpdate` to Strata over OL RPC.
6. Strata accepts that update into the OL mempool and assembles OL blocks.
7. When an OL epoch completes, Strata builds a `CheckpointPayload`.
8. Strata's Bitcoin writer stack publishes the corresponding checkpoint envelope to signet.
9. `asm-runner` sees the new signet block, processes it as L1 input, extracts the checkpoint transaction, and verifies it.
10. If valid, ASM updates its checkpoint state and emits a `CheckpointTipUpdate` log.

## Detailed Trace

### 1. EE block production starts in `alpen-client`

On the Alpen side, sequencer mode is wired with both:

- an OL endpoint: `--ol-client-url`, `--ol-submit-url`
- a Bitcoin endpoint: `--btc-rpc-url`, `--btc-rpc-user`, `--btc-rpc-password`

This is the first important architectural fact: EE sequencing talks to both Strata and signet.

### 2. New EE blocks are built

The EE sequencer starts:

- the execution chain service
- the OL chain tracker
- `block_builder_task(...)`

`block_builder_task(...)` is the block-construction path for new EE blocks.

### 3. EE blocks are collected into batches

After block production, `create_batch_builder(...)` groups EE blocks into batches using the configured sealing policy.

This is the first aggregation boundary: the system does not checkpoint each EE block directly to signet. It batches first.

### 4. DA publication to signet runs in parallel

The EE DA stack is launched from:

- `BtcioParams::new(...)`
- `BroadcasterBuilder::new(...)`
- `create_chunked_envelope_task(...)`
- `ChunkedEnvelopeDaProvider::new(...)`

This path prepares and broadcasts the EE state-diff data through chunked envelope transactions on signet.

### 5. Proof generation runs in parallel

The EE sequencer also starts:

- chunk proving
- account proving
- batch lifecycle management

The important handoff is that the batch lifecycle waits until the batch is both:

- DA-ready
- proof-ready

### 6. `alpen-client` submits the OL update

Once a batch is ready, `create_update_submitter_task(...)` submits a `SnarkAccountUpdate` to Strata.

The submission path is:

- `RpcOLClient::submit_update(...)`
- wraps the update as `RpcSnarkAccountUpdate`
- wraps that into `RpcOLTransaction`
- sends it through OL RPC `submitTransaction`

This is the OL boundary. At this point the EE client is no longer just producing local blocks; it is publishing the canonical account update into Strata.

### 7. Strata turns the submitted update into OL blocks

On the Strata side:

- the sequencer starts the OL mempool
- `BlockasmBuilder` assembles OL blocks from mempool transactions
- `SequencerBuilder` produces OL blocks on the configured cadence

This is the OL block-production path that consumes the `SnarkAccountUpdate` submitted by `alpen-client`.

### 8. End of epoch produces a checkpoint payload

When the OL chain worker completes an epoch, it emits an epoch summary.

The OL checkpoint worker consumes that summary and builds a `CheckpointPayload` containing:

- the new `CheckpointTip`
- the covered L1 height
- the terminal OL block commitment
- the state diff
- the OL logs
- the terminal header complement
- the proof

This is the checkpoint artifact that will ultimately be posted to signet.

### 9. Strata publishes the checkpoint to signet

Strata's sequencer-side Bitcoin writer stack is responsible for L1 publication:

- `start_broadcaster(...)`
- `start_writer(...)`
- `EnvelopeHandle`
- `WatcherBuilder`
- `BundlerBuilder`

The key comment in Strata's current service wiring is that the writer:

- bundles L1 intents
- creates envelope transactions
- publishes to Bitcoin

This is the signet publication stage for checkpoint envelopes.

### 10. `asm-runner` observes the new signet block

On the ASM side, `asm-runner`:

- subscribes to bitcoind `rawblock` ZMQ
- backfills gaps if needed
- submits each new L1 block to the ASM worker

That is implemented in `bin/asm-runner/src/block_watcher.rs`.

### 11. ASM pre-processes the new L1 block

For each new signet block, ASM:

- validates header continuity
- filters relevant transactions by magic bytes
- loads subprotocol state
- collects auxiliary data requirements

This happens in `crates/stf/src/preprocess.rs`.

### 12. ASM extracts and verifies the checkpoint transaction

If the L1 block contains a checkpoint envelope transaction, the checkpoint subprotocol:

- extracts the checkpoint payload from the envelope
- authenticates the envelope pubkey against the sequencer predicate
- verifies epoch progression
- verifies L1 coverage progression
- verifies L2 slot progression
- reconstructs the covered ASM manifest-range hash from auxiliary data
- verifies the checkpoint proof against that reconstructed claim

This is the critical verification step that turns an L1 checkpoint transaction into accepted ASM state.

### 13. ASM persists the result

If the checkpoint is valid, ASM:

- emits a `CheckpointTipUpdate` log
- records the manifest
- stores auxiliary data
- stores the new anchor state last as the block commit point

That last ordering matters because it is the crash-safety contract for ASM block processing.

## Integration Boundaries That Matter

For future work, the most important boundaries are:

- `alpen-client` does not currently talk directly to `asm-runner`
- `alpen-client` expects an OL interface from Strata
- that OL interface explicitly includes `getAsmManifestCommitment`
- ASM verifies the signet checkpoint only after it is mined into an L1 block

This means:

- ASM is downstream of signet inclusion
- `alpen-client` is upstream of signet inclusion
- Strata is the bridge between EE updates and signet checkpoint publication

## Practical Implications

### What is true today

- Alpen currently behaves more like a commit chain on private signet than a full onchain DA rollup.
- `alpen-client` sequencer mode depends on both Strata OL RPC and signet Bitcoin RPC.
- ASM can parse and verify the signet checkpoint after inclusion.

### What to keep in mind for future implementation work

- If the goal is to consume signet commitments inside Alpen bootstrap or validation flows, the natural compatibility point is the OL API, especially `getAsmManifestCommitment`.
- If the goal is to verify that a given EE state transition is anchored to signet, the full chain of evidence is:
  1. EE block
  2. batch
  3. DA publication
  4. proof-ready account update
  5. OL block / epoch summary
  6. checkpoint payload
  7. signet checkpoint transaction
  8. ASM-verified checkpoint tip

## Primary Code References

### In this ASM repository

- `bin/asm-runner/src/block_watcher.rs`
- `crates/stf/src/preprocess.rs`
- `crates/stf/src/transition.rs`
- `crates/subprotocols/checkpoint/subprotocol/src/handler.rs`
- `crates/subprotocols/checkpoint/txs/src/parser.rs`
- `crates/subprotocols/checkpoint/verification/src/verification.rs`
- `crates/worker/src/service.rs`
- `crates/rpc/src/traits.rs`

### In `alpenlabs/alpen` `main` as inspected on 2026-06-11

- `docker/alpen-client/entrypoint.sh`
- `bin/alpen-client/src/main.rs`
- `bin/alpen-client/src/ol_client.rs`
- `bin/alpen-client/src/rpc_client.rs`
- `bin/strata/src/services.rs`
- `bin/strata/src/sequencer/block_producer.rs`
- `crates/ol/rpc/api/src/lib.rs`
- `crates/ol/checkpoint/src/state.rs`

## Maintenance Rule

If a future change touches:

- Alpen EE sequencing
- Strata OL submission
- checkpoint publication
- ASM checkpoint verification

then this document should be updated in the same change set if the architecture or the ownership of any stage has moved.
