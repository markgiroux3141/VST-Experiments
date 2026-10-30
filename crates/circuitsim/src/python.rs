//! Python bindings (feature "python"), built by maturin as the module `circuitsim`.

use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::create_exception;
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyDict;

use crate::ir::{CircuitIr, IR_VERSION};
use crate::partition::Coupling;
use crate::stream::Stream;
use crate::transient::{ErrorNorm, Method, Options, Solver};

create_exception!(
    circuitsim,
    SimulationError,
    PyRuntimeError,
    "The circuit can't be simulated (unsupported element, singular matrix, ...)."
);

/// How often per run `simulate` checks for signals and reports progress.
const PROGRESS_CALLS: usize = 200;

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
/// `dt` seconds; sample 0 is the DC operating point. `method` is one of
/// `Method::NAMES` ("trap", "radau5", ...), `solver` one of `Solver::NAMES`
/// ("dk", "mna"). The other keywords are solver options (see `Options` in
/// transient.rs; None keeps the default). `partition` names sections of the
/// IR to run on a second thread, coupled through the nodes they share with
/// one sample of latency (`partition.rs`; `partition_coupling` "hold" or
/// "extrapolate"); the stats are then the first partition's. Returns {probe name, e.g.
/// "v(out)": float64 array like `input`}, and with `stats=True` also a dict
/// of solver statistics. Raises ValueError for invalid arguments and
/// SimulationError when the circuit can't be simulated.
///
/// The run releases the GIL. About PROGRESS_CALLS times per run it takes the
/// GIL back to check for signals (so Ctrl-C stops it with KeyboardInterrupt)
/// and calls `progress(fraction done)` if given; an exception raised there
/// stops the run and propagates.
#[pyfunction]
#[pyo3(signature = (
    ir_json, input, dt, method = "trap", *, solver = None, reltol = None, vntol = None,
    max_iter = None, max_halvings = None, gmin = None, extrapolate = None, input_order = None,
    predictor = None, error_abstol = None, error_reltol = None, max_error_halvings = None,
    newton_reuse = None, step_selection = None, error_norm = None, tube_tables = None,
    partition = None, partition_coupling = None, stats = false, progress = None, controls = None
))]
#[allow(clippy::too_many_arguments)]
fn simulate<'py>(
    py: Python<'py>,
    ir_json: &str,
    input: PyReadonlyArray1<'py, f64>,
    dt: f64,
    method: &str,
    solver: Option<&str>,
    reltol: Option<f64>,
    vntol: Option<f64>,
    max_iter: Option<usize>,
    max_halvings: Option<u32>,
    gmin: Option<f64>,
    extrapolate: Option<bool>,
    input_order: Option<usize>,
    predictor: Option<usize>,
    error_abstol: Option<f64>,
    error_reltol: Option<f64>,
    max_error_halvings: Option<u32>,
    newton_reuse: Option<bool>,
    step_selection: Option<bool>,
    error_norm: Option<&str>,
    tube_tables: Option<bool>,
    partition: Option<Vec<String>>,
    partition_coupling: Option<&str>,
    stats: bool,
    progress: Option<Py<PyAny>>,
    controls: Option<Vec<PyReadonlyArray1<'py, f64>>>,
) -> PyResult<Bound<'py, PyAny>> {
    let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
    // The control inputs' samples (IR order), as long as the input.
    let ctl: Vec<Vec<f64>> = controls
        .unwrap_or_default()
        .iter()
        .map(|c| c.as_array().to_vec())
        .collect();
    let d = Options::default();
    let opts = Options {
        method: Method::parse(method).map_err(invalid)?,
        solver: solver
            .map_or(Ok(d.solver), Solver::parse)
            .map_err(invalid)?,
        reltol: reltol.unwrap_or(d.reltol),
        vntol: vntol.unwrap_or(d.vntol),
        max_iter: max_iter.unwrap_or(d.max_iter),
        max_halvings: max_halvings.unwrap_or(d.max_halvings),
        gmin: gmin.unwrap_or(d.gmin),
        extrapolate: extrapolate.unwrap_or(d.extrapolate),
        input_order: input_order.unwrap_or(d.input_order),
        predictor: predictor.unwrap_or(d.predictor),
        error_abstol: error_abstol.unwrap_or(d.error_abstol),
        error_reltol: error_reltol.unwrap_or(d.error_reltol),
        max_error_halvings: max_error_halvings.unwrap_or(d.max_error_halvings),
        newton_reuse: newton_reuse.unwrap_or(d.newton_reuse),
        step_selection: step_selection.unwrap_or(d.step_selection),
        error_norm: error_norm
            .map_or(Ok(d.error_norm), ErrorNorm::parse)
            .map_err(invalid)?,
        tube_tables: tube_tables.unwrap_or(d.tube_tables),
        // Python gets the probes only.
        all_unknowns: false,
        ..d
    };
    let coupling = Coupling::parse(partition_coupling.unwrap_or("extrapolate")).map_err(invalid)?;
    let x = input.as_array().to_vec();
    let total = x.len();
    let mut raised: Option<PyErr> = None;
    let result = py.detach(|| {
        let every = total.div_ceil(PROGRESS_CALLS);
        let report = |done: usize| {
            Python::attach(|py| {
                py.check_signals()?;
                if let Some(f) = &progress {
                    f.call1(py, (done as f64 / total as f64,))?;
                }
                Ok(())
            })
            .map_err(|e: PyErr| {
                raised = Some(e);
                crate::Error::new("interrupted")
            })
        };
        let ctl: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
        match &partition {
            Some(second) if !second.is_empty() => crate::partition::simulate_partitioned_controls(
                &ir, second, coupling, &x, &ctl, dt, &opts, every, report,
            ),
            _ => crate::transient::simulate_controls(&ir, &x, &ctl, dt, &opts, every, report),
        }
    });
    if let Some(e) = raised {
        return Err(e);
    }
    let out = result.map_err(|e| SimulationError::new_err(e.to_string()))?;
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
    st.set_item("error_rejections", s.error_rejections)?;
    st.set_item("solves", s.solves)?;
    st.set_item("iterations", s.iterations)?;
    st.set_item("max_iterations", s.max_iterations)?;
    st.set_item("dc_method", s.dc_method)?;
    st.set_item("dc_iterations", s.dc_iterations)?;
    st.set_item("solver", s.solver)?;
    st.set_item("nonlinear_unknowns", s.nonlinear_unknowns)?;
    st.set_item("linear_unknowns", s.linear_unknowns)?;
    st.set_item("states", s.states)?;
    st.set_item("device_evaluations", s.device_evaluations)?;
    st.set_item("factorizations", s.factorizations)?;
    st.set_item("exact_retries", s.exact_retries)?;
    st.set_item("accepted_by_level", s.accepted_by_level.to_vec())?;
    st.set_item("rejected_by_level", s.rejected_by_level.to_vec())?;
    Ok((probes, st).into_pyobject(py)?.into_any())
}

