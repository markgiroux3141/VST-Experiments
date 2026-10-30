//! The linear engine against closed-form solutions (and, for coupled
//! inductors, an independent ODE integration). ngspice agreement is tested
//! from Python (tests/test_circuitsim_linear.py).

use std::f64::consts::PI;

use circuitsim::ir::{
    Capacitor, CircuitIr, Coupling, Element, IR_VERSION, Inductor, Probe, Resistor, Section,
    SineSource, Vccs, VoltageSource,
};
use circuitsim::{Error, Method, Options, Solver, simulate, simulate_with_progress};

// --- Building test circuits ----------------------------------------------------------

fn r(name: &str, a: &str, b: &str, r_ohm: f64) -> Element {
    Element::Resistor(Resistor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        r_ohm,
    })
}

fn c(name: &str, a: &str, b: &str, c_f: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: None,
    })
}

fn l(name: &str, a: &str, b: &str, l_h: f64) -> Element {
    Element::Inductor(Inductor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        l_h,
    })
}

fn k(name: &str, l_a: &str, l_b: &str, k: f64) -> Element {
    Element::Coupling(Coupling {
        name: name.into(),
        l_a: l_a.into(),
        l_b: l_b.into(),
        k,
    })
}

fn circuit(elements: Vec<Element>, probes: &[&str]) -> CircuitIr {
    CircuitIr {
        version: IR_VERSION,
        title: "test".into(),
        input_node: "in".into(),
        controls: vec![],
        noise: None,
        heaters: None,
        probes: probes
            .iter()
            .map(|n| Probe::Voltage {
                node: n.to_string(),
            })
            .collect(),
        models: vec![],
        sections: vec![Section {
            title: "test".into(),
            elements,
        }],
    }
}

fn sine(n: usize, h: f64, f_hz: f64) -> Vec<f64> {
    (0..n)
        .map(|i| (2.0 * PI * f_hz * i as f64 * h).sin())
        .collect()
}

/// Max |simulated - exact| for probe `p` over the run.
fn max_err(
    ir: &CircuitIr,
    h: f64,
    t_end: f64,
    f_hz: f64,
    method: Method,
    exact: impl Fn(f64) -> f64,
) -> f64 {
    let n = (t_end / h).round() as usize + 1;
    let out = simulate(ir, &sine(n, h, f_hz), h, &Options::with_method(method)).unwrap();
    out.values[0]
        .iter()
        .enumerate()
        .map(|(i, y)| (y - exact(i as f64 * h)).abs())
        .fold(0.0, f64::max)
}

const H: f64 = 1.0 / 192_000.0; // 96 kHz x 2 oversampling, the production step

// --- DC operating point ----------------------------------------------------------------

#[test]
fn dc_operating_point_opens_capacitors_and_shorts_inductors() {
    let ir = circuit(
        vec![
            r("R1", "in", "a", 1e3),
            l("L1", "a", "b", 1.0),
            r("R2", "b", "0", 1e3),
            c("C1", "a", "0", 1e-6),
            Element::VoltageSource(VoltageSource {
                name: "VB".into(),
                pos: "vb".into(),
                neg: "0".into(),
                dc_v: 3.0,
            }),
            r("R3", "vb", "0", 50.0),
        ],
        &["a", "b", "vb", "in", "0"],
    );
    // Constant input: the DC point must persist through the transient.
    let out = simulate(&ir, &[10.0; 50], H, &Options::default()).unwrap();
    assert_eq!(out.names, ["v(a)", "v(b)", "v(vb)", "v(in)", "v(0)"]);
    for (vals, want) in out.values.iter().zip([5.0, 5.0, 3.0, 10.0, 0.0]) {
        for v in vals {
            assert!((v - want).abs() < 1e-12, "{v} vs {want}");
        }
    }
}

// --- First- and second-order circuits vs closed form ------------------------------------

