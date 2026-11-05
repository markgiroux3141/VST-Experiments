//! Python bindings (feature "python"), built by maturin as the module `roomsim`. Arrays come
//! in flat (float64, uint32) and go out flat; `varimu.rooms.gpu` shapes them. Every call
//! releases the GIL. `backend` is "gpu" or "cpu" (the f64 reference).

use numpy::{IntoPyArray, PyReadonlyArray1};
use pyo3::exceptions::{PyRuntimeError, PyValueError};
use pyo3::prelude::*;

use crate::rays::{BANDS, RayRoom};
use crate::spectra::ImageSpectra;

fn invalid(e: impl ToString) -> PyErr {
    PyValueError::new_err(e.to_string())
}

fn gpu_err(e: impl ToString) -> PyErr {
    PyRuntimeError::new_err(e.to_string())
}

fn triples(v: &[f64]) -> Vec<[f64; 3]> {
    v.chunks_exact(3).map(|c| [c[0], c[1], c[2]]).collect()
}

/// The GPU's name and backend; raises RuntimeError when there is none.
#[pyfunction]
fn gpu_info(py: Python<'_>) -> PyResult<String> {
    py.detach(|| crate::gpu::gpu().map(|g| g.describe()))
        .map_err(gpu_err)
}

/// rays.rs's run. tris: T x 9 (v0, v1, v2), tri_face: T, normals: F x 3, alpha: F x 7,
/// scattering: F, receivers: R x 3, source: 3, dirs: N x 3. Returns (travelling (7 x nt),
/// density (R x 7 x nt), nt), flat.
#[pyfunction]
#[pyo3(signature = (tris, tri_face, normals, alpha, scattering, receivers, source, dirs,
                    t_max_s, fs_env, radius_m, c, seed, max_bounces=10_000, backend="gpu"))]
#[allow(clippy::too_many_arguments)]
fn ray_trace<'py>(
    py: Python<'py>,
    tris: PyReadonlyArray1<f64>,
    tri_face: PyReadonlyArray1<u32>,
    normals: PyReadonlyArray1<f64>,
    alpha: PyReadonlyArray1<f64>,
    scattering: PyReadonlyArray1<f64>,
    receivers: PyReadonlyArray1<f64>,
    source: PyReadonlyArray1<f64>,
    dirs: PyReadonlyArray1<f64>,
    t_max_s: f64,
    fs_env: f64,
    radius_m: f64,
    c: f64,
    seed: u32,
    max_bounces: u32,
    backend: &str,
) -> PyResult<Bound<'py, PyAny>> {
    let t = tris.as_slice()?;
    if t.len() % 9 != 0 {
        return Err(invalid("tris: T x 9"));
    }
    let room = RayRoom {
        tris: t
            .chunks_exact(9)
            .map(|c| [[c[0], c[1], c[2]], [c[3], c[4], c[5]], [c[6], c[7], c[8]]])
            .collect(),
        tri_face: tri_face.as_slice()?.to_vec(),
        normals: triples(normals.as_slice()?),
        alpha: alpha
            .as_slice()?
            .chunks_exact(BANDS)
            .map(|c| c.try_into().unwrap())
            .collect(),
        scattering: scattering.as_slice()?.to_vec(),
        receivers: triples(receivers.as_slice()?),
        radius_m,
        c,
        t_max_s,
        fs_env,
        seed,
        max_bounces,
    };
    let src = source.as_slice()?;
    if src.len() != 3 {
        return Err(invalid("source: 3"));
    }
    let src = [src[0], src[1], src[2]];
    let dirs = triples(dirs.as_slice()?);
    let gpu_wanted = match backend {
        "gpu" => true,
        "cpu" => false,
        b => return Err(invalid(format!("backend {b:?}: gpu or cpu"))),
    };
    let r = py
        .detach(|| {
            if gpu_wanted {
                crate::rays::trace_gpu(crate::gpu::gpu()?, &room, src, &dirs)
            } else {
                crate::rays::trace_cpu(&room, src, &dirs)
            }
        })
        .map_err(gpu_err)?;
    Ok((
        r.travelling.into_pyarray(py),
        r.density.into_pyarray(py),
        r.nt,
    )
        .into_pyobject(py)?
        .into_any())
}

/// spectra.rs's sum. coarse: S x E x G x 2 (re, im), delay: I (samples), idx: K, w: K;
/// spec_index (I, uint32) and scale (I) optional (spectra.rs: shared spectra). Returns
/// E x K x 2 (re, im), flat.
#[pyfunction]
#[pyo3(signature = (coarse, n_ent, n_grid, delay, idx, w, n_fft, backend="gpu",
                    spec_index=None, scale=None))]
#[allow(clippy::too_many_arguments)]
fn image_spectra<'py>(
    py: Python<'py>,
    coarse: PyReadonlyArray1<f64>,
    n_ent: usize,
    n_grid: usize,
    delay: PyReadonlyArray1<f64>,
    idx: PyReadonlyArray1<u32>,
    w: PyReadonlyArray1<f64>,
    n_fft: usize,
    backend: &str,
    spec_index: Option<PyReadonlyArray1<u32>>,
    scale: Option<PyReadonlyArray1<f64>>,
) -> PyResult<Bound<'py, PyAny>> {
    if !(1..=2).contains(&n_ent) {
        return Err(invalid("n_ent: 1 or 2"));
    }
    let s = ImageSpectra {
        coarse: coarse
            .as_slice()?
            .chunks_exact(2)
            .map(|c| [c[0], c[1]])
            .collect(),
        n_ent,
        n_grid,
        delay: delay.as_slice()?.to_vec(),
        spec_index: match &spec_index {
            Some(a) => a.as_slice()?.to_vec(),
            None => Vec::new(),
        },
        scale: match &scale {
            Some(a) => a.as_slice()?.to_vec(),
            None => Vec::new(),
        },
        idx: idx.as_slice()?.to_vec(),
        w: w.as_slice()?.to_vec(),
        n_fft,
    };
    let gpu_wanted = match backend {
        "gpu" => true,
        "cpu" => false,
        b => return Err(invalid(format!("backend {b:?}: gpu or cpu"))),
    };
    let out = py
        .detach(|| {
            if gpu_wanted {
                crate::spectra::spectra_gpu(crate::gpu::gpu()?, &s)
            } else {
                crate::spectra::spectra_cpu(&s)
            }
        })
        .map_err(gpu_err)?;
    let flat: Vec<f64> = out.into_iter().flatten().collect();
    Ok(flat.into_pyarray(py).into_any())
}

#[pymodule]
fn roomsim(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", crate::VERSION)?;
    m.add("SOURCE_HASH", crate::SOURCE_HASH)?;
    m.add_function(wrap_pyfunction!(gpu_info, m)?)?;
    m.add_function(wrap_pyfunction!(ray_trace, m)?)?;
    m.add_function(wrap_pyfunction!(image_spectra, m)?)?;
    crate::fdtd::python::register(m)?;
    Ok(())
}
