//! Block-by-block runs (`stream.rs`): the same output as a whole run, and
//! parameter changes while running.

use std::fs;
use std::path::Path;
use std::time::Instant;

use circuitsim::ir::CircuitIr;
use circuitsim::partition::{Coupling, simulate_partitioned};
use circuitsim::stream::Stream;
use circuitsim::transient::{Method, Options};

fn fixture(name: &str) -> CircuitIr {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("tests")
        .join("fixtures")
        .join(name);
    CircuitIr::from_json(&fs::read_to_string(path).expect(name)).unwrap()
}

const SUPPLIES: [&str; 3] = ["power supply", "bias supply", "channel 2 (idle, lumped)"];

fn supplies() -> Vec<String> {
    SUPPLIES.iter().map(|s| s.to_string()).collect()
}

/// The draft's settings (sim_settings circuitsim_draft) at a 48 kHz step.
fn draft(order: usize) -> Options {
    Options {
        input_order: order,
        reltol: 1e-3,
        vntol: 1e-2,
        tube_tables: true,
        all_unknowns: false,
        ..Options::with_method(Method::TrBdf2)
    }
}

const H: f64 = 1.0 / 48_000.0;

/// 1 kHz at 0 dBFS (13.8 V), faded in over 1 ms.
fn tone(n: usize) -> Vec<f64> {
    (0..n)
        .map(|i| {
            let t = i as f64 * H;
            13.8 * (t / 1e-3).min(1.0) * (2.0 * std::f64::consts::PI * 1e3 * t).sin()
        })
        .collect()
}

/// A stream's whole output, fed `input` in blocks of the sizes `blocks` (cycled).
fn streamed(mut s: Stream, input: &[f64], blocks: &[usize]) -> Vec<Vec<f64>> {
    let mut out: Vec<Vec<f64>> = s.initial().into_iter().map(|v| vec![v]).collect();
    let (mut i, mut j) = (1, 0);
    while i < input.len() {
        let b = blocks[j % blocks.len()].min(input.len() - i);
        for (o, v) in out.iter_mut().zip(s.process(&input[i..i + b]).unwrap()) {
            o.extend(v);
        }
        i += b;
        j += 1;
    }
    for (o, v) in out.iter_mut().zip(s.finish().unwrap()) {
        o.extend(v);
    }
    out
}

fn identical(a: &[Vec<f64>], b: &[Vec<f64>]) -> bool {
    a.len() == b.len()
        && a.iter().zip(b).all(|(x, y)| {
            x.len() == y.len() && x.iter().zip(y).all(|(p, q)| p.to_bits() == q.to_bits())
        })
}

/// Fed in blocks of any size (one sample, a few, odd lengths), a stream gives
/// the whole run's output bit for bit: one solve against `simulate`, partitioned
/// against `simulate_partitioned`; linear and 5th-order input interpolation.
#[test]
fn a_stream_is_the_whole_run_in_blocks() {
    let ir = fixture("default.json");
    let x = tone(600);
    for order in [1, 5] {
        let opts = draft(order);
        let whole = circuitsim::simulate(&ir, &x, H, &opts).unwrap();
        for blocks in [&[1usize][..], &[7, 1, 64], &[599]] {
            let s = Stream::new(&ir, &[], Coupling::Extrapolate, H, &opts, x[0]).unwrap();
            assert_eq!(s.names(), whole.names.as_slice());
            assert!(
                identical(&streamed(s, &x, blocks), &whole.values),
                "order {order}, blocks {blocks:?}"
            );
        }
        let part = simulate_partitioned(
            &ir,
            &supplies(),
            Coupling::Extrapolate,
            &x,
            H,
            &opts,
            usize::MAX,
            |_| Ok(()),
        )
        .unwrap();
        for blocks in [&[1usize][..], &[13, 2]] {
            let s = Stream::new(&ir, &supplies(), Coupling::Extrapolate, H, &opts, x[0]).unwrap();
            assert!(
                identical(&streamed(s, &x, blocks), &part.values),
                "partitioned, order {order}, blocks {blocks:?}"
            );
        }
    }
}

/// The output lags the input by the interpolation's lookahead (3 samples at
/// order 5), and the stream refuses input after `finish`.
#[test]
fn a_stream_lags_by_its_lookahead() {
    let ir = fixture("default.json");
    let x = tone(20);
    let mut s = Stream::new(&ir, &[], Coupling::Extrapolate, H, &draft(5), x[0]).unwrap();
    assert_eq!(s.process(&x[1..11]).unwrap()[0].len(), 11 - 3);
    assert_eq!(s.steps(), 8);
    assert_eq!(s.finish().unwrap()[0].len(), 2);
    assert!(s.process(&x[11..]).is_err());
}