/// RC lowpass driven by a sine source A cos(wt) (phase 90): the DC operating
/// point takes the source at t = 0, so the capacitor starts charged to A,
/// and the run is the forced response plus a decay from there. Every
/// solver path (DK, full MNA, Radau's coupled stages) evaluates the source
/// at its stage times.
#[test]
fn sine_source_starts_at_its_t0_value_and_matches_closed_form() {
    let (rr, cc, f, a) = (1e3, 1e-6, 60.0, 10.0);
    let ir = circuit(
        vec![
            Element::SineSource(SineSource {
                name: "VM".into(),
                pos: "m".into(),
                neg: "0".into(),
                offset_v: 0.0,
                amplitude_v: a,
                freq_hz: f,
                phase_deg: 90.0,
            }),
            r("R1", "m", "out", rr),
            c("C1", "out", "0", cc),
            r("RIN", "in", "0", 1e3),
        ],
        &["out", "m"],
    );
    let (w, tau) = (2.0 * PI * f, rr * cc);
    let wt = w * tau;
    let exact = |t: f64| {
        let forced = a * ((w * t).cos() + wt * (w * t).sin()) / (1.0 + wt * wt);
        forced + a * (1.0 - 1.0 / (1.0 + wt * wt)) * (-t / tau).exp()
    };
    let n = (0.05 / H).round() as usize;
    for (method, solver, tol) in [
        (Method::Esdirk4, Solver::Dk, 1e-9),
        (Method::Esdirk4, Solver::Mna, 1e-9),
        (Method::Radau5, Solver::Mna, 1e-9),
        (Method::Trapezoidal, Solver::Dk, 1e-6),
    ] {
        let opts = Options {
            method,
            solver,
            ..Options::default()
        };
        let out = simulate(&ir, &vec![0.0; n], H, &opts).unwrap();
        let src = &out.values[1];
        assert!((src[0] - a).abs() < 1e-12, "source at t = 0: {}", src[0]);
        let err = out.values[0]
            .iter()
            .enumerate()
            .map(|(i, y)| (y - exact(i as f64 * H)).abs())
            .fold(0.0, f64::max);
        assert!(err < tol * a, "{method:?} {solver:?}: max error {err}");
        let src_err = src
            .iter()
            .enumerate()
            .map(|(i, y)| (y - a * (w * i as f64 * H).cos()).abs())
            .fold(0.0, f64::max);
        assert!(
            src_err < 1e-12 * a,
            "{method:?} {solver:?}: source error {src_err}"
        );
    }
}

/// RC lowpass driven by A sin(wt) from rest: the forced response plus the
/// decaying term that makes v(0) = 0.
#[test]
fn rc_lowpass_matches_closed_form_with_second_order_convergence() {
    let (rr, cc, f) = (1e3, 1e-6, 1e3);
    let ir = circuit(
        vec![r("R1", "in", "out", rr), c("C1", "out", "0", cc)],
        &["out"],
    );
    let (w, tau) = (2.0 * PI * f, rr * cc);
    let exact = |t: f64| {
        let wt = w * tau;
        ((w * t).sin() - wt * (w * t).cos() + wt * (-t / tau).exp()) / (1.0 + wt * wt)
    };
    let e1 = max_err(&ir, H, 5e-3, f, Method::Trapezoidal, exact);
    let e2 = max_err(&ir, H / 2.0, 5e-3, f, Method::Trapezoidal, exact);
    // Trapezoidal phase error ~ (wh)^2 / 12 of the amplitude (0.16 here).
    assert!(e1 < 3e-5, "error {e1:e}");
    let ratio = e2 / e1;
    assert!(
        (0.22..0.28).contains(&ratio),
        "h/2 error ratio {ratio} (expect 1/4)"
    );
    // Backward Euler: first order.
    let b1 = max_err(&ir, H, 5e-3, f, Method::BackwardEuler, exact);
    let b2 = max_err(&ir, H / 2.0, 5e-3, f, Method::BackwardEuler, exact);
    assert!((0.45..0.55).contains(&(b2 / b1)), "Euler ratio {}", b2 / b1);
}

