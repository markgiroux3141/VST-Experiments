//! Heated cathodes against the Python reference (`varimu/devices/cathode.py`'s `heated`,
//! exported by `scripts/export_circuit_fixtures.py` into `fixtures/cathode/`): the currents to
//! 1e-12, and the analytic Jacobian against finite differences.

use std::fs;
use std::path::Path;

use circuitsim::cathode::{Emission, Heated};
use circuitsim::devices::{self, Device};
use circuitsim::ir::DeviceModel;
use serde::Deserialize;

#[derive(Deserialize)]
struct Fixture {
    phi_ev: f64,
    n: f64,
    t0_k: f64,
    devices: Vec<Entry>,
}

#[derive(Deserialize)]
struct Entry {
    model: DeviceModel,
    port: usize,
    is0_a: f64,
    points: Vec<Point>,
}

#[derive(Deserialize)]
struct Point {
    v: Vec<f64>,
    t_k: f64,
    i_ref: f64,
    currents: Vec<f64>,
}

fn fixture() -> Fixture {
    let path = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/cathode/cathode.json");
    serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap()
}

fn heated(fx: &Fixture, e: &Entry, p: &Point) -> Heated {
    let em = Emission {
        is0_a: e.is0_a,
        phi_ev: fx.phi_ev,
        n: fx.n,
        t0_k: fx.t0_k,
    };
    let mut h = Heated::new(devices::from_model(&e.model), e.port, em);
    h.set_cathode(p.t_k, p.i_ref);
    h
}

#[test]
fn heated_tubes_equal_the_reference() {
    let fx = fixture();
    for e in &fx.devices {
        for p in &e.points {
            let h = heated(&fx, e, p);
            let np = h.ports();
            let (mut i, mut g) = (vec![0.0; np], vec![0.0; np * np]);
            h.eval(&p.v, &mut i, &mut g);
            for (a, b) in i.iter().zip(&p.currents) {
                let tol = 1e-12 * b.abs().max(1e-12);
                assert!(
                    (a - b).abs() <= tol,
                    "{:?} at {:?} T {} i_ref {}: {a} vs {b}",
                    e.model.name(),
                    p.v,
                    p.t_k,
                    p.i_ref
                );
            }
        }
    }
}

#[test]
fn the_jacobian_is_the_derivative() {
    let fx = fixture();
    for e in &fx.devices {
        for p in &e.points {
            let h = heated(&fx, e, p);
            let np = h.ports();
            let (mut i, mut g) = (vec![0.0; np], vec![0.0; np * np]);
            h.eval(&p.v, &mut i, &mut g);
            for k in 0..np {
                let d = 1e-6 * p.v[k].abs().max(1.0);
                let (mut vp, mut vm) = (p.v.clone(), p.v.clone());
                vp[k] += d;
                vm[k] -= d;
                let (mut ip, mut im) = (vec![0.0; np], vec![0.0; np]);
                let mut gg = vec![0.0; np * np];
                h.eval(&vp, &mut ip, &mut gg);
                h.eval(&vm, &mut im, &mut gg);
                for j in 0..np {
                    let fd = (ip[j] - im[j]) / (2.0 * d);
                    let an = g[j * np + k];
                    let scale = an.abs().max(fd.abs()).max(1e-9);
                    assert!(
                        (fd - an).abs() <= 1e-4 * scale,
                        "{:?} d i{j}/d v{k} at {:?} T {}: analytic {an} vs fd {fd}",
                        e.model.name(),
                        p.v,
                        p.t_k
                    );
                }
            }
        }
    }
}
