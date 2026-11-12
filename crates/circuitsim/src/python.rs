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
    partition = None, partition_coupling = None, stats = false, progress = None, controls = None,
    notes = None, origin_samples = None, tape_gpu = None, hard_step_iterations = None
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
    notes: Option<Vec<(usize, String, u8, u8)>>,
    origin_samples: Option<u64>,
    tape_gpu: Option<bool>,
    hard_step_iterations: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let ir = CircuitIr::from_json(ir_json).map_err(invalid)?;
    let notes = note_events(notes.unwrap_or_default())?;
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
        origin_samples: origin_samples.unwrap_or(d.origin_samples),
        tape_gpu: tape_gpu.unwrap_or(d.tape_gpu),
        hard_step_iterations: hard_step_iterations.unwrap_or(d.hard_step_iterations),
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
        // Multi-rate sections (the IR's substeps) always run partitioned.
        let second = partition.clone().unwrap_or_default();
        if !second.is_empty() || ir.multirate() {
            crate::partition::simulate_partitioned_notes(
                &ir, &second, coupling, &x, &ctl, &notes, dt, &opts, every, report,
            )
        } else {
            crate::transient::simulate_notes(&ir, &x, &ctl, &notes, dt, &opts, every, report)
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
    st.set_item("events", s.events)?;
    st.set_item("late_events", s.late_events)?;
    st.set_item("latched_events", s.latched_events)?;
    st.set_item("accepted_by_level", s.accepted_by_level.to_vec())?;
    st.set_item("rejected_by_level", s.rejected_by_level.to_vec())?;
    Ok((probes, st).into_pyobject(py)?.into_any())
}

/// Note events from Python: (sample, kind, note, value), kind "on" (value the velocity),
/// "off", "pedal" (value 0 up, 1 down) or "pressure" (channel aftertouch, value 0-127;
/// note ignored).
fn note_events(
    notes: Vec<(usize, String, u8, u8)>,
) -> PyResult<Vec<(usize, crate::media::NoteEvent)>> {
    use crate::media::NoteEvent;
    notes
        .into_iter()
        .map(|(at, kind, note, value)| {
            let ev = match kind.as_str() {
                "on" => NoteEvent::On {
                    note,
                    velocity: value,
                },
                "off" => NoteEvent::Off { note },
                "pedal" => NoteEvent::Pedal { down: value > 0 },
                "pressure" => NoteEvent::Pressure {
                    value: value.min(127),
                },
                k => {
                    return Err(invalid(format!(
                        "note event kind {k:?}: on, off, pedal or pressure"
                    )));
                }
            };
            Ok((at, ev))
        })
        .collect()
}

/// The harp alone (`harp.rs`'s `render`; docs/RHODES_PLAN.md RH3): `element` an IR `harp`
/// element (JSON), `n` steps at `fs` from rest with `notes` as `simulate` takes them.
/// Returns (the EMF at every step, every internal sample, (k, s)): sample 0 is the rest's.
/// Releases the GIL.
#[pyfunction]
#[pyo3(signature = (element, fs, n, notes))]
fn harp_render<'py>(
    py: Python<'py>,
    element: &str,
    fs: f64,
    n: usize,
    notes: Vec<(usize, String, u8, u8)>,
) -> PyResult<Bound<'py, PyAny>> {
    let el: crate::ir::Harp =
        serde_json::from_str(element).map_err(|e| invalid(format!("harp_render: {e}")))?;
    el.model.check().map_err(invalid)?;
    let notes = note_events(notes)?;
    let (y, raw, ks) = py.detach(|| {
        let m = crate::harp::Medium::new(&el, fs);
        let ks = (m.k, m.s);
        let (y, raw) = crate::harp::render(&el, fs, n.max(1), &notes);
        (y, raw, ks)
    });
    Ok((y.into_pyarray(py), raw.into_pyarray(py), ks)
        .into_pyobject(py)?
        .into_any())
}