fn g(name: &str, pos: &str, neg: &str, cp: &str, cn: &str, gm_s: f64) -> Element {
    Element::Vccs(Vccs {
        name: name.into(),
        pos: pos.into(),
        neg: neg.into(),
        ctrl_pos: cp.into(),
        ctrl_neg: cn.into(),
        gm_s,
    })
}

/// A voltage-controlled current source (SPICE G, a speaker's readout): its control draws
/// nothing (an RC it reads keeps its closed form), gm v(ctrl) flows from pos to neg (into
/// a resistor from ground: + gm R v), and through a 1 H inductor it gives the control's
/// derivative (the readout's acceleration).
#[test]
fn vccs_reads_without_loading_and_differentiates_through_an_inductor() {
    let (rr, cc, f, gm) = (1e3, 1e-6, 1e3, 2e-3);
    let (w, tau) = (2.0 * PI * f, rr * cc);
    let rc = |t: f64| {
        let wt = w * tau;
        ((w * t).sin() - wt * (w * t).cos() + wt * (-t / tau).exp()) / (1.0 + wt * wt)
    };
    let els = || {
        vec![
            r("R1", "in", "a", rr),
            c("C1", "a", "0", cc),
            g("GR", "0", "o", "a", "0", gm),
            r("RO", "o", "0", 500.0),
            g("GD", "0", "d", "in", "0", 1e-3),
            l("LD", "d", "0", 1.0),
        ]
    };
    let t_end = 5e-3;
    let read = |p: &str| circuit(els(), &[p]);
    assert!(max_err(&read("a"), H, t_end, f, Method::Trapezoidal, rc) < 3e-5);
    // gm R = 1: the resistor's voltage is the control's.
    assert!(max_err(&read("o"), H, t_end, f, Method::Trapezoidal, rc) < 3e-5);
    // 1 H x 1e-3 S x d/dt (1 - cos w t) = 1e-3 w sin(w t) (6.3 V peak; the drive starts
    // with zero slope, as a settled run does: trapezoidal never damps an inconsistent
    // start), off by ~(w h)^2 / 12 of it.
    let n = (t_end / H).round() as usize + 1;
    let u: Vec<f64> = (0..n).map(|i| 1.0 - (w * i as f64 * H).cos()).collect();
    let out = simulate(
        &read("d"),
        &u,
        H,
        &Options::with_method(Method::Trapezoidal),
    )
    .unwrap();
    let e = out.values[0]
        .iter()
        .enumerate()
        .map(|(i, y)| (y - 1e-3 * w * (w * i as f64 * H).sin()).abs())
        .fold(0.0, f64::max);
    assert!(e < 1e-3 * 1e-3 * w, "derivative error {e:e}");
}

#[test]
fn rl_highpass_matches_closed_form() {
    let (rr, ll, f) = (100.0, 0.1, 1e3);
    let ir = circuit(
        vec![r("R1", "in", "out", rr), l("L1", "out", "0", ll)],
        &["out"],
    );
    let (w, tau) = (2.0 * PI * f, ll / rr);
    let exact = |t: f64| {
        let wt = w * tau;
        let i =
            ((w * t).sin() - wt * (w * t).cos() + wt * (-t / tau).exp()) / (rr * (1.0 + wt * wt));
        (w * t).sin() - rr * i
    };
    let e = max_err(&ir, H, 5e-3, f, Method::Trapezoidal, exact);
    assert!(e < 1e-4, "error {e:e}");
}

