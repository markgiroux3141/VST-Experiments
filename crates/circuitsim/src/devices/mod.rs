//! Nonlinear device models: compiled ports of `varimu/devices/*.py`.
//!
//! The Python models are the source of truth. Every equation here is written
//! in the same order of operations as its Python reference, and
//! `tests/devices.rs` checks the currents against values exported from Python
//! (`scripts/export_circuit_fixtures.py`) to 1e-12. The Jacobians are
//! analytic (checked against finite differences).
//!
//! A device with pins `0..=P` has `P` ports: port `j` is the voltage of pin
//! `j` relative to the last pin (the reference, e.g. the cathode), and its
//! current flows into pin `j` and back out of the reference pin.

use std::fmt;

use crate::ir::DeviceModel;

pub mod core;
pub mod diode;
pub mod pentode;
pub mod triode;

pub use self::core::MagneticCore;
pub use diode::{JunctionDiode, VacuumDiode};
pub use pentode::Pentode;
pub use triode::Triode;

/// A nonlinear multi-port, as the Newton solver sees it.
pub trait Device: fmt::Debug + Send + Sync {
    /// Number of ports (pins minus one).
    fn ports(&self) -> usize;

    /// Port currents `i` and the Jacobian `g[j * ports + k] = d i_j / d v_k`
    /// at the port voltages `v`.
    fn eval(&self, v: &[f64], i: &mut [f64], g: &mut [f64]);

    /// Newton step limiting: given the previous linearization point `v_old`,
    /// pull the proposed `v` back where the model is too steep to trust a
    /// full step (SPICE's `pnjlim` for junctions). Returns whether it changed
    /// anything; a limited iteration never counts as converged.
    fn limit(&self, _v: &mut [f64], _v_old: &[f64]) -> bool {
        false
    }

    /// A conductance (S) the DK solver may move from this port into the
    /// linear part of the circuit (`dk.rs`): numerics only, results are the
    /// same in exact arithmetic. Nonzero for ports that can be the only
    /// path to a node (a rectifier into a floating winding); the value
    /// should lie within the port's range of conductances.
    fn shunt(&self, _port: usize) -> f64 {
        0.0
    }

    /// Called once per accepted time step with the final port voltages. The
    /// hook for devices with memory (a hysteretic transformer core, an
    /// optical cell); stateless models ignore it.
    fn accept(&mut self, _v: &[f64]) {}

    /// Whether [`Device::accept`] can change the device's currents (then the
    /// DK solver doesn't reuse an evaluation across steps).
    fn has_state(&self) -> bool {
        false
    }

    /// The device's memory (empty for stateless models), to carry it across
    /// a parameter change (`Transient::update` builds new device instances).
    fn state(&self) -> Vec<f64> {
        Vec::new()
    }

    /// Restore memory taken with [`Device::state`].
    fn set_state(&mut self, _state: &[f64]) {}
}

/// The device for an IR model.
pub fn from_model(model: &DeviceModel) -> Box<dyn Device> {
    match model {
        DeviceModel::Triode(m) => Box::new(Triode::new(m)),
        DeviceModel::Pentode(m) => Box::new(Pentode::new(m)),
        DeviceModel::JunctionDiode(m) => Box::new(JunctionDiode::new(m)),
        DeviceModel::VacuumDiode(m) => Box::new(VacuumDiode::new(m)),
        DeviceModel::MagneticCore(m) => Box::new(MagneticCore::new(m)),
    }
}

/// `ln(1 + exp(x))` exactly as numpy's `logaddexp(0, x)` computes it.
pub(crate) fn softplus(x: f64) -> f64 {
    if x == 0.0 {
        std::f64::consts::LN_2
    } else if x > 0.0 {
        x + (-x).exp().ln_1p()
    } else {
        x.exp().ln_1p()
    }
}

/// `d softplus / dx = 1 / (1 + exp(-x))`, without overflow.
pub(crate) fn sigmoid(x: f64) -> f64 {
    if x >= 0.0 {
        1.0 / (1.0 + (-x).exp())
    } else {
        let e = x.exp();
        e / (1.0 + e)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn softplus_is_stable_and_matches_its_definition() {
        for x in [-800.0, -30.0, -1.0, -1e-9, 0.0, 1e-9, 1.0, 30.0, 800.0] {
            let naive = (1.0 + f64::exp(x)).ln();
            let sp = softplus(x);
            assert!(sp.is_finite() && sp >= 0.0);
            if naive.is_finite() && naive > 1e-300 {
                assert!((sp - naive).abs() <= 1e-15 * naive.max(1.0), "{x}");
            }
            let d = 1e-6 * x.abs().max(1.0);
            let fd = (softplus(x + d) - softplus(x - d)) / (2.0 * d);
            assert!((sigmoid(x) - fd).abs() < 1e-8, "{x}");
        }
    }
}
