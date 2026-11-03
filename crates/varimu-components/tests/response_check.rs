//! The response module (`varimu_components::response`) against circuitsim's transient on
//! the IR both builders make from the same saved version (the transformer part's
//! `component:`, linear cores): a sine through the circuit, its steady state fitted, at
//! a few frequencies. Checks that the module's network is the macro's (windings, the
//! coupled leakage, the core node's gap and eddy loss, the compiled capacitors and their
//! terminals), not only its own algebra (its unit tests).

// Small dense least squares by index.
#![allow(clippy::needless_range_loop)]

use std::f64::consts::PI;
use std::path::{Path, PathBuf};

use num_complex::Complex64 as C;
use varimu_circuit::spec::{load_circuit, resolve};
use varimu_circuit::yaml::{self, Value};
use varimu_circuit::{Cores, Library, build_ir};
use varimu_components::compile::compile;
use varimu_components::design::Design;
use varimu_components::edit::design_of_version;
use varimu_components::response::{Ground, Network, Setup, at};
use varimu_components::tables::Tables;

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

/// The compiled transformer of a saved version, recompiled from its construction.
fn compiled(reference: &str) -> varimu_components::compile::Compiled {
    let cfg = config();
    let lib = Library::new(&cfg);
    let v = lib.component_data(reference).unwrap();
    let d = Design::parse(&design_of_version(&v).unwrap()).unwrap();
    compile(&d, &Tables::load(&cfg).unwrap(), &lib).unwrap()
}

/// out / in at `f` from circuitsim: a sine, the last cycles' steady state fitted (with
/// an offset and a slope for what's left of the start's slow transient).
fn transient(circuit: &str, reference: &str, f: f64) -> C {
    let dir = std::env::temp_dir().join(format!("varimu_response_check_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    let path = dir.join(format!("{}.yaml", reference.replace('@', "_")));
    std::fs::write(&path, circuit).unwrap();
    let spec = load_circuit(&path).unwrap();
    let p = resolve(&spec, &[("t_model".into(), Value::Str(reference.into()))]).unwrap();
    let lib = Library::new(config());
    let ir = build_ir(&lib, &spec, &p, Cores::Linear).unwrap();
    let per = 400.0;
    let h = 1.0 / (f * per);
    let cycles = (0.4 * f).max(40.0);
    let n = (cycles * per) as usize;
    let x: Vec<f64> = (0..n)
        .map(|i| (2.0 * PI * f * i as f64 * h).sin())
        .collect();
    let out = circuitsim::simulate(&ir, &x, h, &circuitsim::transient::Options::default()).unwrap();
    let y = &out.values[out.names.iter().position(|s| s == "v(out)").unwrap()];
    // Least squares on the last 20 cycles: y = a sin + b cos + c + d t.
    let m = (20.0 * per) as usize;
    let mut ata = [[0.0f64; 4]; 4];
    let mut atb = [0.0f64; 4];
    for i in (n - m)..n {
        let t = i as f64 * h;
        let row = [
            (2.0 * PI * f * t).sin(),
            (2.0 * PI * f * t).cos(),
            1.0,
            t - (n - m) as f64 * h,
        ];
        for r in 0..4 {
            for c in 0..4 {
                ata[r][c] += row[r] * row[c];
            }
            atb[r] += row[r] * y[i];
        }
    }
    // Gauss-Jordan on the 4 x 4 normal equations.
    for col in 0..4 {
        let piv = (col..4)
            .max_by(|&a, &b| ata[a][col].abs().total_cmp(&ata[b][col].abs()))
            .unwrap();
        ata.swap(col, piv);
        atb.swap(col, piv);
        for r in 0..4 {
            if r != col {
                let k = ata[r][col] / ata[col][col];
                for c in 0..4 {
                    ata[r][c] -= k * ata[col][c];
                }
                atb[r] -= k * atb[col];
            }
        }
    }
    let (a, b) = (atb[0] / ata[0][0], atb[1] / ata[1][1]);
    // a sin + b cos = Re{(b - j a) e^{jwt}}... as a phasor of sin: a + j b.
    C::new(a, b)
}

fn check(circuit: &str, reference: &str, s: &Setup, freqs: &[f64], tol: f64) {
    let c = compiled(reference);
    let net = Network::of(&c);
    for &f in freqs {
        let (h, _) = at(&net, s, f).unwrap();
        let t = transient(circuit, reference, f);
        let err = (h - t).norm() / t.norm();
        println!("{reference} {f:>7} Hz: module {h:.6}, circuitsim {t:.6}, {err:.2e}");
        assert!(err < tol, "{reference} at {f} Hz: {h} vs {t} ({err:.2e})");
    }
}

/// BV191@3 (disc windings, coupled leakage, its compiled capacitors, a shield's to
/// ground), the primary halves in series from a line source into a grid leak.
#[test]
fn bv191_agrees_with_circuitsim() {
    let circuit = "\
title: response check
input: in
probes: [out]
values:
  t_model: {value: BV191@3, source: test}
  r_s: {value: 200.0, source: test}
  r_l: {value: 1.0e+5, source: test}
sections:
  - title: t
    parts:
      RS: {R: [in, p], r: r_s}
      T1:
        transformer:
          p1: {nodes: [p, ct]}
          p2: {nodes: [ct, \"0\"]}
          s: {nodes: [out, \"0\"]}
        component: t_model
        shields: {S: \"0\"}
      RL: {R: [out, \"0\"], r: r_l}
";
    let c = compiled("BV191@3");
    let ix = |w: &str| c.design.winding_index(w);
    let s = Setup {
        drive: vec![ix("p1"), ix("p2")],
        ground: Ground::End,
        source_ohm: 200.0,
        load: ix("s"),
        load_ohm: 1e5,
    };
    let _ = yaml::parse(circuit, "check").unwrap();
    check(circuit, "BV191@3", &s, &[30.0, 1000.0, 15e3, 40e3], 2e-4);
}

/// OT_5E3@2 (layer windings, its compiled capacitors), both halves in series from a
/// matched source into the speaker's 8 ohm.
#[test]
fn ot_5e3_agrees_with_circuitsim() {
    let circuit = "\
title: response check
input: in
probes: [out]
values:
  t_model: {value: OT_5E3@2, source: test}
  r_s: {value: 8000.0, source: test}
  r_l: {value: 8.0, source: test}
sections:
  - title: t
    parts:
      RS: {R: [in, a], r: r_s}
      T1:
        transformer:
          pa: {nodes: [a, ct]}
          pb: {nodes: [ct, \"0\"]}
          s: {nodes: [out, \"0\"]}
        component: t_model
      RL: {R: [out, \"0\"], r: r_l}
";
    let c = compiled("OT_5E3@2");
    let ix = |w: &str| c.design.winding_index(w);
    let s = Setup {
        drive: vec![ix("pa"), ix("pb")],
        ground: Ground::End,
        source_ohm: 8000.0,
        load: ix("s"),
        load_ohm: 8.0,
    };
    check(circuit, "OT_5E3@2", &s, &[30.0, 1000.0, 15e3, 40e3], 2e-4);
}
