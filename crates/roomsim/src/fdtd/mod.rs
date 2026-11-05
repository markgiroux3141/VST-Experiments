//! The wave solver (ROOM_LOOP_PLAN.md R10): not built yet.

#[cfg(feature = "python")]
pub mod python {
    use pyo3::prelude::*;

    pub fn register(_m: &Bound<'_, PyModule>) -> PyResult<()> {
        Ok(())
    }
}
