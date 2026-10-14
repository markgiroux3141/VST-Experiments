//! Python bindings (feature "python"), built by maturin as the module `circuitsim`.

use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::create_exception;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::ir::{CircuitIr, IR_VERSION};
use crate::transient::Method;

create_exception!(
    circuitsim,
    SimulationError,
    PyRuntimeError,
    "The circuit can't be simulated (unsupported element, singular matrix, ...)."
);

fn invalid(e: impl ToString) -> PyErr {
    PyValueError::new_err(e.to_string())
}

/// Parse and validate IR JSON in Rust, then write it back out.
///
/// Raises ValueError if the JSON is not a valid circuit IR.
#[pyfunction]
fn ir_roundtrip(json: &str) -> PyResult<String> {
    Ok(CircuitIr::from_json(json).map_err(invalid)?.to_json())
}

/// Transient run of a circuit IR (JSON) at a fixed step.
///
/// `input` holds the volts at the IR's input node, one sample per step of
/// `dt` seconds; sample 0 is the DC operating point. `method` is "trap" or
/// "euler". Returns {probe name, e.g. "v(out)": float64 array like `input`}.
/// Raises ValueError for invalid arguments and SimulationError when the
/// circuit can't be simulated.
#[pyfunction]
#[pyo3(signature = (ir_json, input, dt, method = "trap"))]
fn simulate<'py>(
    py: Python<'py>,
    ir_json: &str,
    input: PyReadonlyArray1<'py, f64>,
    dt: f64,
    method: &str,
) -> PyResult<Bound<'py, PyDict>> {
    let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
    let method = Method::parse(method).map_err(invalid)?;
    let x = input.as_array().to_vec();
    let out = py
        .detach(|| crate::simulate(&ir, &x, dt, method))
        .map_err(|e| SimulationError::new_err(e.to_string()))?;
    let d = PyDict::new(py);
    for (name, v) in out.names.into_iter().zip(out.values) {
        d.set_item(name, v.into_pyarray(py))?;
    }
    Ok(d)
}

#[pymodule]
fn circuitsim(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", crate::VERSION)?;
    m.add("IR_VERSION", IR_VERSION)?;
    m.add("SimulationError", m.py().get_type::<SimulationError>())?;
    m.add_function(wrap_pyfunction!(ir_roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(simulate, m)?)?;
    Ok(())
}