/// Series RLC, output across C, underdamped, driven from rest.
#[test]
fn series_rlc_matches_closed_form() {
    let (rr, ll, cc, f) = (100.0, 10e-3, 1e-6, 1e3);
    let ir = circuit(
        vec![
            r("R1", "in", "a", rr),
            l("L1", "a", "b", ll),
            c("C1", "b", "0", cc),
        ],
        &["b"],
    );
    let w = 2.0 * PI * f;
    // H(jw) = 1 / (1 - w^2 LC + j w RC)
    let (re, im) = (1.0 - w * w * ll * cc, w * rr * cc);
    let (mag, phi) = (1.0 / re.hypot(im), -im.atan2(re));
    let alpha = rr / (2.0 * ll);
    let wd = (1.0 / (ll * cc) - alpha * alpha).sqrt();
    // v(0) = 0 and v'(0) = i(0) / C = 0 fix the homogeneous part.
    let c1 = -mag * phi.sin();
    let c2 = (alpha * c1 - mag * w * phi.cos()) / wd;
    let exact = |t: f64| {
        mag * (w * t + phi).sin() + (-alpha * t).exp() * (c1 * (wd * t).cos() + c2 * (wd * t).sin())
    };
    let e1 = max_err(&ir, H, 5e-3, f, Method::Trapezoidal, exact);
    let e2 = max_err(&ir, H / 2.0, 5e-3, f, Method::Trapezoidal, exact);
    assert!(e1 < 2e-4, "error {e1:e}");
    assert!((0.22..0.28).contains(&(e2 / e1)), "ratio {}", e2 / e1);
}

// --- Coupled inductors vs an independent ODE integration --------------------------------

/// Two windings, dots at `p` and `s`: [L1 M; M L2] d/dt [i1 i2] = [u - Rs i1, -Rl i2],
/// integrated with RK4 at a much finer step than the engine's.
fn transformer_reference(
    l1: f64,
    l2: f64,
    kk: f64,
    rs: f64,
    rl: f64,
    f: f64,
    t: &[f64],
) -> (Vec<f64>, Vec<f64>) {
    let m = kk * (l1 * l2).sqrt();
    let det = l1 * l2 - m * m;
    let u = |t: f64| (2.0 * PI * f * t).sin();
    let deriv = |t: f64, i: [f64; 2]| {
        let (a, b) = (u(t) - rs * i[0], -rl * i[1]);
        [(l2 * a - m * b) / det, (l1 * b - m * a) / det]
    };
    let sub = 200;
    let (mut i, mut tt) = ([0.0, 0.0], 0.0);
    let (mut vp, mut vs) = (vec![], vec![]);
    for (n, &target) in t.iter().enumerate() {
        if n > 0 {
            let dt = (target - tt) / sub as f64;
            for _ in 0..sub {
                let add = |i: [f64; 2], d: [f64; 2], s: f64| [i[0] + s * d[0], i[1] + s * d[1]];
                let k1 = deriv(tt, i);
                let k2 = deriv(tt + dt / 2.0, add(i, k1, dt / 2.0));
                let k3 = deriv(tt + dt / 2.0, add(i, k2, dt / 2.0));
                let k4 = deriv(tt + dt, add(i, k3, dt));
                for j in 0..2 {
                    i[j] += dt / 6.0 * (k1[j] + 2.0 * k2[j] + 2.0 * k3[j] + k4[j]);
                }
                tt += dt;
            }
        }
        vp.push(u(target) - rs * i[0]);
        vs.push(-rl * i[1]);
    }
    (vp, vs)
}

