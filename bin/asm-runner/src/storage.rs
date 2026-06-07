//! Storage setup for the ASM runner.

use std::sync::Arc;

use anyhow::Result;
use asm_storage::{AsmManifestMmrDb, AsmStateDb};
use strata_asm_moho_storage::SledExportEntriesDb;

use crate::config::DatabaseConfig;

/// Create storage backends for the ASM runner.
pub(crate) fn create_storage(
    config: &DatabaseConfig,
) -> Result<(Arc<AsmStateDb>, Arc<AsmManifestMmrDb>, SledExportEntriesDb)> {
    let db = sled::open(&config.path)?;
    let state_db = Arc::new(AsmStateDb::open(&db)?);
    let mmr_db = Arc::new(AsmManifestMmrDb::open(&db)?);
    let export_entries_db = SledExportEntriesDb::open(&db)?;
    Ok((state_db, mmr_db, export_entries_db))
}