/// A Clavinet's strings alone (`clavinet.rs`'s `render`; docs/CLAVINET_PLAN.md CL3):
/// `element` an IR `clav_strings` element (JSON), `n` steps at `fs` from rest with `notes`
/// as `simulate` takes them, on `workers` worker threads (None: the default). Returns
/// (the centre pickup's EMF at every step, the bridge's, their internal samples, (k, s)):
/// sample 0 is the rest's. Releases the GIL.
#[pyfunction]
#[pyo3(signature = (element, fs, n, notes, workers=None))]
fn clav_render<'py>(
    py: Python<'py>,
    element: &str,
    fs: f64,
    n: usize,
    notes: Vec<(usize, String, u8, u8)>,
    workers: Option<usize>,
) -> PyResult<Bound<'py, PyAny>> {
    let el: crate::ir::ClavStrings =
        serde_json::from_str(element).map_err(|e| invalid(format!("clav_render: {e}")))?;
    let notes = note_events(notes)?;
    let (out, ks) = py.detach(|| {
        let out = crate::clavinet::render(&el, fs, n.max(1), &notes, workers);
        let ks = crate::clavinet::Medium::with_workers(&el, fs, 0).map(|m| (m.k, m.s));
        (out, ks)
    });
    let ([yc, yb], [rc, rb]) = out.map_err(invalid)?;
    let ks = ks.map_err(invalid)?;
    Ok((
        yc.into_pyarray(py),
        yb.into_pyarray(py),
        rc.into_pyarray(py),
        rb.into_pyarray(py),
        ks,
    )
        .into_pyobject(py)?
        .into_any())
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
        partition_coupling = None, c0 = None, error_abstol = None, error_reltol = None,
        step_selection = None, error_norm = None, hard_step_iterations = None
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
        error_abstol: Option<f64>,
        error_reltol: Option<f64>,
        step_selection: Option<bool>,
        error_norm: Option<&str>,
        hard_step_iterations: Option<usize>,
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
            error_abstol: error_abstol.unwrap_or(d.error_abstol),
            error_reltol: error_reltol.unwrap_or(d.error_reltol),
            step_selection: step_selection.unwrap_or(d.step_selection),
            error_norm: error_norm
                .map_or(Ok(d.error_norm), ErrorNorm::parse)
                .map_err(invalid)?,
            hard_step_iterations: hard_step_iterations.unwrap_or(d.hard_step_iterations),
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

/// The GPU the tape's recording kernel runs on with `tape_gpu=True` ("name (backend)"), or
/// None with why not: (description, None) or (None, reason).
#[pyfunction]
fn tape_gpu() -> (Option<String>, Option<String>) {
    match crate::tape_stream::gpu_available() {
        Ok(d) => (Some(d), None),
        Err(e) => (None, Some(e)),
    }
}

