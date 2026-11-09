//! The reset and edge event kernels (`circuitsim::reset_events`) against the Python reference
//! (`varimu.devices.reset_events`), on the fixture `scripts/export_circuit_fixtures.py` writes:
//! the Minimoog oscillator's tables as elements, an edge's band-limited step tables, and
//! per-sample runs of a reset with an edge following it on an emulated oscillator (senses in,
//! held currents out).

use std::collections::BTreeMap;
use std::fs;
use std::path::PathBuf;

use circuitsim::events::{KERNEL_ATTEN_DB, minphase_lowpass};
use circuitsim::ir::{EdgeEvents, Element, ResetEvents};
use circuitsim::reset_events::{EdgeRun, ResetRun, edge_step_table};
use serde::Deserialize;

#[derive(Deserialize)]
struct Steps {
    shape: Vec<f64>,
    steps: Vec<Vec<f64>>,
}

#[derive(Deserialize)]
struct RunCase {
    h: f64,
    ramp: Vec<f64>,
    reset_currents: Vec<f64>,
    comp_currents: Vec<f64>,
    diffs: Vec<f64>,
    edge_currents: Vec<f64>,
    resets: u64,
    reset_late: u64,
    edges: u64,
    edge_late: u64,
}

#[derive(Deserialize)]
struct Fixture {
    reset: Element,
    edge: Element,
    edge_steps: BTreeMap<String, Steps>,
    runs: Vec<RunCase>,
}

fn fixture() -> Fixture {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join("events")
        .join("reset_events.json");
    serde_json::from_str(&fs::read_to_string(path).expect("reset_events.json")).expect("parse")
}

fn elements(f: &Fixture) -> (ResetEvents, EdgeEvents) {
    let Element::ResetEvents(r) = f.reset.clone() else {
        panic!("the fixture's reset is a ResetEvents")
    };
    let Element::EdgeEvents(e) = f.edge.clone() else {
        panic!("the fixture's edge is an EdgeEvents")
    };
    (r, e)
}

/// |a - b| within rel of the scale, or abs.
fn close(a: f64, b: f64, scale: f64, rel: f64, what: &str) {
    assert!(
        (a - b).abs() <= rel * scale.abs() + 1e-30,
        "{what}: {a} vs {b} (scale {scale})"
    );
}

#[test]
fn edge_step_tables_are_pythons() {
    let f = fixture();
    for (m, s) in &f.edge_steps {
        let m: usize = m.parse().unwrap();
        let got = edge_step_table(&s.shape, &minphase_lowpass(m, KERNEL_ATTEN_DB), m);
        assert_eq!(got.len(), s.steps.len());
        for (g, w) in got.iter().zip(&s.steps) {
            assert_eq!(g.len(), w.len(), "m {m}: steps per row");
            for (a, b) in g.iter().zip(w) {
                // numpy sums each step pairwise, Rust in order: ~1e-12 apart
                close(*a, *b, 1.0, 1e-10, "edge step table");
            }
        }
    }
}

#[test]
fn runs_are_pythons() {
    let f = fixture();
    let (re, ee) = elements(&f);
    let gain = ee
        .follow_gain
        .expect("the fixture's edge follows the reset");
    for case in &f.runs {
        let mut reset = ResetRun::new(&re, case.h).expect("reset tables");
        let mut edge = EdgeRun::new(&ee, case.h).expect("edge tables");
        let peak = case
            .reset_currents
            .iter()
            .fold(0.0_f64, |m, x| m.max(x.abs()));
        let on = case
            .edge_currents
            .iter()
            .fold(0.0_f64, |m, x| m.max(x.abs()));
        for (k, &v) in case.ramp.iter().enumerate() {
            let i = reset.sense(v);
            close(
                i,
                case.reset_currents[k],
                peak,
                1e-10,
                "the reset's current",
            );
            close(
                reset.comp_current(),
                case.comp_currents[k],
                peak,
                1e-10,
                "the reset's deficit",
            );
            // the edge's input: Python's (its divider of the ramp, the wobble)
            let j = edge.sense(case.diffs[k], Some(reset.lead()));
            close(j, case.edge_currents[k], on, 1e-10, "the edge's current");
        }
        assert_eq!(reset.counts.events, case.resets);
        assert_eq!(reset.counts.late, case.reset_late);
        assert_eq!(edge.counts.events, case.edges);
        assert_eq!(edge.counts.late, case.edge_late);
        assert!(case.resets > 0 && case.edges > 0 && gain > 0.0);
    }
}
