//! The Components view's logic end to end (docs/COMPONENT_EDITOR_PLAN.md C2 step 7's
//! done-when, as the view does it): the 5E3's output transformer opened from its saved
//! version, a second winding plan made (the secondary moved between the primary halves),
//! compiled, heard against the first in the 5E3 at draft-1x (both rendered, loudness
//! matched), saved as the next version and the circuit moved to it. On a scratch copy of
//! config/: the repo's store is never written.

use std::path::{Path, PathBuf};
use std::sync::atomic::AtomicBool;
use std::time::Duration;

use varimu_app::components::{Bench, Side, retarget, saved_as, transformer_components, uses};
use varimu_app::live::Circuit;
use varimu_app::render::render;
use varimu_app::settings::{Quality, Settings};
use varimu_circuit::versions::{self, Ref};
use varimu_circuit::yaml::Value;
use varimu_components::edit::{self, SectionKind};
use varimu_components::path;

fn repo_config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn copy_dir(from: &Path, to: &Path) {
    std::fs::create_dir_all(to).unwrap();
    for e in std::fs::read_dir(from).unwrap() {
        let e = e.unwrap();
        let p = e.path();
        if p.is_dir() {
            copy_dir(&p, &to.join(e.file_name()));
        } else {
            std::fs::copy(&p, to.join(e.file_name())).unwrap();
        }
    }
}

fn scratch(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varimu_components_{tag}_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let cfg = dir.join("config");
    copy_dir(&repo_config(), &cfg);
    cfg
}

const WAIT: Duration = Duration::from_secs(300);

/// A guitar-like test signal: a plucked E2 chord's harmonics, decaying (guitar level:
/// the 5E3's full scale is 1 V peak in).
fn pluck(rate: u32, seconds: f64) -> Vec<f64> {
    let n = (seconds * rate as f64) as usize;
    let notes = [82.41, 123.47, 164.81, 207.65];
    (0..n)
        .map(|i| {
            let t = i as f64 / rate as f64;
            let env = (-t * 2.5).exp() * (1.0 - (-t * 400.0).exp());
            notes
                .iter()
                .flat_map(|&f| (1..12).map(move |h| (f, h)))
                .map(|(f, h)| (2.0 * std::f64::consts::PI * f * h as f64 * t).sin() / h as f64)
                .sum::<f64>()
                * 0.08
                * env
        })
        .collect()
}

#[test]
fn the_store_lists_its_transformers_and_their_users() {
    let cfg = repo_config();
    let all = transformer_components(&cfg);
    let names: Vec<&str> = all.iter().map(|(n, _)| n.as_str()).collect();
    assert!(
        names.contains(&"OT_5E3") && names.contains(&"BV191"),
        "{names:?}"
    );
    assert!(!names.contains(&"12AX7") && !names.contains(&"P12R"));
    let u = uses(&cfg, "OT_5E3");
    let circuits: Vec<&str> = u.iter().map(|x| x.circuit.as_str()).collect();
    assert_eq!(circuits[0], "fender_5e3", "{circuits:?}"); // hand-written first
    assert!(circuits.contains(&"fender_5e3_drawn"));
    assert_eq!(u[0].params, ["ot_model"]);
    assert_eq!(u[0].version, 2);
    assert!(!u[0].drawn && u[1].drawn);
}