/// The tape medium's recording kernel (`crate::tape::record`; the reference is
/// `varimu.devices.tape.record`). `preisach`: (hc_median, sigma_ln_hc, sigma_hi, h_max,
/// n_table); `head`: (gap, pole, relax) in metres; `heights`: per layer; `zones`: per
/// layer, or per layer and cell (layers x cells, flattened);
/// `s_rec`, `hg`: per bias sample; `axes`: (cos, sin, weight) per easy-axis direction,
/// flattened; `h_static_x` / `_y` (during the pass), `h_end_x` / `_y` (after it): layers x
/// cells, flattened, or None; `table_step`: the head field's table step over the layer's
/// height (0: exact); `gpu`: on the GPU in f32 (the `gpu` feature); `threads`: the CPU
/// kernel's threads (0: every logical core; the result doesn't depend on it); `mean_field`
/// (alpha) and `ms_a_m`: the moving model's mean field alpha Ms M on every hysteron (an
/// opt-in variant, `crate::tape::record_mean_field`; 0: off); `astroid`: the axes driven by
/// `crate::tape::astroid_drive` (an opt-in variant). Returns (M_x, M_y) / Ms,
/// layers x cells flattened. Releases the GIL.
#[pyfunction]
#[pyo3(signature = (preisach, head, heights, zones, s_rec, hg, s_cells, axes, h_static_x = None, h_static_y = None, h_end_x = None, h_end_y = None, table_step = 0.0, gpu = false, threads = 0, mean_field = 0.0, ms_a_m = 0.0, astroid = false))]
#[allow(clippy::too_many_arguments)]
fn tape_record<'py>(
    py: Python<'py>,
    preisach: (f64, f64, f64, f64, usize),
    head: (f64, f64, f64),
    heights: PyReadonlyArray1<'py, f64>,
    zones: PyReadonlyArray1<'py, f64>,
    s_rec: PyReadonlyArray1<'py, f64>,
    hg: PyReadonlyArray1<'py, f64>,
    s_cells: PyReadonlyArray1<'py, f64>,
    axes: PyReadonlyArray1<'py, f64>,
    h_static_x: Option<PyReadonlyArray1<'py, f64>>,
    h_static_y: Option<PyReadonlyArray1<'py, f64>>,
    h_end_x: Option<PyReadonlyArray1<'py, f64>>,
    h_end_y: Option<PyReadonlyArray1<'py, f64>>,
    table_step: f64,
    gpu: bool,
    threads: usize,
    mean_field: f64,
    ms_a_m: f64,
    astroid: bool,
) -> PyResult<(Bound<'py, PyAny>, Bound<'py, PyAny>)> {
    let (heights, zones) = (heights.as_array().to_vec(), zones.as_array().to_vec());
    let (s_rec, hg) = (s_rec.as_array().to_vec(), hg.as_array().to_vec());
    let s_cells = s_cells.as_array().to_vec();
    let flat = axes.as_array().to_vec();
    let zones_ok = zones.len() == heights.len() || zones.len() == heights.len() * s_cells.len();
    if !flat.len().is_multiple_of(3) || !zones_ok || s_rec.len() != hg.len() {
        return Err(invalid("tape_record: mismatched array lengths"));
    }
    let axes: Vec<[f64; 3]> = flat.chunks(3).map(|c| [c[0], c[1], c[2]]).collect();
    let n = heights.len() * s_cells.len();
    let hx = h_static_x.map(|a| a.as_array().to_vec());
    let hy = h_static_y.map(|a| a.as_array().to_vec());
    if hx.as_ref().is_some_and(|v| v.len() != n) || hy.as_ref().is_some_and(|v| v.len() != n) {
        return Err(invalid("tape_record: h_static must be layers x cells"));
    }
    let hy = match (&hx, hy) {
        (Some(_), None) => Some(vec![0.0; n]),
        (_, y) => y,
    };
    let ex = h_end_x.map(|a| a.as_array().to_vec());
    let ey = h_end_y.map(|a| a.as_array().to_vec());
    if ex.as_ref().is_some_and(|v| v.len() != n) || ey.as_ref().is_some_and(|v| v.len() != n) {
        return Err(invalid("tape_record: h_end must be layers x cells"));
    }
    let ey = match (&ex, ey) {
        (Some(_), None) => Some(vec![0.0; n]),
        (_, y) => y,
    };
    let (mx, my) = py
        .detach(|| {
            let p =
                crate::tape::preisach(preisach.0, preisach.1, preisach.2, preisach.3, preisach.4);
            let rec = crate::tape::Recording {
                preisach: &p,
                head: crate::tape::Head {
                    gap: head.0,
                    pole: head.1,
                    relax: head.2,
                },
                heights: &heights,
                zones: &zones,
                s_rec: &s_rec,
                hg: &hg,
                s_cells: &s_cells,
                axes: &axes,
                h_static: match (&hx, &hy) {
                    (Some(x), Some(y)) => Some((x.as_slice(), y.as_slice())),
                    _ => None,
                },
                h_end: match (&ex, &ey) {
                    (Some(x), Some(y)) => Some((x.as_slice(), y.as_slice())),
                    _ => None,
                },
                table_step,
                threads,
                gpu,
            };
            crate::tape::record_mean_field(&rec, mean_field, ms_a_m, astroid)
        })
        .map_err(invalid)?;
    Ok((
        mx.into_pyarray(py).into_any(),
        my.into_pyarray(py).into_any(),
    ))
}

