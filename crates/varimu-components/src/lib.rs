//! The component compiler (docs/COMPONENT_EDITOR_PLAN.md, C2): a transformer specified by
//! its construction (a lamination from a sourced table, the stack, the core material,
//! butt or interleaved stacking, and a winding plan of sections, layers, wire and
//! insulation) compiled by sourced formulas to the values the circuit's `transformer`
//! macro takes, and saved as an immutable component version
//! (`config/components/<name>/<N>.yaml` plus its line in `versions.lock`).
//!
//! Rust compiles, Python reads: the compiled form is data, read by both builders like a
//! device file (`varimu-circuit` doesn't depend on this crate).
//!
//! - [`tables`]: the lamination, wire and dielectric tables (`config/transformer/`), each
//!   row with its source;
//! - [`design`]: the transformer's source format (what the component editor edits);
//! - [`geometry`]: the winding window laid out (layers, mean turn lengths, builds);
//! - [`leakage`]: leakage inductance from the window's MMF profile (the energy method);
//! - [`capacitance`]: layer and interwinding capacitance;
//! - [`compile`]: all of it to the macro's values, a report and warnings;
//! - [`response`]: the compiled transformer's frequency response between a source and a
//!   load (what the Components view plots);
//! - [`edit`]: editing a design as data (the Components view's edits);
//! - [`store`]: saving a version and its lock line.

pub mod capacitance;
pub mod compile;
pub mod design;
pub mod edit;
pub mod fem;
pub mod geometry;
pub mod leakage;
pub mod response;
pub mod sourced;
pub mod store;
pub mod tables;

pub use varimu_circuit::Error;

/// This crate's version, recorded in every compiled version.
pub const COMPILER: &str = concat!("varimu-components ", env!("CARGO_PKG_VERSION"));

pub(crate) fn err<T>(msg: impl Into<String>) -> Result<T, Error> {
    Err(Error(msg.into()))
}
