//! The Novachord's keys medium alone (docs/NOVACHORD_PLAN.md, NV4): microseconds per sample
//! with N keys held (synthetic senses: the vibrato grids at rest, ATTACK 4's buses).
//!
//!     cargo run --release -p circuitsim --example nova_bench -- [KEYS_HELD] [SECONDS]

use std::time::Instant;

use circuitsim::ir::NovaKeys;
use circuitsim::media::NoteEvent;
use circuitsim::novachord::{Medium, load};

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let held: usize = args.get(1).and_then(|s| s.parse().ok()).unwrap_or(0);
    let seconds: f64 = args.get(2).and_then(|s| s.parse().ok()).unwrap_or(2.0);
    let fs = 96_000.0;
    let dir = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../config/components/novachord_keys");
    let yaml = std::fs::read_to_string(dir.join("1.yaml")).expect("the component");
    let sha = yaml
        .lines()
        .skip_while(|l| !l.starts_with("data:"))
        .find_map(|l| l.trim().strip_prefix("sha256: "))
        .expect("a sha")
        .to_string();
    let el = NovaKeys {
        name: "VKEYS".into(),
        data: "config/components/novachord_keys/1.keys.json".into(),
        sha256: sha,
        keys: vec![1.0, 72.0],
        mellow: 0.0,
        v_per_a: 1000.0,
        normal_vibrato: 0.0,
        small_vibrato: 0.0,
        grids: (0..12).map(|i| format!("g{i}")).collect(),
        abus: "abus".into(),
        cbus: "cbus".into(),
        keyp: "keyp".into(),
        cuts: vec!["cy".into(), "co".into(), "cr".into()],
        plates: (0..18).map(|g| format!("grp{g}")).collect(),
        outs: (0..18).map(|g| format!("nk{g}")).collect(),
    };
    let model = load(&el).expect("the model");
    {
        use circuitsim::devices::Device;
        let tube = circuitsim::devices::Pentode::new(&model.tube);
        let fast = circuitsim::novachord::ControlTube::new(&model.tube);
        let (mut i, mut g) = ([0.0; 3], [0.0; 9]);
        let t0 = Instant::now();
        let mut acc = 0.0;
        for k in 0..2_000_000 {
            let x = (k % 1000) as f64 * 0.003;
            tube.eval(&[250.0 + x, 100.0 + x, -2.0 + x], &mut i, &mut g);
            acc += i[0] + g[8];
        }
        println!(
            "pentode eval: {:.1} ns [{acc:.3e}]",
            t0.elapsed().as_secs_f64() / 2e6 * 1e9
        );
        let t0 = Instant::now();
        for k in 0..2_000_000 {
            let x = (k % 1000) as f64 * 0.003;
            fast.eval(&[250.0 + x, 100.0 + x, -2.0 + x], &mut i, &mut g);
            acc += i[0] + g[8];
        }
        println!(
            "tabulated: {:.1} ns [{acc:.3e}]",
            t0.elapsed().as_secs_f64() / 2e6 * 1e9
        );
    }
    let mut m = Medium::new(&el, fs).expect("the medium");
    for i in 0..held {
        m.queue(
            100,
            NoteEvent::On {
                note: 45 + i as u8,
                velocity: 100,
            },
        );
    }
    let n = (seconds * fs) as usize;
    let mut s = vec![0.0; 36];
    let i = 34.0 / 4000.0;
    let t0 = Instant::now();
    let mut acc = 0.0;
    for _ in 0..n {
        s[..12].fill(-12.0); // the vibrato grids at rest
        s[12] = -125.0;
        s[13] = -125.0;
        s[14] = i * 1100.0;
        s[15] = i * 800.0;
        s[16] = i * 900.0;
        s[17] = i * 1000.0;
        s[18..].iter_mut().for_each(|p| *p = 255.0);
        acc += m.push(&s);
    }
    let el_s = t0.elapsed().as_secs_f64();
    println!(
        "{held} keys held: {:.2} us a sample ({:.2}x real time at 96 kHz; senses included), {} awake, {:.2} evaluations a key-sample [{acc:.3e}]",
        el_s / n as f64 * 1e6,
        el_s / seconds,
        m.sounding(),
        m.evaluations() as f64 / (n as f64 * m.sounding().max(1) as f64)
    );
}