/// The tape between the heads (`crate::tape_stream::TapeStream`; the reference is
/// `varimu.devices.tape_machine.TapeStream`): `params` its JSON (`stream_params`), fs the
/// step rate, `h` the record gap's signal field per step, pushed `chunk` at a time;
/// `noise_seed`: the coating's grain on, keyed by (seed, "tape"); `transport_seed`: the
/// transport's random parts' (seed, "transport"); `supply_hz`: varispeed's capstan supply
/// frequency per push (a medium with `varispeed` needs it); `bias_a_m`: a reduced
/// medium's bias changes, (push index, deep-gap peak A/m) rising, each set before that
/// push (the pushes split there); `origin`: the stream starts at that step of a longer run
/// (`TapeStream::set_origin`); `gpu`: the recording kernel on the GPU in f32
/// (`TapeStream::set_gpu`). Returns the repro EMF after each push (at t_{n+1});
/// `readouts`: {"emf": that, and the medium's other readouts per push: "cross" (crosstalk),
/// "sync" and "sync_cross" (Sel-Sync), those it has}.
/// With the literal bias (`bias_substeps` M), `h` is the head's whole field, M samples per
/// step (`chunk` a multiple of M). Releases the GIL.
/// The moving model's solver counters since the last call: (samples solved, samples not
/// converged, the largest residual left in M / Ms); resets them.
#[pyfunction]
fn tape_moving_stats() -> (usize, usize, f64) {
    crate::tape::moving_stats()
}

#[pyfunction]
#[pyo3(signature = (params, fs, h, chunk = 4800, noise_seed = None, transport_seed = 0, supply_hz = None, bias_a_m = None, origin = 0, gpu = false, readouts = false))]
#[allow(clippy::too_many_arguments)]
fn tape_stream_run<'py>(
    py: Python<'py>,
    params: &str,
    fs: f64,
    h: PyReadonlyArray1<'py, f64>,
    chunk: usize,
    noise_seed: Option<u64>,
    transport_seed: u64,
    supply_hz: Option<PyReadonlyArray1<'py, f64>>,
    bias_a_m: Option<Vec<(usize, f64)>>,
    origin: u64,
    gpu: bool,
    readouts: bool,
) -> PyResult<Bound<'py, PyAny>> {
    let p: crate::tape_stream::TapeParams =
        serde_json::from_str(params).map_err(|e| invalid(format!("tape_stream_run: {e}")))?;
    let h = h.as_array().to_vec();
    let supply = supply_hz.map(|s| s.as_array().to_vec());
    let changes = bias_a_m.unwrap_or_default();
    let has = (p.crosstalk.is_some(), p.sync.is_some());
    let out = py.detach(
        || -> Result<(Vec<f64>, crate::tape_stream::Readouts), String> {
            let mut st = crate::tape_stream::TapeStream::build(
                &p,
                fs,
                noise_seed.map(|seed| (seed, "tape")),
                transport_seed,
            )?;
            st.set_origin(origin)?;
            st.set_gpu(gpu)?;
            let mut out = Vec::with_capacity(h.len());
            let mut all = crate::tape_stream::Readouts::default();
            let mut part = crate::tape_stream::Readouts::default();
            let m = st.substeps();
            let chunk = (chunk.max(1)).div_ceil(m) * m;
            // Pushed `chunk` at a time, split at each bias change.
            let cuts = changes
                .iter()
                .map(|c| (c.0 * m).min(h.len()))
                .chain(std::iter::once(h.len()));
            let mut pos = 0;
            for (ci, end) in cuts.enumerate() {
                while pos < end {
                    let e = (pos + chunk).min(end);
                    let c = &h[pos..e];
                    // Varispeed: the supply's frequency at each push (one per push).
                    let sup = supply.as_ref().map(|sup| {
                        let k0 = pos / m;
                        let k1 = (k0 + c.len() / m).min(sup.len());
                        &sup[k0..k1]
                    });
                    match (readouts, sup) {
                        (true, sup) => {
                            st.push_many_readouts(c, sup, &mut out, &mut part)?;
                            all.cross.extend_from_slice(&part.cross);
                            all.sync.extend_from_slice(&part.sync);
                            all.sync_cross.extend_from_slice(&part.sync_cross);
                        }
                        (false, Some(sup)) => st.push_many_supply(c, sup, &mut out)?,
                        (false, None) => st.push_many(c, &mut out)?,
                    }
                    pos = e;
                }
                if let Some(&(_, hg)) = changes.get(ci) {
                    st.set_bias(hg)?;
                }
            }
            Ok((out, all))
        },
    );
    let (out, all) = out.map_err(|e| invalid(&e))?;
    if readouts {
        let d = PyDict::new(py);
        d.set_item("emf", out.into_pyarray(py))?;
        if has.0 {
            d.set_item("cross", all.cross.into_pyarray(py))?;
        }
        if has.1 {
            d.set_item("sync", all.sync.into_pyarray(py))?;
        }
        if has.0 && has.1 {
            d.set_item("sync_cross", all.sync_cross.into_pyarray(py))?;
        }
        return Ok(d.into_any());
    }
    Ok(out.into_pyarray(py).into_any())
}

