//! Python bindings (feature "python"), built by maturin as the module `circuitsim`.

use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::create_exception;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::ir::{CircuitIr, IR_VERSION};
use crate::transient::{Method, Options};

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
/// "euler". The other keywords are solver options (see `Options` in
/// transient.rs; None keeps the default). Returns {probe name, e.g.
/// "v(out)": float64 array like `input`}, and with `stats=True` also a dict
/// of solver statistics. Raises ValueError for invalid arguments and
/// SimulationError when the circuit can't be simulated.
#[pyfunction]
#[pyo3(signature = (
    ir_json, input, dt, method = "trap", *, reltol = None, vntol = None, max_iter = None,
    max_halvings = None, gmin = None, extrapolate = None, stats = false
))]
#[allow(clippy::too_many_arguments)]
fn simulate<'py>(
    py: Python<'py>,
    ir_json: &str,
    input: PyReadonlyArray1<'py, f64>,
    dt: f64,
    method: &str,
    reltol: Option<f64>,
    vntol: Option<f64>,
    max_iter: Option<usize>,
    max_halvings: Option<u32>,
    gmin: Option<f64>,
    extrapolate: Option<bool>,
    stats: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
    let d = Options::default();
    let opts = Options {
        method: Method::parse(method).map_err(invalid)?,
        reltol: reltol.unwrap_or(d.reltol),
        vntol: vntol.unwrap_or(d.vntol),
        max_iter: max_iter.unwrap_or(d.max_iter),
        max_halvings: max_halvings.unwrap_or(d.max_halvings),
        gmin: gmin.unwrap_or(d.gmin),
        extrapolate: extrapolate.unwrap_or(d.extrapolate),
        ..d
    };
    let x = input.as_array().to_vec();
    let out = py
        .detach(|| crate::simulate(&ir, &x, dt, &opts))
        .map_err(|e| SimulationError::new_err(e.to_string()))?;
    let probes = PyDict::new(py);
    for (name, v) in out.names.into_iter().zip(out.values) {
        probes.set_item(name, v.into_pyarray(py))?;
    }
    if !stats {
        return Ok(probes.into_any());
    }
    let s = &out.stats;
    let st = PyDict::new(py);
    st.set_item("steps", s.steps)?;
    st.set_item("substeps", s.substeps)?;
    st.set_item("halved_steps", s.halved_steps)?;
    st.set_item("iterations", s.iterations)?;
    st.set_item("max_iterations", s.max_iterations)?;
    st.set_item("dc_method", s.dc_method)?;
    st.set_item("dc_iterations", s.dc_iterations)?;
    st.set_item("nonlinear_unknowns", s.nonlinear_unknowns)?;
    st.set_item("linear_unknowns", s.linear_unknowns)?;
    Ok((probes, st).into_pyobject(py)?.into_any())
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
