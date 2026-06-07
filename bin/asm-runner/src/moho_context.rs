//! Moho worker-context implementation for the ASM runner.
//!
//! [`MohoWorkerContextImpl`] backs the three concern traits the Moho worker
//! interfaces through ([`AsmStateProvider`], [`L1ProviderContext`],
//! [`MohoStateStore`]). It reads the ASM anchor states and logs the ASM worker
//! already committed (via [`AsmStateDb`]), resolves L1 parents from the Bitcoin
//! node, and persists derived Moho states via [`SledMohoStateDb`].
//!
//! Unlike the ASM worker — which runs on its own thread and can block on Bitcoin
//! RPC directly — the Moho worker runs as an async service. The
//! [`MohoWorkerContext`](strata_asm_moho_worker::MohoWorkerContext) traits are
//! synchronous, so parent resolution bridges to the async client via
//! [`block_in_place`](task::block_in_place); see [`Self::get_parent_block`].

use std::sync::Arc;

use asm_storage::AsmStateDb;
use bitcoin::BlockHash;
use bitcoind_async_client::{Client, error::ClientError, traits::Reader};
use moho_types::MohoState;
use strata_asm_common::{AnchorState, AsmLogEntry};
use strata_asm_moho_storage::SledMohoStateDb;
use strata_asm_moho_worker::{
    AsmStateProvider, L1ProviderContext, MohoStateStore, MohoWorkerError, MohoWorkerResult,
};
use strata_asm_worker::AsmState;
use strata_btc_types::{BlockHashExt, L1BlockIdBitcoinExt};
use strata_identifiers::L1BlockCommitment;
use tokio::{runtime::Handle, task};

use crate::retry::{ExponentialBackoff, RetryConfig, retry_with_backoff_async};

/// Storage and L1 access the Moho worker derives per-block Moho states from.
pub(crate) struct MohoWorkerContextImpl {
    runtime_handle: Handle,
    bitcoin_client: Arc<Client>,
    /// Backoff schedule for Bitcoin RPC calls.
    rpc_backoff: ExponentialBackoff,
    /// Maximum retry attempts per Bitcoin RPC call.
    rpc_max_retries: u16,
    /// ASM anchor states and logs the Moho state is derived from, committed by
    /// the ASM worker.
    state_db: Arc<AsmStateDb>,
    /// Persistence for the derived per-block Moho states.
    moho_state_db: SledMohoStateDb,
}

impl MohoWorkerContextImpl {
    pub(crate) fn new(
        runtime_handle: Handle,
        bitcoin_client: Arc<Client>,
        retry: &RetryConfig,
        state_db: Arc<AsmStateDb>,
        moho_state_db: SledMohoStateDb,
    ) -> Self {
        Self {
            runtime_handle,
            bitcoin_client,
            rpc_backoff: retry.backoff(),
            rpc_max_retries: retry.max_retries,
            state_db,
            moho_state_db,
        }
    }

    /// Reads the ASM state the ASM worker committed for `blockid`, mapping a
    /// miss to [`MohoWorkerError::MissingAsmState`].
    fn anchor(&self, blockid: &L1BlockCommitment) -> MohoWorkerResult<AsmState> {
        self.state_db
            .get(blockid)
            .map_err(|e| MohoWorkerError::Storage(e.to_string()))?
            .ok_or(MohoWorkerError::MissingAsmState(*blockid))
    }
}

impl AsmStateProvider for MohoWorkerContextImpl {
    fn get_anchor_state(&self, blockid: &L1BlockCommitment) -> MohoWorkerResult<AnchorState> {
        Ok(self.anchor(blockid)?.state().clone())
    }

    fn get_anchor_logs(&self, blockid: &L1BlockCommitment) -> MohoWorkerResult<Vec<AsmLogEntry>> {
        Ok(self.anchor(blockid)?.logs().clone())
    }
}

impl L1ProviderContext for MohoWorkerContextImpl {
    fn get_parent_block(&self, block: &L1BlockCommitment) -> MohoWorkerResult<L1BlockCommitment> {
        let block_hash: BlockHash = block.blkid().to_block_hash();
        let client = &self.bitcoin_client;

        // The context traits are synchronous but the Bitcoin RPC is async, and
        // the Moho worker runs as an async service — a nested `Handle::block_on`
        // would panic. `block_in_place` releases the current worker thread for
        // the blocking call so the runtime keeps making progress; it requires
        // the multi-threaded runtime the runner builds.
        let header = task::block_in_place(|| {
            self.runtime_handle.block_on(retry_with_backoff_async(
                "btc_get_block_header",
                self.rpc_max_retries,
                &self.rpc_backoff,
                || async { client.get_block_header(&block_hash).await },
            ))
        })
        .map_err(|_: ClientError| MohoWorkerError::MissingParentBlock(*block))?;

        let parent_id = header.prev_blockhash.to_l1_block_id();
        Ok(L1BlockCommitment::new(block.height() - 1, parent_id))
    }
}

impl MohoStateStore for MohoWorkerContextImpl {
    fn get_latest_moho_state(&self) -> MohoWorkerResult<Option<(L1BlockCommitment, MohoState)>> {
        self.moho_state_db
            .get_latest()
            .map_err(|e| MohoWorkerError::Storage(e.to_string()))
    }

    fn get_moho_state(&self, blockid: &L1BlockCommitment) -> MohoWorkerResult<MohoState> {
        self.moho_state_db
            .get(*blockid)
            .map_err(|e| MohoWorkerError::Storage(e.to_string()))?
            .ok_or(MohoWorkerError::MissingMohoState(*blockid))
    }

    fn store_moho_state(
        &self,
        blockid: &L1BlockCommitment,
        state: &MohoState,
    ) -> MohoWorkerResult<()> {
        self.moho_state_db
            .store(*blockid, state.clone())
            .map_err(|e| MohoWorkerError::Storage(e.to_string()))
    }
}
