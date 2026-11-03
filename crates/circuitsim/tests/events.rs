//! Technique K's event kernels (`circuitsim::events`) against the Python reference
//! (`varimu.devices.thyratron_events`), on the fixtures `scripts/export_circuit_fixtures.py`
//! writes: the kernels, step charges, crossing predictions, table lookups and per-sample
//! runs (senses in, held currents out) on a synthetic unit.

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use circuitsim::events::{
    KERNEL_ATTEN_DB, Lookup, Run, Tables, minphase_lowpass, predict_crossing, step_charges,
};
use circuitsim::ir::{Element, ThyratronEvents};
use serde::Deserialize;

#[derive(Deserialize)]
struct Charges {
    pulse: Vec<f64>,
    filtered: Vec<Vec<f64>>,
    raw: Vec<Vec<f64>>,
}

#[derive(Deserialize)]
struct Crossing {
    m: [f64; 3],
    phi: Option<f64>,
}

#[derive(Deserialize)]
struct LookupCase {
    v_g: f64,
    slope: f64,
    v_s: f64,
    dead_s: f64,
    latched: bool,
    q: Option<Vec<Vec<f64>>>,
    q_raw: Option<Vec<Vec<f64>>>,
    q_grid: Option<Vec<Vec<f64>>>,
    centroid: f64,
}

#[derive(Deserialize)]
struct RunCase {
    h: f64,
    senses: Vec<[f64; 2]>,
    currents: Vec<f64>,
    grid_currents: Vec<f64>,
    comp_currents: Vec<f64>,
    events: u64,
    late: u64,
    latched: u64,
}

#[derive(Deserialize)]
struct Fixture {
    element: Element,
    kernels: BTreeMap<String, Vec<f64>>,
    step_charges: BTreeMap<String, Charges>,
    crossings: Vec<Crossing>,
    lookups: Vec<LookupCase>,
    runs: Vec<RunCase>,
}

fn fixture() -> Fixture {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join("events")
        .join("events.json");
    serde_json::from_str(&fs::read_to_string(path).expect("events.json")).expect("parse")
}

fn element(f: &Fixture) -> ThyratronEvents {
    match &f.element {
        Element::ThyratronEvents(e) => e.clone(),
        _ => panic!("the fixture's element is a ThyratronEvents"),
    }
}

/// Max |a - b| over max |b| (0 when both are all zeros).
fn rel_err(a: &[f64], b: &[f64]) -> f64 {
    assert_eq!(a.len(), b.len());
    let scale = b.iter().fold(0.0f64, |m, x| m.max(x.abs()));
    let diff = a
        .iter()
        .zip(b)
        .fold(0.0f64, |m, (x, y)| m.max((x - y).abs()));
    if scale == 0.0 { diff } else { diff / scale }
}

/// The min-phase kernel's cepstrum takes the log of a 100 dB stopband: roundoff in the
/// FFTs (rustfft's against numpy's) comes back ~4e-12 of the peak (-230 dB).
const KERNEL_TOL: f64 = 1e-10;

#[test]
fn kernels_match_python() {
    let f = fixture();
    for (m, want) in &f.kernels {
        let got = minphase_lowpass(m.parse().expect("m"), KERNEL_ATTEN_DB);
        let e = rel_err(&got, want);
        assert!(e < KERNEL_TOL, "m {m}: kernel off by {e:e}");
    }
}

#[test]
fn step_charges_match_python() {
    let f = fixture();
    let rate = element(&f).ref_rate_hz;
    for (m, c) in &f.step_charges {
        let m: usize = m.parse().expect("m");
        let h = minphase_lowpass(m, KERNEL_ATTEN_DB);
        for (got, want) in [
            (step_charges(&c.pulse, &h, m, rate), &c.filtered),
            (step_charges(&c.pulse, &[1.0], m, rate), &c.raw),
        ] {
            assert_eq!(got.len(), m + 1);
            let e = rel_err(&got.concat(), &want.concat());
            assert!(e < KERNEL_TOL, "m {m}: step charges off by {e:e}");
        }
    }
}

#[test]
fn crossings_match_python_exactly() {
    for c in fixture().crossings {
        assert_eq!(predict_crossing(c.m), c.phi, "margins {:?}", c.m);
    }
}

#[test]
fn lookups_match_python() {
    let f = fixture();
    let el = element(&f);
    // 32 reference samples per step at 96 kHz
    let t = Tables::new(&el, 32.0 / el.ref_rate_hz).expect("tables");
    let mut lk = Lookup::default();
    for c in &f.lookups {
        t.lookup(c.v_g, c.slope, &mut lk);
        let at = format!("v_g {} slope {}", c.v_g, c.slope);
        assert_eq!(lk.latched, c.latched, "{at}");
        assert!((lk.v_s - c.v_s).abs() <= 1e-13 * c.v_s.abs(), "{at}: v_s");
        assert!(
            (lk.dead_s - c.dead_s).abs() <= 1e-13 * c.dead_s.abs(),
            "{at}: dead"
        );
        if !c.latched {
            assert!(
                (lk.centroid - c.centroid).abs() <= 1e-12 * c.centroid.abs(),
                "{at}: centroid"
            );
        }
        if let Some(g) = &c.q_grid {
            let eg = rel_err(&lk.q_grid, &g.concat());
            assert!(eg < KERNEL_TOL, "{at}: q_grid off by {eg:e}");
        }
        if let (Some(q), Some(r)) = (&c.q, &c.q_raw) {
            let (eq, er) = (rel_err(&lk.q, &q.concat()), rel_err(&lk.q_raw, &r.concat()));
            assert!(eq < KERNEL_TOL, "{at}: q off by {eq:e}");
            // the raw charges take no kernel
            assert!(er < 1e-13, "{at}: q_raw off by {er:e}");
        }
    }
}

#[test]
fn runs_match_python() {
    let f = fixture();
    let el = element(&f);
    for (n, c) in f.runs.iter().enumerate() {
        let mut run = Run::new(&el, c.h).expect("run");
        let (mut grid, mut comp) = (Vec::new(), Vec::new());
        let got: Vec<f64> = c
            .senses
            .iter()
            .map(|s| {
                let i = run.sense(s[0], s[1]);
                grid.push(run.grid_current());
                comp.push(run.comp_current());
                i
            })
            .collect();
        assert_eq!(
            (run.counts.events, run.counts.late, run.counts.latched),
            (c.events, c.late, c.latched),
            "run {n}: counts"
        );
        let e = rel_err(&got, &c.currents);
        assert!(e < 1e-9, "run {n}: currents off by {e:e}");
        let e = rel_err(&grid, &c.grid_currents);
        assert!(e < 1e-9, "run {n}: grid currents off by {e:e}");
        let e = rel_err(&comp, &c.comp_currents);
        assert!(e < 1e-9, "run {n}: the deficit's currents off by {e:e}");
    }
}

#[test]
fn a_step_that_isnt_whole_reference_samples_is_refused() {
    let el = element(&fixture());
    let err = Tables::new(&el, 1.0 / 44_100.0).expect_err("44.1 kHz");
    assert!(err.contains("whole number"), "{err}");
}
