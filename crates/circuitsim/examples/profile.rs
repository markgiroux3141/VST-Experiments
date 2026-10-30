//! Where a transient step's time goes, on a circuit IR (JSON file).
//!
//!     cargo run --release --example profile -- circuit.json [method] [oversample] [solver] [reltol] [vntol]

use std::time::Instant;

use circuitsim::dk::{self, DkNewton, DkSystem, Ports};
use circuitsim::ir::CircuitIr;
use circuitsim::linalg::{ColLu, Lu};
use circuitsim::mna::Mna;
use circuitsim::newton::{NewtonOptions, Reduced};
use circuitsim::transient::{Method, Options, Solver, Transient};

/// Microseconds per call: the best of 7 batches (the desktop is noisy).
fn time<F: FnMut()>(reps: usize, mut f: F) -> f64 {
    let batch = (reps / 7).max(1);
    (0..7)
        .map(|_| {
            let t = Instant::now();
            for _ in 0..batch {
                f();
            }
            t.elapsed().as_secs_f64() / batch as f64 * 1e6
        })
        .fold(f64::INFINITY, f64::min)
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let ir = CircuitIr::from_json(&std::fs::read_to_string(&args[1]).unwrap()).unwrap();
    let method = Method::parse(args.get(2).map_or("trap", |s| s.as_str())).unwrap();
    let k: usize = args.get(3).map_or(2, |s| s.parse().unwrap());
    let solver = Solver::parse(args.get(4).map_or("dk", |s| s.as_str())).unwrap();
    let h = 1.0 / (96_000.0 * k as f64);
    let fs = 13.8; // 0 dBFS in volts

    // Whole steps: 0.25 s of a 1 kHz tone at -6 dBFS, or with CCIF=1 a
    // 19 + 20 kHz twin tone at -10 dBFS.
    let mna = Mna::from_ir(&ir, 1e-12).unwrap();
    let d = Options::default();
    let opts = Options {
        solver,
        reltol: args.get(5).map_or(d.reltol, |s| s.parse().unwrap()),
        newton_reuse: std::env::var("NO_REUSE").is_err(),
        // ERR=1: production's local error control.
        error_abstol: if std::env::var("ERR").is_ok() {
            0.01
        } else {
            0.0
        },
        error_reltol: 1e-3,
        vntol: args.get(6).map_or(d.vntol, |s| s.parse().unwrap()),
        ..Options::with_method(method)
    };
    let mut tr = Transient::new(mna, h, opts, 0.0).unwrap();
    let n = (0.25 / h) as usize;
    circuitsim::timing::take();
    let c0 = circuitsim::timing::now();
    let t = Instant::now();
    for i in 1..=n {
        let t = i as f64 * h;
        let tau = 2.0 * std::f64::consts::PI;
        let u = if std::env::var("CCIF").is_ok() {
            0.5 * 0.316 * fs * ((tau * 19e3 * t).sin() + (tau * 20e3 * t).sin())
        } else {
            0.5 * fs * (tau * 1000.0 * t).sin()
        };
        tr.step(u).unwrap();
    }
    let per_step = t.elapsed().as_secs_f64() / n as f64 * 1e6;
    let cycles = circuitsim::timing::now().wrapping_sub(c0);
    let parts = circuitsim::timing::take();
    if cycles > 0 {
        // Cycles to microseconds per step by the run's own clock.
        let us = per_step / (cycles as f64 / n as f64);
        let mut timed = 0.0;
        for ((_, name), c) in circuitsim::timing::PARTS.iter().zip(parts) {
            let t = c as f64 / n as f64 * us;
            timed += t;
            println!("  {name:24} {t:6.2} us/step");
        }
        println!("  {:24} {:6.2} us/step", "other", per_step - timed);
    }
    let st = tr.stats();
    println!(
        "{method:?} {solver:?} k={k}: {per_step:.2} us/step, {:.2} x realtime, \
         {:.2} iterations/step (Newton on {}, {} states)",
        per_step * 1e-6 * 96_000.0 * k as f64,
        st.iterations as f64 / st.steps as f64,
        st.nonlinear_unknowns,
        st.states,
    );
    println!(
        "  per step: {:.2} device evaluations (of {} devices), {:.3} factorizations, {:.3} substeps",
        st.device_evaluations as f64 / st.steps as f64,
        tr.mna().devices.len(),
        st.factorizations as f64 / st.steps as f64,
        st.substeps as f64 / st.steps as f64,
    );

    if let Some(ev) = tr.device_evaluations() {
        let per: Vec<String> = tr
            .mna()
            .devices
            .iter()
            .zip(ev)
            .map(|(d, e)| format!("{} {:.2}", d.name, *e as f64 / st.steps as f64))
            .collect();
        println!("  evaluations per step: {}", per.join(", "));
    }
    // Pieces.
    let mna = Mna::from_ir(&ir, 1e-12).unwrap();
    let x = tr.x().to_vec();
    let mut dn = Vec::new();
    for d in &mna.devices {
        for &p in d.pins.iter().flatten() {
            if !dn.contains(&p) {
                dn.push(p);
            }
        }
    }
    let a = mna.g.plus_scaled(2.0 / h, &mna.c);
    let red = Reduced::new(&a, &dn);
    let (nn, nl) = (red.n_len(), red.l_len());
    println!("n = {}, N = {nn}, L = {nl}", mna.len());
    let reps = 20000;
    let mut v = [0.0; 4];
    let mut i = [0.0; 4];
    let mut g = [0.0; 16];
    let mut total = 0.0;
    for d in &mna.devices {
        let np = d.device.ports();
        let r = d.pins.last().unwrap().map_or(0.0, |p| x[p]);
        for (v, pin) in v.iter_mut().zip(&d.pins) {
            *v = pin.map_or(0.0, |p| x[p]) - r;
        }
        let us = time(reps, || {
            d.device.eval(&v[..np], &mut i[..np], &mut g[..np * np])
        });
        total += us;
        println!("  eval {:8} {us:.3} us", d.name);
    }
    println!("all devices: {total:.2} us");
    let mut lu = Lu::with_size(nn);
    println!(
        "LU refactor N: {:.2} us",
        time(reps, || lu.refactor(&red.s).unwrap())
    );
    let mut rhs = vec![1.0; nn];
    let mut work = vec![0.0; nn];
    println!(
        "LU solve N: {:.2} us",
        time(reps, || lu.solve(&mut rhs, &mut work))
    );
    let r = vec![1.0; mna.len()];
    let (mut y, mut rn, mut wl) = (vec![0.0; nl], vec![0.0; nn], vec![0.0; nl]);
    println!(
        "reduce: {:.2} us",
        time(reps, || red.reduce(&r, &mut y, &mut rn, &mut wl))
    );
    let mut xf = vec![0.0; mna.len()];
    println!(
        "expand: {:.2} us",
        time(reps, || red.expand(&y, &rn, &mut xf))
    );
    let mut cx = vec![0.0; mna.len()];
    println!(
        "C x (dense): {:.2} us",
        time(reps, || mna.c.mul_vec(&x, &mut cx))
    );

    // The DK solver's pieces (esdirk4's diagonal: 1 / (g h) = 4 / h).
    let ports = Ports::new(&mna.devices);
    let sup = dk::support(&mna.c);
    let inv = 4.0 / h;
    let t = Instant::now();
    let sys = DkSystem::new(
        &mna.g,
        &mna.c,
        inv,
        &mna.b,
        mna.input_row,
        &mna.source_rows(),
        &[],
        &ports,
        &sup,
        &[],
    )
    .unwrap();
    println!(
        "DK: M = {}, r = {}; system built in {:.2} ms",
        sys.m,
        sys.r,
        t.elapsed().as_secs_f64() * 1e3
    );
    let (m, r) = (sys.m, sys.r);
    let xs: Vec<f64> = sup.iter().map(|&s| x[s]).collect();
    let mut base = vec![0.0; sys.rows_for(true)];
    println!(
        "  step base: {:.2} us",
        time(reps, || sys.step_base(&xs, &mut base))
    );
    let w = vec![1e-3; r];
    let mut out = vec![0.0; m + r];
    println!(
        "  stage: {:.2} us",
        time(reps, || sys.stage(&base, 0.1, &[], &w, &mut out))
    );
    let iv = vec![1e-3; m];
    let mut neg = vec![0.0; m.max(r)];
    let mut ys = out[m..].to_vec();
    println!(
        "  states: {:.2} us",
        time(reps, || sys.states(&mut ys, &iv, &mut neg))
    );
    let mut xn = vec![0.0; mna.len()];
    println!(
        "  unknowns: {:.2} us",
        time(reps, || sys.unknowns(
            &base,
            0.1,
            &[],
            &w,
            &iv,
            &mut xn,
            &mut neg
        ))
    );
    let mut newton = DkNewton::new(&ports, false);
    let mut v0 = vec![0.0; m];
    ports.voltages(&x, &mut v0);
    newton.v_lin.copy_from_slice(&v0);
    let one = NewtonOptions {
        reltol: 1e-6,
        vntol: 1e-6,
        max_iter: 1,
        gshunt: 0.0,
    };
    let p = out[..m].to_vec();
    let mut v = v0.clone();
    println!(
        "  one Newton iteration: {:.2} us (devices {total:.2})",
        time(reps, || {
            v.copy_from_slice(&v0);
            let _ = newton.solve(&sys, &mna.devices, &ports, &p, &mut v, &one);
        })
    );
    let mut k = sys.k_matrix();
    for j in 0..m {
        k[j * m + j] += 1.0;
    }
    let mut clu = ColLu::with_size(m);
    println!(
        "  M x M LU: {:.2} us",
        time(reps, || clu.factor(&k).unwrap())
    );
}
