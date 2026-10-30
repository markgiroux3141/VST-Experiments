//! circuitsim: a fast nonlinear audio circuit simulator.
//!
//! Netlist in, signals out, for circuits built from the device models it has
//! (tubes, diodes, transformers). ngspice stays the reference engine; see
//! `docs/CIRCUIT_SIM_PLAN.md` in the repository for the plan and milestones.
//!
//! So far: the circuit IR shared with the Python side ([`ir`], M1), the
//! fixed-step engine ([`mna`], [`transient`], M2), the nonlinear devices
//! with Newton on the full MNA system ([`devices`], [`newton`], M3), and
//! the integration methods with local error control chosen for the 670 (M4).

use std::fmt;

pub mod devices;
pub mod dk;
pub mod fastmath;
pub mod ir;
pub mod linalg;
pub mod mna;
pub mod newton;
pub mod noise;
pub mod partition;
pub mod stream;
pub mod timing;
pub mod transient;

#[cfg(feature = "python")]
mod python;

pub use transient::{
    Method, Options, Output, Solver, Stats, StepInput, simulate, simulate_controls,
    simulate_with_progress,
};

/// Crate version (also `circuitsim.__version__` in Python).
pub const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Hash of the sources this build was compiled from (see `build.rs`; also
/// `circuitsim.SOURCE_HASH` in Python).
pub const SOURCE_HASH: &str = env!("CIRCUITSIM_SOURCE_HASH");

/// Anything that stops a simulation: an invalid circuit, an unsupported
/// element, a singular matrix.
#[derive(Debug, Clone, PartialEq)]
pub struct Error(pub String);

impl Error {
    pub fn new(msg: impl Into<String>) -> Self {
        Error(msg.into())
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Error {}

impl From<ir::IrError> for Error {
    fn from(e: ir::IrError) -> Self {
        Error(e.to_string())
    }
}
