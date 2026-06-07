//! Lightweight sled-backed storage for the ASM runner.
//!
//! Replaces alpen's `strata-state`, `strata-storage`, and `strata-db-store-sled`
//! with a self-contained implementation that has zero alpen dependencies.
//!
//! Two storage backends:
//! - [`AsmStateDb`] — anchor states + aux data, keyed by L1 block commitment
//! - [`AsmManifestMmrDb`] — manifest hash MMR (append, prove, query)
//!
//! Per-container export entries moved to `strata-asm-moho-storage`, persisted
//! by the Moho worker alongside the `MohoState` whose `ExportState` MMR they
//! mirror.

mod mmr;
mod state;

pub use mmr::AsmManifestMmrDb;
pub use state::AsmStateDb;