#[test]
fn an_unedited_version_is_itself_and_edits_undo() {
    let cfg = repo_config();
    let mut b = Bench::open(&cfg, "OT_5E3@2").unwrap();
    let o = b.wait(WAIT).unwrap();
    assert_eq!(
        o.saved.as_ref().map(ToString::to_string).as_deref(),
        Some("OT_5E3@2")
    );
    assert!(!b.edited());
    // Its pinned and design sides are the same circuit (no unsaved version).
    let d = b.playable(Side::Design).unwrap();
    assert!(d.title.contains("OT_5E3@2") && !d.title.contains("unsaved"));

    // A drag of one value is one undo step; undo returns the version.
    let p = path!["core", "stack_m"];
    for x in [0.026, 0.027, 0.028] {
        b.set(p.clone(), Value::Float(x)).unwrap();
    }
    assert_eq!(edit::number(&b.design, &p), Some(0.028));
    assert!(
        edit::source(&b.design, &p)
            .unwrap()
            .starts_with("design choice")
    );
    let o = b.wait(WAIT).unwrap();
    assert!(o.saved.is_none());
    assert!(b.edited());
    b.undo();
    assert!(!b.can_undo());
    assert_eq!(edit::number(&b.design, &p), Some(0.0254));
    let o = b.wait(WAIT).unwrap();
    assert_eq!(
        o.saved.as_ref().map(ToString::to_string).as_deref(),
        Some("OT_5E3@2")
    );
    b.redo();
    assert_eq!(edit::number(&b.design, &p), Some(0.028));
    // An invalid design is an error, not a crash; the last good outcome stays.
    b.set(
        path!["sections", 0, "wire"],
        Value::Str("AWG 99 heavy".into()),
    )
    .unwrap();
    assert!(b.wait(WAIT).is_err());
    assert!(b.outcome.is_some());
}

