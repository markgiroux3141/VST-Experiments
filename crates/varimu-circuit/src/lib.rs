//! Circuit files and drawings for the native app (docs/NATIVE_APP_PLAN.md).
//!
//! This crate will hold the Rust side of what `varimu/circuit` (the circuit
//! format, macros, parts, device loading) and `varimu/editor` (drawings,
//! connect, compile, preflight) do in Python, building circuitsim's IR
//! directly. Python stays the reference: R1 compares the IR built here with
//! the IR Python builds, fixture by fixture.
//!
//! R0 (scaffold): only the IR types, re-exported from circuitsim.

pub use circuitsim::ir;

#[cfg(test)]
mod tests {
    use std::path::PathBuf;

    /// The IR the builder will emit is circuitsim's own: a Python-exported
    /// circuit reads through this crate's re-export.
    #[test]
    fn reads_an_exported_ir() {
        let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../circuitsim/tests/fixtures/default.json");
        let text = std::fs::read_to_string(&path).expect("fixture");
        let ir = super::ir::CircuitIr::from_json(&text).expect("IR JSON");
        assert!(!ir.sections.is_empty());
    }
}