/// The time constant switched from position 2 to 3 while running (same nodes):
/// the stream carries on, in one solve and partitioned, and the control voltage
/// leaves the run that wasn't switched. A change that adds nodes (position 5)
/// is refused when it's applied. Prints what an update costs.
#[test]
fn a_stream_takes_parameter_changes() {
    let (ir, tc3, tc5) = (
        fixture("default.json"),
        fixture("tc3.json"),
        fixture("tc5.json"),
    );
    let x = tone(4800);
    let opts = draft(5);
    for second in [Vec::new(), supplies()] {
        let cv = |s: &Stream| s.names().iter().position(|n| n == "v(cv)").unwrap();
        let mut plain = Stream::new(&ir, &second, Coupling::Extrapolate, H, &opts, x[0]).unwrap();
        let mut switched =
            Stream::new(&ir, &second, Coupling::Extrapolate, H, &opts, x[0]).unwrap();
        let j = cv(&plain);
        plain.process(&x[1..2400]).unwrap();
        switched.process(&x[1..2400]).unwrap();
        switched.update(&tc3).unwrap();
        let t = Instant::now();
        let a = switched.process(&x[2400..2410]).unwrap();
        let dt = t.elapsed();
        let p = plain.process(&x[2400..2410]).unwrap();
        println!(
            "update ({} partition): 10 samples with it in {:.2} ms",
            if second.is_empty() { "no" } else { "with" },
            dt.as_secs_f64() * 1e3
        );
        let rest_a = switched.process(&x[2410..]).unwrap();
        let rest_p = plain.process(&x[2410..]).unwrap();
        assert_eq!(a[j].len(), 10);
        let d = (rest_a[j].last().unwrap() - rest_p[j].last().unwrap()).abs();
        assert!(d > 1e-3, "the switch changed nothing ({d} V)");
        let _ = p;
        // Position 5 adds nodes: refused at the step that would apply it.
        switched.update(&tc5).unwrap_or(());
        let e = switched.process(&x[1..20]).unwrap_err().to_string();
        assert!(e.contains("changed"), "{e}");
    }
}

/// The AC threshold's tapped pot (R115A/B: 100k, tap at half) turned from 0.709
/// to 0.3, past its tap: its three segments rewire among the same nodes, so MNA
/// numbers them in another order. The update carries the state over by name,
/// partitioned or not, and the run goes on (and back again).
#[test]
fn a_stream_takes_a_pot_across_its_tap() {
    let ir = fixture("default.json");
    // As varimu.circuit.parts.tapped_pot builds it at 0.3: 0 - wiper - tap - top.
    let mut v: serde_json::Value = serde_json::to_value(&ir).unwrap();
    for sec in v["sections"].as_array_mut().unwrap() {
        for e in sec["elements"].as_array_mut().unwrap() {
            let name = e["name"].as_str().unwrap().to_string();
            let Some(rest) = name.strip_prefix("R115") else {
                continue;
            };
            let side = &rest[..1].to_lowercase();
            let (tap, wiper, top) = (
                format!("x1{side}"),
                format!("w1{side}"),
                if side == "a" { "t5" } else { "t8" },
            );
            let (a, b, r) = match &rest[1..] {
                "a" => ("0".to_string(), wiper.clone(), 30e3),
                "b" => (wiper.clone(), tap.clone(), 20e3),
                _ => (tap.clone(), top.to_string(), 50e3),
            };
            e["a"] = a.into();
            e["b"] = b.into();
            e["r_ohm"] = r.into();
        }
    }
    let low = CircuitIr::from_json(&v.to_string()).unwrap();
    let x = tone(2400);
    let opts = draft(5);
    for second in [Vec::new(), supplies()] {
        let mut s = Stream::new(&ir, &second, Coupling::Extrapolate, H, &opts, x[0]).unwrap();
        s.process(&x[1..800]).unwrap();
        s.update(&low).unwrap();
        let out = s.process(&x[800..1600]).unwrap();
        assert!(out.iter().flatten().all(|v| v.is_finite()));
        s.update(&ir).unwrap();
        s.process(&x[1600..]).unwrap();
        s.finish().unwrap();
    }
}