#[test]
fn a_second_winding_plan_is_made_heard_saved_and_pinned() {
    let cfg = scratch("plan");
    let mut b = Bench::open(&cfg, "OT_5E3").unwrap();
    assert_eq!(b.opened.as_ref().unwrap().version, Some(2));
    let first = b.wait(WAIT).unwrap().compiled.clone();
    // The plan: pa | s | pb, the secondary between the primary halves (the paper wraps
    // kept on both sides of it).
    let kinds = |b: &Bench| -> Vec<String> {
        edit::sections(&b.design)
            .iter()
            .map(|s| match edit::section_kind(s) {
                Some(SectionKind::Winding) => edit::section_winding(s).unwrap().to_string(),
                Some(k) => format!("{k:?}"),
                None => "?".into(),
            })
            .collect()
    };
    assert_eq!(kinds(&b), ["pa", "Insulation", "pb", "Insulation", "s"]);
    b.edit(vec![], |d| edit::move_section(d, 4, 2)).unwrap();
    b.edit(vec![], |d| edit::move_section(d, 4, 3)).unwrap();
    assert_eq!(kinds(&b), ["pa", "Insulation", "s", "Insulation", "pb"]);
    let second = b.wait(WAIT).unwrap();
    assert!(second.saved.is_none() && !second.preview);
    let c2 = second.compiled.clone();
    // Same turns; the inner half's leakage to the secondary more than halved (it was the
    // farther one), the outer's about as it was: the halves now alike (2.1x apart before).
    let ix = |w: &str| c2.design.winding_index(w);
    let (pa, pb, s) = (ix("pa"), ix("pb"), ix("s"));
    assert_eq!(c2.windings[s].turns, first.windings[s].turns);
    for k in [pa, pb] {
        let (old, new) = (first.short_circuit_h(k, s), c2.short_circuit_h(k, s));
        println!(
            "{}: leakage with s shorted {:.2} -> {:.2} mH",
            c2.windings[k].label,
            old * 1e3,
            new * 1e3
        );
    }
    assert!(c2.short_circuit_h(pa, s) < 0.5 * first.short_circuit_h(pa, s));
    assert!(first.short_circuit_h(pa, s) > 2.0 * first.short_circuit_h(pb, s));
    let ratio = c2.short_circuit_h(pa, s) / c2.short_circuit_h(pb, s);
    assert!((ratio - 1.0).abs() < 0.15, "{ratio}");

    // Heard against the first in the 5E3 at draft-1x: both sides build and render, and
    // differ; the loudness match runs.
    assert_eq!(b.play_use().unwrap().circuit, "fender_5e3");
    let s1 = Settings::load(&cfg, Quality::Draft1x).unwrap();
    let x = pluck(s1.sample_rate, 1.5);
    let cancel = AtomicBool::new(false);
    let mut outs = Vec::new();
    for side in [Side::Pinned, Side::Design] {
        let p = b.playable(side).unwrap();
        println!("{}", p.title);
        let c = Circuit::from_spec(p.lib, p.spec, s1.cores().unwrap());
        let r = render(&c, &Vec::new(), &x, &s1, |_| {}, &cancel).unwrap();
        assert!(r.out.iter().all(|v| v.is_finite()));
        outs.push(r.out);
    }
    let rms = |v: &[f64]| (v.iter().map(|x| x * x).sum::<f64>() / v.len() as f64).sqrt();
    let diff: Vec<f64> = outs[0].iter().zip(&outs[1]).map(|(a, b)| a - b).collect();
    let rel_db = 20.0 * (rms(&diff) / rms(&outs[0])).log10();
    println!("difference {rel_db:.1} dB re the pinned side");
    assert!(rel_db > -60.0 && rel_db < 0.0, "{rel_db}");
    b.start_match(x, Vec::new(), s1);
    while b.matching() {
        std::thread::sleep(Duration::from_millis(20));
        b.poll();
    }
    let trim = b.match_db().expect("a loudness match");
    println!("loudness match: the design trimmed {trim:+.2} dB");
    assert!(trim.abs() < 6.0);

    // Saved as the next version: the file, its lock line, readable; saving again is a
    // no-op; the bench now reads it as saved.
    let root = cfg.join("components");
    let r = b.save().unwrap();
    assert_eq!(r.to_string(), "OT_5E3@3");
    let (_, text) = versions::read_text(&root, &r).unwrap();
    assert_eq!(saved_as(&root, "OT_5E3", &text), Some(r.clone()));
    assert_eq!(b.save().unwrap(), r);
    assert_eq!(versions::versions(&root, "OT_5E3"), [1, 2, 3]);
    assert!(!b.edited());

    // The circuit moved to it explicitly: its parameter names @3, nothing else changed.
    let before = std::fs::read_to_string(cfg.join("circuits/fender_5e3.yaml")).unwrap();
    b.move_pin().unwrap();
    let after = std::fs::read_to_string(cfg.join("circuits/fender_5e3.yaml")).unwrap();
    let changed: Vec<(&str, &str)> = before
        .lines()
        .zip(after.lines())
        .filter(|(a, b)| a != b)
        .collect();
    assert_eq!(changed.len(), 1, "{changed:?}");
    assert!(changed[0].1.contains("value: OT_5E3@3"), "{}", changed[0].1);
    assert_eq!(before.lines().count(), after.lines().count());
    assert_eq!(b.play_use().unwrap().version, 3);
    // As pinned it now builds from the saved @3, equal to what played as the design.
    let p = b.playable(Side::Pinned).unwrap();
    let c = Circuit::from_spec(p.lib, p.spec, s1_cores(&cfg));
    assert!(c.build(&Vec::new()).is_ok());
    // A drawn circuit's pin isn't moved from here.
    b.play_in = b.uses.iter().position(|u| u.drawn).unwrap();
    assert!(b.move_pin().unwrap_err().contains("drawing"));
    let _ = std::fs::remove_dir_all(cfg.parent().unwrap());
}

fn s1_cores(cfg: &Path) -> varimu_circuit::Cores {
    Settings::load(cfg, Quality::Draft1x)
        .unwrap()
        .cores()
        .unwrap()
}

#[test]
fn retarget_replaces_parameters_and_inline_parts() {
    let cfg = repo_config();
    let mut spec =
        varimu_circuit::spec::load_circuit(&cfg.join("circuits/fender_5e3.yaml")).unwrap();
    assert_eq!(retarget(&mut spec, "ot_5e3", "OT_5E3@9"), 1);
    let v = spec
        .values
        .get("ot_model")
        .unwrap()
        .as_map()
        .unwrap()
        .get("value")
        .unwrap();
    assert_eq!(v.as_str(), Some("OT_5E3@9"));
    assert_eq!(retarget(&mut spec, "BV191", "BV191@9"), 0);
    let _ = Ref {
        name: String::new(),
        version: None,
    };
}