/// A run fed block by block, for real time (`stream.rs`): the same output as
/// `simulate` (or a partitioned `simulate`) on the same input, lagging it by the
/// input interpolation's lookahead, with component values changed while running.
///
/// `Stream(ir_json, dt, u0, method, *, solver, reltol, vntol, input_order,
/// newton_reuse, tube_tables, partition, partition_coupling)`: at the DC
/// operating point with input `u0` (sample 0). Keywords as `simulate`'s (no
/// error control). Methods release the GIL; errors raise SimulationError.
#[pyclass(name = "Stream")]
struct PyStream {
    inner: Stream,
}

/// {probe name: float64 array} from per-probe values.
fn probe_dict<'py>(
    py: Python<'py>,
    names: &[String],
    values: Vec<Vec<f64>>,
) -> PyResult<Bound<'py, PyDict>> {
    let d = PyDict::new(py);
    for (name, v) in names.iter().zip(values) {
        d.set_item(name, v.into_pyarray(py))?;
    }
    Ok(d)
}

#[pymethods]
impl PyStream {
    #[new]
    #[pyo3(signature = (
        ir_json, dt, u0, method = "trap", *, solver = None, reltol = None, vntol = None,
        input_order = None, newton_reuse = None, tube_tables = None, partition = None,
        partition_coupling = None, c0 = None
    ))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        py: Python<'_>,
        ir_json: &str,
        dt: f64,
        u0: f64,
        method: &str,
        solver: Option<&str>,
        reltol: Option<f64>,
        vntol: Option<f64>,
        input_order: Option<usize>,
        newton_reuse: Option<bool>,
        tube_tables: Option<bool>,
        partition: Option<Vec<String>>,
        partition_coupling: Option<&str>,
        c0: Option<Vec<f64>>,
    ) -> PyResult<PyStream> {
        let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
        let d = Options::default();
        let opts = Options {
            method: Method::parse(method).map_err(invalid)?,
            solver: solver
                .map_or(Ok(d.solver), Solver::parse)
                .map_err(invalid)?,
            reltol: reltol.unwrap_or(d.reltol),
            vntol: vntol.unwrap_or(d.vntol),
            input_order: input_order.unwrap_or(d.input_order),
            newton_reuse: newton_reuse.unwrap_or(d.newton_reuse),
            tube_tables: tube_tables.unwrap_or(d.tube_tables),
            all_unknowns: false,
            ..d
        };
        let coupling =
            Coupling::parse(partition_coupling.unwrap_or("extrapolate")).map_err(invalid)?;
        let second = partition.unwrap_or_default();
        let inner = py
            .detach(|| {
                Stream::with_controls(
                    &ir,
                    &second,
                    coupling,
                    dt,
                    &opts,
                    u0,
                    &c0.unwrap_or_default(),
                )
            })
            .map_err(|e| SimulationError::new_err(e.to_string()))?;
        Ok(PyStream { inner })
    }

    /// The probes' names (`v(node)`), in the IR's order.
    #[getter]
    fn names(&self) -> Vec<String> {
        self.inner.names().to_vec()
    }

    /// Samples stepped so far.
    #[getter]
    fn steps(&self) -> usize {
        self.inner.steps()
    }

    /// The probes at sample 0: {name: float}.
    fn initial<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let d = PyDict::new(py);
        for (name, v) in self.inner.names().iter().zip(self.inner.initial()) {
            d.set_item(name, v)?;
        }
        Ok(d)
    }

    /// Feed input samples (volts), and the control inputs' over the same span
    /// (IR order; None: each holds its last value); returns {probe: array} for
    /// the samples stepped.
    #[pyo3(signature = (input, controls = None))]
    fn process<'py>(
        &mut self,
        py: Python<'py>,
        input: PyReadonlyArray1<'py, f64>,
        controls: Option<Vec<PyReadonlyArray1<'py, f64>>>,
    ) -> PyResult<Bound<'py, PyDict>> {
        let x = input.as_array().to_vec();
        let ctl: Vec<Vec<f64>> = controls
            .unwrap_or_default()
            .iter()
            .map(|c| c.as_array().to_vec())
            .collect();
        let inner = &mut self.inner;
        let vals = py
            .detach(|| {
                let ctl: Vec<&[f64]> = ctl.iter().map(Vec::as_slice).collect();
                inner.process_with(&x, &ctl)
            })
            .map_err(|e| SimulationError::new_err(e.to_string()))?;
        probe_dict(py, self.inner.names(), vals)
    }

    /// The input has ended: the samples the lookahead held back.
    fn finish<'py>(&mut self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let inner = &mut self.inner;
        let vals = py
            .detach(|| inner.finish())
            .map_err(|e| SimulationError::new_err(e.to_string()))?;
        probe_dict(py, self.inner.names(), vals)
    }

    /// New component values (the same circuit's IR), applied at the next
    /// sample boundaries the stream steps across. Raises ValueError for an IR
    /// that can't be split as the stream is; a change the step can't apply
    /// (nodes added or removed) raises SimulationError from `process`.
    fn update(&mut self, ir_json: &str) -> PyResult<()> {
        let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
        self.inner.update(&ir).map_err(invalid)
    }
}

#[pymodule]
fn circuitsim(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", crate::VERSION)?;
    m.add("SOURCE_HASH", crate::SOURCE_HASH)?;
    m.add("IR_VERSION", IR_VERSION)?;
    m.add("SimulationError", m.py().get_type::<SimulationError>())?;
    m.add_function(wrap_pyfunction!(ir_roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(simulate, m)?)?;
    m.add_class::<PyStream>()?;
    Ok(())
}
