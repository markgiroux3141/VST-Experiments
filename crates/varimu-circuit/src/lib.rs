//! Circuit files and drawings for the native app (docs/NATIVE_APP_PLAN.md).
//!
//! The Rust side of `varimu/circuit` (R1): circuit files (`spec`), the builder and its
//! macro parts (`builder`, `parts`), device files and core materials (`devices`), the
//! 670's derived values (`derived`), all building circuitsim's IR directly. Python
//! stays the reference: tests/agreement.rs compares the IR built here with the IR
//! Python builds (scripts/export_app_fixtures.py), case by case. `varimu/editor`'s
//! drawings join in R3.
//!
//! ```no_run
//! use varimu_circuit::{Cores, Library, spec, yaml::Value};
//! let lib = Library::new("config");
//! let c = spec::load_circuit(&spec::circuit_path(lib.config_dir(), "fairchild_670")?)?;
//! let p = spec::resolve(&c, &[("time_constant".into(), Value::Int(3))])?;
//! let ir = varimu_circuit::build_ir(&lib, &c, &p, Cores::Ja)?;
//! # Ok::<(), varimu_circuit::Error>(())
//! ```

pub mod builder;
pub mod compile;
pub mod connect;
pub mod derived;
pub mod devices;
pub mod drawing;
pub mod importer;
pub mod json;
pub mod parts;
pub mod preflight;
pub mod spec;
pub mod symbols;
pub mod values;
pub mod yaml;
pub mod yaml_out;

pub use builder::{Cores, build_ir};
pub use circuitsim::ir;
pub use devices::Library;

/// A load or build error, with the file and the part it's about.
#[derive(Debug, Clone, PartialEq)]
pub struct Error(pub String);

impl std::fmt::Display for Error {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for Error {}
