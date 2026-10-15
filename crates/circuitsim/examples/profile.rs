//! Where a transient step's time goes, on a circuit IR (JSON file).
//!
//!     cargo run --release --example profile -- circuit.json [method] [oversample]

use std::time::Instant;

use circuitsim::ir::CircuitIr;
use circuitsim::linalg::Lu;
use circuitsim::mna::Mna;
use circuitsim::newton::Reduced;
use circuitsim::transient::{Method, Options, Transient};

fn time<F: FnMut()>(reps: usize, mut f: F) -> f64 {
    let t = Instant::now();
    for _ in 0..reps {
        f();
    }
    t.elapsed().as_secs_f64() / reps as f64 * 1e6
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let ir = CircuitIr::from_json(&std::fs::read_to_string(&args[1]).unwrap()).unwrap();
    let method = Method::parse(args.get(2).map_or("trap", |s| s.as_str())).unwrap();
    let k: usize = args.get(3).map_or(2, |s| s.parse().unwrap());
    let h = 1.0 / (96_000.0 * k as f64);
    let fs = 13.8; // 0 dBFS in volts

    // Whole steps: 0.25 s of a 1 kHz tone at -6 dBFS.
    let mna = Mna::from_ir(&ir, 1e-12).unwrap();
    let mut tr = Transient::new(mna, h, Options::with_method(method), 0.0).unwrap();
    let n = (0.25 / h) as usize;
    let t = Instant::now();
    for i in 1..=n {
        let u = 0.5 * fs * (2.0 * std::f64::consts::PI * 1000.0 * i as f64 * h).sin();
        tr.step(u).unwrap();
    }
    let per_step = t.elapsed().as_secs_f64() / n as f64 * 1e6;
    let st = tr.stats();
    println!(
        "{method:?} k={k}: {per_step:.2} us/step, {:.2} x realtime, {:.2} iterations/step",
        per_step * 1e-6 * 96_000.0 * k as f64,
        st.iterations as f64 / st.steps as f64
    );

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
}