/// The tape particles' state after field histories (`crate::tape::Preisach::state_after`;
/// the reference is `varimu.devices.preisach.Preisach.state_after`): `h` cells x samples,
/// flattened row-major with `samples` per cell.
#[pyfunction]
fn tape_state_after<'py>(
    py: Python<'py>,
    preisach: (f64, f64, f64, f64, usize),
    h: PyReadonlyArray1<'py, f64>,
    samples: usize,
) -> PyResult<Bound<'py, PyAny>> {
    let h = h.as_array().to_vec();
    if samples == 0 || !h.len().is_multiple_of(samples) {
        return Err(invalid("tape_state_after: h must be cells x samples"));
    }
    let out: Vec<f64> = py.detach(|| {
        let p = crate::tape::preisach(preisach.0, preisach.1, preisach.2, preisach.3, preisach.4);
        h.chunks(samples).map(|c| p.state_after(c)).collect()
    });
    Ok(out.into_pyarray(py).into_any())
}

/// The moving model's M_x / Ms after field histories along x (`crate::tape::moving_history`;
/// the reference is `varimu.tape_variants.along_x`): `h` histories x samples, flattened
/// row-major with `samples` per history; `axes` (cos, sin, weight) per easy axis,
/// flattened; `a` = alpha Ms (A/m).
#[pyfunction]
fn tape_moving_along_x<'py>(
    py: Python<'py>,
    preisach: (f64, f64, f64, f64, usize),
    axes: PyReadonlyArray1<'py, f64>,
    h: PyReadonlyArray1<'py, f64>,
    samples: usize,
    a: f64,
) -> PyResult<Bound<'py, PyAny>> {
    let h = h.as_array().to_vec();
    let flat = axes.as_array().to_vec();
    if samples == 0 || !h.len().is_multiple_of(samples) || !flat.len().is_multiple_of(3) {
        return Err(invalid(
            "tape_moving_along_x: h must be histories x samples",
        ));
    }
    let axes: Vec<[f64; 3]> = flat.chunks(3).map(|c| [c[0], c[1], c[2]]).collect();
    let out: Vec<f64> = py.detach(|| {
        let p = crate::tape::preisach(preisach.0, preisach.1, preisach.2, preisach.3, preisach.4);
        h.chunks(samples)
            .map(|c| {
                let hist: Vec<(f64, f64)> = c.iter().map(|&x| (x, 0.0)).collect();
                crate::tape::moving_history(&p, &axes, &hist, a).0
            })
            .collect()
    });
    Ok(out.into_pyarray(py).into_any())
}

#[pymodule]
fn circuitsim(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", crate::VERSION)?;
    m.add("SOURCE_HASH", crate::SOURCE_HASH)?;
    m.add("IR_VERSION", IR_VERSION)?;
    m.add("SimulationError", m.py().get_type::<SimulationError>())?;
    m.add_function(wrap_pyfunction!(ir_roundtrip, m)?)?;
    m.add_function(wrap_pyfunction!(simulate, m)?)?;
    m.add_function(wrap_pyfunction!(harp_render, m)?)?;
    m.add_function(wrap_pyfunction!(clav_render, m)?)?;
    m.add_function(wrap_pyfunction!(tape_record, m)?)?;
    m.add_function(wrap_pyfunction!(tape_moving_stats, m)?)?;
    m.add_function(wrap_pyfunction!(tape_moving_along_x, m)?)?;
    m.add_function(wrap_pyfunction!(tape_gpu, m)?)?;
    m.add_function(wrap_pyfunction!(tape_state_after, m)?)?;
    m.add_function(wrap_pyfunction!(tape_stream_run, m)?)?;
    m.add_class::<PyStream>()?;
    Ok(())
}