#[test]
fn coupled_inductors_match_the_ode() {
    // A 1:2 transformer with k = 0.999, like the 670's (leakage 0.2% of L).
    let (l1, l2, kk, rs, rl, f) = (1.0, 4.0, 0.999, 600.0, 10e3, 1e3);
    let ir = circuit(
        vec![
            r("RS", "in", "p", rs),
            l("L1", "p", "0", l1),
            l("L2", "s", "0", l2),
            k("K12", "L1", "L2", kk),
            r("RL", "s", "0", rl),
        ],
        &["p", "s"],
    );
    // Errors vs the ODE on the secondary: (whole run, after the first 2 ms).
    let errors = |h: f64| {
        let n = (10e-3 / h) as usize;
        let out = simulate(&ir, &sine(n, h, f), h, &Options::default()).unwrap();
        let t: Vec<f64> = (0..n).map(|i| i as f64 * h).collect();
        let (vp, vs) = transformer_reference(l1, l2, kk, rs, rl, f, &t);
        let settle = (2e-3 / h) as usize;
        let mut all = 0.0f64;
        let mut late = 0.0f64;
        for (sim, reference) in [(&out.values[0], &vp), (&out.values[1], &vs)] {
            for (i, (a, b)) in sim.iter().zip(reference.iter()).enumerate() {
                all = all.max((a - b).abs());
                if i >= settle {
                    late = late.max((a - b).abs());
                }
            }
        }
        let peak = vs.iter().fold(0.0f64, |a, v| a.max(v.abs()));
        (all / peak, late / peak, out)
    };
    let (all1, late1, out) = errors(H);
    let (_, late2, _) = errors(H / 2.0);
    // Secondary ~ 2x the primary, in phase with the dots.
    let peak = out.values[1].iter().fold(0.0f64, |a, v| a.max(v.abs()));
    assert!(peak > 0.5, "secondary peak {peak}");
    // Second order once the start has passed (measured 7e-6 re peak).
    assert!(late1 < 2e-5, "late error {late1:e} re peak");
    assert!(
        (0.22..0.28).contains(&(late2 / late1)),
        "ratio {}",
        late2 / late1
    );
    // The leakage mode (L1 (1 - k^2) against Rs + Rl / 4: tau = 0.65 us) is
    // much faster than the 5.2 us step. Trapezoidal integration rings on it
    // when the sine starts, decaying by (1 - h/2tau) / (1 + h/2tau) = -0.6 per
    // step: measured 2.3e-3 re peak on the first step. A known trapezoidal
    // property (docs/CIRCUIT_SIM_PLAN.md, risks), bounded here so a change shows.
    assert!(all1 < 5e-3, "start-up error {all1:e} re peak");
    let n = out.values[1].len();
    // Reversing the secondary's dot flips its polarity.
    let mut flipped = ir.clone();
    flipped.sections[0].elements[2] = l("L2", "0", "s", l2);
    let out2 = simulate(&flipped, &sine(n, H, f), H, &Options::default()).unwrap();
    for (a, b) in out.values[1].iter().zip(&out2.values[1]) {
        assert!((a + b).abs() < 1e-9 * peak);
    }
}

/// A secondary closed by a resistor and held to ground only by 1 GOhm, as the
/// 670's T104 secondary is once the bridge diodes are removed. No current can
/// reach the leak, so `b` sits at exactly 0 V; what the engine shows there is
/// its roundoff. Unscaled pivoting gave ~4 mV in the 670. With equilibration
/// it's 5.5e-5 V here (1e-4 of the swing), the double-precision floor
/// eps x (1 / 1 mOhm) x V / (1 / 1 GOhm); ngspice shows ~2e-5 V on the same
/// node in the 670.
#[test]
fn floating_secondary_stays_at_zero() {
    let ir = circuit(
        vec![
            r("RS", "in", "p", 600.0),
            r("RW1", "p", "p_r", 1e-3),
            l("L1", "p_r", "0", 10.0),
            r("RW2", "a", "a_r", 1e-3),
            l("L2", "a_r", "b", 10.0),
            k("K12", "L1", "L2", 0.999),
            r("R136", "a", "b", 3900.0),
            r("RLEAK", "b", "0", 1e9),
            Element::VoltageSource(VoltageSource {
                name: "VBP".into(),
                pos: "bp".into(),
                neg: "0".into(),
                dc_v: 240.0,
            }),
            r("RBP", "bp", "p", 1e3),
        ],
        &["a", "b"],
    );
    let n = (10e-3 / H) as usize;
    let out = simulate(&ir, &sine(n, H, 1e3), H, &Options::default()).unwrap();
    let swing = out.values[0].iter().fold(0.0f64, |m, v| m.max(v.abs()));
    let worst = out.values[1].iter().fold(0.0f64, |m, v| m.max(v.abs()));
    assert!(swing > 0.1, "secondary swing {swing}");
    assert_eq!(out.values[1][0], 0.0, "DC point");
    assert!(
        worst < 3e-4 * swing,
        "b wanders {worst:e} V (swing {swing:.3} V)"
    );
}

// --- Errors ----------------------------------------------------------------------------

