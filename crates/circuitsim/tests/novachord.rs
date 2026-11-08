//! The Novachord's keys as a medium (docs/NOVACHORD_PLAN.md, NV4) on the saved component's
//! data, alone: the oscillators' vibrato grids at rest, the attack switch's
//! buses at a position's table values (SM2 p.16), the cut-off taps and plate leads at their
//! rest. The envelopes behave as the manual describes them (the reference's own numbers are
//! scripts/novachord_live_check.py's), keys sleep once released, a pedal holds them.

use std::path::Path;

use circuitsim::ir::NovaKeys;
use circuitsim::media::NoteEvent;
use circuitsim::novachord::Medium;

const FS: f64 = 96_000.0;

/// The saved keys' element (None when the component isn't there).
fn keys() -> Option<NovaKeys> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/components/novachord_keys");
    let yaml = std::fs::read_to_string(dir.join("1.yaml")).ok()?;
    let sha = yaml
        .lines()
        .skip_while(|l| !l.starts_with("data:"))
        .find_map(|l| l.trim().strip_prefix("sha256: "))?
        .to_string();
    Some(NovaKeys {
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
    })
}

/// SM2 p.16's buses A and C per ATTACK position.
fn buses(attack: usize) -> (f64, f64) {
    [
        (-268.0, 9.0),
        (-235.0, -24.0),
        (-180.0, -40.0),
        (-125.0, -125.0),
        (-40.0, -180.0),
        (-24.0, -235.0),
        (9.0, -268.0),
    ][attack - 1]
}

/// Run `n` samples with `events` (sample, event): each plate lead's output and the keys
/// awake, per sample.
fn run(attack: usize, n: usize, events: &[(usize, NoteEvent)]) -> (Vec<[f64; 18]>, Vec<usize>) {
    let el = keys().expect("the component");
    let mut m = Medium::new(&el, FS).expect("the medium");
    for &(at, ev) in events {
        m.queue(at, ev);
    }
    let (a, c) = buses(attack);
    // the cut-off divider's taps (Fig. 19: 2800 / 100 x 6 / 600 off +34 V)
    let i = 34.0 / 4000.0;
    let cuts = [i * 800.0, i * 900.0, i * 1000.0];
    let keyp = i * 1100.0;
    let mut s = vec![0.0; 18 + 18];
    let (mut outs, mut awake) = (Vec::new(), Vec::new());
    for _ in 0..n {
        s[..12].fill(-12.0); // the vibrato grids at rest
        s[12] = a;
        s[13] = c;
        s[14] = keyp;
        s[15..18].copy_from_slice(&cuts);
        s[18..].iter_mut().for_each(|p| *p = 255.0);
        m.push(&s);
        let mut o = [0.0; 18];
        for (g, x) in o.iter_mut().enumerate() {
            *x = m.output(g);
        }
        outs.push(o);
        awake.push(m.sounding());
    }
    (outs, awake)
}

/// A lead's mean plate current (mA) over samples a..b.
fn mean_ma(outs: &[[f64; 18]], g: usize, a: usize, b: usize) -> f64 {
    outs[a..b].iter().map(|o| o[g]).sum::<f64>() / (b - a) as f64
}

const A4: u8 = 69; // key 41, plate lead 10

#[test]
fn keys_rest_asleep_and_silent() {
    if keys().is_none() {
        return;
    }
    let (outs, awake) = run(4, 9600, &[]);
    assert!(awake.iter().all(|&a| a == 0));
    assert!(outs.iter().flatten().all(|&x| x == 0.0));
}

#[test]
fn organ_attack_holds_and_releases_to_sleep() {
    if keys().is_none() {
        return;
    }
    // asleep ~1 s after the release: the cathode relaxes through RN7 x CN15 (~0.14 s)
    let n = (2.5 * FS) as usize;
    let on = (0.05 * FS) as usize;
    let off = (0.65 * FS) as usize;
    let ev = [
        (
            on,
            NoteEvent::On {
                note: A4,
                velocity: 100,
            },
        ),
        (off, NoteEvent::Off { note: A4 }),
    ];
    let (outs, awake) = run(4, n, &ev);
    let early = mean_ma(&outs, 10, on + 4800, on + 9600);
    let held = mean_ma(&outs, 10, off - 9600, off);
    assert!(held > 1e-3, "a held key draws plate current: {held} mA");
    // ATTACK 4 (organ-like): it comes up within ~0.1 s and holds
    assert!(early > 0.5 * held, "{early} vs {held}");
    // only its own lead
    assert!(mean_ma(&outs, 9, off - 9600, off).abs() < 1e-9);
    // released: silent within ~0.3 s, then asleep
    let quiet = off + (0.3 * FS) as usize;
    assert!(mean_ma(&outs, 10, quiet, quiet + 4800).abs() < 1e-3 * held);
    assert_eq!(*awake.last().unwrap(), 0);
}

#[test]
fn percussive_attack_dies_away_while_held() {
    if keys().is_none() {
        return;
    }
    let n = (1.0 * FS) as usize;
    let on = (0.05 * FS) as usize;
    let ev = [(
        on,
        NoteEvent::On {
            note: A4,
            velocity: 100,
        },
    )];
    let (outs, awake) = run(1, n, &ev);
    let peak = (on..on + 9600).map(|k| outs[k][10]).fold(0.0, f64::max);
    let late = mean_ma(&outs, 10, n - 4800, n);
    assert!(peak > 1e-3, "it strikes: {peak} mA");
    assert!(late < 0.1 * peak, "and dies away held: {late} of {peak} mA");
    assert_eq!(*awake.last().unwrap(), 1, "a key held stays awake");
}

#[test]
fn string_attack_swells() {
    if keys().is_none() {
        return;
    }
    let n = (1.5 * FS) as usize;
    let on = (0.05 * FS) as usize;
    let ev = [(
        on,
        NoteEvent::On {
            note: A4,
            velocity: 100,
        },
    )];
    let (outs, _) = run(7, n, &ev);
    let at = |s: f64| {
        mean_ma(
            &outs,
            10,
            on + (s * FS) as usize,
            on + ((s + 0.05) * FS) as usize,
        )
    };
    // ATTACK 7 (strings): still rising after half a second
    assert!(
        at(0.1) < at(0.5) && at(0.5) < at(1.2),
        "{} {} {}",
        at(0.1),
        at(0.5),
        at(1.2)
    );
}

#[test]
fn the_pedal_holds_a_released_key() {
    if keys().is_none() {
        return;
    }
    let n = (1.0 * FS) as usize;
    let on = (0.05 * FS) as usize;
    let off = (0.4 * FS) as usize;
    let ev = [
        (0, NoteEvent::Pedal { down: true }),
        (
            on,
            NoteEvent::On {
                note: A4,
                velocity: 100,
            },
        ),
        (off, NoteEvent::Off { note: A4 }),
    ];
    let (outs, awake) = run(4, n, &ev);
    let held = mean_ma(&outs, 10, off - 4800, off);
    let after = mean_ma(&outs, 10, n - 4800, n);
    assert!(
        after > 0.3 * held,
        "the pedal sustains: {after} of {held} mA"
    );
    assert_eq!(*awake.last().unwrap(), 1);
}