#[test]
fn errors_name_the_problem() {
    // A node that only connects through a capacitor has no DC solution.
    let floating = circuit(
        vec![r("R1", "in", "0", 1e3), c("C1", "in", "x", 1e-6)],
        &["x"],
    );
    let e = simulate(&floating, &[0.0; 4], H, &Options::default()).unwrap_err();
    assert!(e.to_string().contains("node x"), "{e}");

    let rc = circuit(vec![r("R1", "in", "0", 1e3)], &["in"]);
    let e = simulate(&rc, &[0.0, f64::NAN], H, &Options::default()).unwrap_err();
    assert!(e.to_string().contains("sample 1"), "{e}");
    assert!(simulate(&rc, &[0.0], 0.0, &Options::default()).is_err());
    assert_eq!(
        simulate(&rc, &[], H, &Options::default()).unwrap().values,
        [Vec::<f64>::new()]
    );
}

/// Progress is reported every `every` samples, doesn't change the result, and
/// an error from the callback stops the run.
#[test]
fn progress_is_reported_and_can_stop_a_run() {
    let ir = circuit(
        vec![r("R1", "in", "out", 1e3), c("C1", "out", "0", 1e-6)],
        &["out"],
    );
    let x = sine(10, H, 1e3);
    let opts = Options::default();
    let mut seen = vec![];
    let out = simulate_with_progress(&ir, &x, H, &opts, 3, |done| {
        seen.push(done);
        Ok(())
    })
    .unwrap();
    assert_eq!(seen, [3, 6, 9]);
    assert_eq!(out, simulate(&ir, &x, H, &opts).unwrap());
    let e = simulate_with_progress(&ir, &x, H, &opts, 4, |done| {
        if done >= 8 {
            Err(Error::new("stop"))
        } else {
            Ok(())
        }
    })
    .unwrap_err();
    assert_eq!(e.to_string(), "stop");
}

// --- Start voltages ---------------------------------------------------------------------

fn c_start(name: &str, a: &str, b: &str, c_f: f64, v0: f64) -> Element {
    Element::Capacitor(Capacitor {
        name: name.into(),
        a: a.into(),
        b: b.into(),
        c_f,
        v0_v: Some(v0),
    })
}

/// A capacitor with a start voltage begins the run holding it (the DC operating point is
/// solved with it held) and then discharges as an ordinary capacitor: grounded, and
/// floating between two resistors (v(a) - v(b) = v0 at the start, split by symmetry).
/// The first step takes the start's derivative as zero, as at a DC point, so the decay
/// runs about half a step late: within 0.5% here, not the 1e-3 of a DC start.
#[test]
fn a_start_voltage_holds_for_the_operating_point_then_discharges() {
    let tau = 1e-3;
    let n = 400;
    for floating in [false, true] {
        let (ir, probe, v_start, tau_run) = if floating {
            let ir = circuit(
                vec![
                    r("R1", "in", "a", 500.0),
                    c_start("C1", "a", "b", 1e-6, 2.0),
                    r("R2", "b", "0", 500.0),
                ],
                &["a", "b"],
            );
            (ir, 0usize, 1.0, tau)
        } else {
            let ir = circuit(
                vec![r("R1", "in", "a", 1e3), c_start("C1", "a", "0", 1e-6, 5.0)],
                &["a"],
            );
            (ir, 0usize, 5.0, tau)
        };
        let out = simulate(&ir, &vec![0.0; n], H, &Options::default()).unwrap();
        let v = &out.values[probe];
        let worst = v
            .iter()
            .enumerate()
            .map(|(i, x)| (x - v_start * (-(i as f64) * H / tau_run).exp()).abs())
            .fold(0.0, f64::max);
        assert!(
            (v[0] - v_start).abs() < 1e-5,
            "floating {floating}: start {}",
            v[0]
        );
        assert!(worst < 5e-3 * v_start, "floating {floating}: worst {worst}");
        if floating {
            let vb = &out.values[1];
            assert!((v[0] - vb[0] - 2.0).abs() < 1e-5, "{} {}", v[0], vb[0]);
        }
    }
}
