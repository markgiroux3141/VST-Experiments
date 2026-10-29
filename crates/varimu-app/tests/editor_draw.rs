//! R3's done-when: the triode stage drawn from scratch in the native editor, through its
//! editing API (pointer clicks on the canvas, keys, the inspector's fields, the prompts),
//! step for step as scripts/editor_draw_triode.py draws it on the web page. The drawing
//! comes out byte for byte the committed config/circuits/triode_stage_drawn.drawing.json
//! (which the web editor drew), it passes the checks, Save as writes the committed
//! circuit file, and it builds triode_stage_drawn.yaml's IR bit for bit.

use std::path::{Path, PathBuf};

use varimu_app::editor::Editor;
use varimu_app::editor::session::{Key, Mode, Mods};
use varimu_circuit::compile::compiled_spec;
use varimu_circuit::spec::{load_circuit, resolve};
use varimu_circuit::yaml::Value;
use varimu_circuit::{Cores, build_ir};

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

const PROVISIONAL: &str = "provisional: model knowledge";

fn source(key: &str) -> String {
    let what = match key {
        "b_plus_v" => "a textbook 12AX7 plate supply, 250-300 V",
        "r_source_ohm" => "a source impedance that lets the grid-current peaks show",
        "c_in_f" => "coupling capacitor: 1.6 Hz with the grid leak",
        "r_grid_ohm" => "12AX7 grid leak, 0.5-1 MOhm",
        "r_plate_ohm" => "12AX7 plate load, 100k",
        "r_cathode_ohm" => "12AX7 self-bias with a 100k plate load, 1.5k",
        "c_cathode_f" => "cathode bypass, a few Hz",
        "c_out_f" => "output coupling capacitor",
        "r_load_ohm" => "the next stage's grid leak",
        _ => panic!("{key}"),
    };
    format!("{PROVISIONAL} ({what})")
}

/// (symbol, ref, x, y, quarter turns, value, source key): the script's PARTS.
type Part = (
    &'static str,
    &'static str,
    f64,
    f64,
    usize,
    Option<&'static str>,
    Option<&'static str>,
);
const PARTS: [Part; 10] = [
    ("Triode", "V1", 40.64, 0.0, 0, None, None),
    ("V", "VB", 25.4, -22.86, 0, Some("250"), Some("b_plus_v")),
    ("R", "RS", 10.16, 0.0, 1, Some("10k"), Some("r_source_ohm")),
    ("C", "CI", 22.86, 0.0, 1, Some("100n"), Some("c_in_f")),
    ("R", "RG", 30.48, 7.62, 0, Some("1M"), Some("r_grid_ohm")),
    (
        "R",
        "RP",
        40.64,
        -15.24,
        0,
        Some("100k"),
        Some("r_plate_ohm"),
    ),
    (
        "R",
        "RK",
        40.64,
        15.24,
        0,
        Some("1.5k"),
        Some("r_cathode_ohm"),
    ),
    ("C", "CK", 48.26, 15.24, 0, Some("22u"), Some("c_cathode_f")),
    ("C", "CO", 50.8, -8.89, 1, Some("100n"), Some("c_out_f")),
    ("R", "RL", 58.42, -5.08, 0, Some("470k"), Some("r_load_ohm")),
];

const WIRES: [&[(f64, f64)]; 9] = [
    &[(13.97, 0.0), (19.05, 0.0)],                     // RS - CI: a
    &[(26.67, 0.0), (33.02, 0.0)],                     // CI - V1.g: g
    &[(30.48, 3.81), (30.48, 0.0)],                    // RG on the grid wire
    &[(40.64, 7.62), (40.64, 11.43)],                  // V1.k - RK: k
    &[(48.26, 11.43), (48.26, 10.16), (40.64, 10.16)], // CK on the cathode
    &[(40.64, -11.43), (40.64, -7.62)],                // RP - V1.p: p
    &[(40.64, -8.89), (46.99, -8.89)],                 // the plate to CO
    &[(54.61, -8.89), (58.42, -8.89)],                 // CO - RL: out
    &[
        (25.4, -27.94),
        (25.4, -30.48),
        (40.64, -30.48),
        (40.64, -19.05),
    ], // VB + to RP: bp
];

const LABELS: [(&str, f64, f64); 7] = [
    ("in", 6.35, 0.0),
    ("a", 16.51, 0.0),
    ("g", 31.75, 0.0),
    ("k", 40.64, 8.89),
    ("p", 43.18, -8.89),
    ("out", 58.42, -8.89),
    ("bp", 33.02, -30.48),
];

const GROUNDS: [(f64, f64); 5] = [
    (30.48, 11.43),
    (40.64, 19.05),
    (48.26, 19.05),
    (58.42, -1.27),
    (25.4, -17.78),
];

/// A click on the canvas at drawing point (x, y), as the mouse makes it.
fn click(ed: &mut Editor, x: f64, y: f64) {
    let (sx, sy) = ed.cam.to_screen(x, y);
    ed.moved(sx, sy);
    ed.down(sx, sy, false);
    ed.up(sx, sy);
}

fn key(ed: &mut Editor, k: Key) -> bool {
    ed.key(k, Mods::default())
}

fn draw(ed: &mut Editor) {
    ed.open_blank();
    // A fixed camera: 9 points per mm, the stage in the middle.
    ed.cam.w = 1200.0;
    ed.cam.h = 800.0;
    let (w, h) = (ed.cam.w, ed.cam.h);
    ed.cam.set(w / 2.0 - 34.0 * 9.0, h / 2.0 + 6.0 * 9.0, 9.0);

    for (sym, r, x, y, turns, value, src) in PARTS {
        ed.set_mode(Mode::Place, Some(sym)); // a tile of the palette
        let (sx, sy) = ed.cam.to_screen(x, y);
        ed.moved(sx, sy);
        for _ in 0..turns {
            key(ed, Key::Char('r'));
        }
        ed.down(sx, sy, false);
        ed.up(sx, sy);
        key(ed, Key::Escape); // back to selecting; the new part stays selected
        let got = ed.sel.symbols[0].clone();
        if got != r {
            ed.rename(&got, r).unwrap();
        }
        if let (Some(v), Some(s)) = (value, src) {
            ed.commit_value(r, v, &source(s)).unwrap();
        }
    }

    key(ed, Key::Char('w'));
    for w in WIRES {
        for &(x, y) in w {
            click(ed, x, y);
        }
        key(ed, Key::Enter);
    }
    key(ed, Key::Escape);

    key(ed, Key::Char('l'));
    for (name, x, y) in LABELS {
        click(ed, x, y);
        assert!(ed.prompt.is_some(), "a label asks for its name");
        ed.answer(Some(name));
    }
    key(ed, Key::Char('g'));
    for (x, y) in GROUNDS {
        click(ed, x, y);
    }
    key(ed, Key::Escape);

    click(ed, 5.0, 25.0); // nothing selected: the circuit's own settings
    assert!(ed.sel.is_empty());
    ed.set_circuit(
        "title",
        Value::Str("12AX7 common-cathode stage (drawn in the editor)".into()),
    );
    let probes = "g, p, k"
        .split(',')
        .map(|p| Value::Str(p.trim().into()))
        .collect();
    ed.set_circuit("probes", Value::List(probes));
}

#[test]
fn the_triode_stage_drawn_from_scratch() {
    let mut ed = Editor::new(&config());
    draw(&mut ed);
    assert!(ed.analysis.ok(), "{:?}", ed.analysis.errors());
    assert!(ed.analysis.has_output);
    assert_eq!(ed.check_now(), &[], "the checks find nothing");

    // The drawing the web editor drew, byte for byte.
    let committed = config().join("circuits/triode_stage_drawn.drawing.json");
    let want = std::fs::read_to_string(&committed).unwrap();
    let got = ed.drawing.to_text();
    if got != want {
        let line = want.lines().zip(got.lines()).position(|(a, b)| a != b);
        panic!(
            "the drawing differs at line {line:?}:\n{:?}\n{:?}",
            line.and_then(|l| want.lines().nth(l)),
            line.and_then(|l| got.lines().nth(l))
        );
    }

    // Save as writes the committed files.
    let dir = std::env::temp_dir().join(format!("varimu_editor_draw_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    ed.circuits_dir = dir.clone();
    ed.save_as("triode_stage_drawn").unwrap();
    for f in ["triode_stage_drawn.drawing.json", "triode_stage_drawn.yaml"] {
        let a = std::fs::read_to_string(dir.join(f)).unwrap();
        let b = std::fs::read_to_string(config().join("circuits").join(f)).unwrap();
        assert!(a == b, "{f} differs from the committed one");
    }
    let _ = std::fs::remove_dir_all(&dir);

    // The same IR as triode_stage_drawn.yaml, linear and Jiles-Atherton cores.
    let b = compiled_spec(&ed.analysis.compiled).unwrap();
    let a = load_circuit(&config().join("circuits/triode_stage_drawn.yaml")).unwrap();
    for cores in [Cores::Linear, Cores::Ja] {
        let ia = build_ir(&ed.lib, &a, &resolve(&a, &[]).unwrap(), cores).unwrap();
        let ib = build_ir(&ed.lib, &b, &resolve(&b, &[]).unwrap(), cores).unwrap();
        assert_eq!(
            serde_json::to_string(&ia).unwrap(),
            serde_json::to_string(&ib).unwrap()
        );
    }
}

/// Undo takes the whole drawing back step by step; redo brings it back.
#[test]
fn undo_and_redo_the_whole_drawing() {
    let mut ed = Editor::new(&config());
    draw(&mut ed);
    let done = ed.drawing.clone();
    let steps = ed.hist.past.len();
    assert!(steps > 40, "{steps} steps");
    for _ in 0..steps {
        ed.undo();
    }
    assert_eq!(ed.drawing, varimu_app::editor::session::blank());
    for _ in 0..steps {
        ed.redo();
    }
    assert_eq!(ed.drawing, done);
}

/// Editing the drawn stage: E12 stepping keeps the value's provenance, a move drags its
/// wires along, copy and paste, delete.
#[test]
fn editing_the_drawn_stage() {
    let mut ed = Editor::new(&config());
    ed.open("triode_stage_drawn").unwrap();
    assert!(!ed.edited());
    let t = ed.step_value("RP", "100k", 1, false).unwrap();
    assert_eq!(t, "120k");
    let rp = ed.drawing.symbol("RP").unwrap();
    assert_eq!(rp.value, "120k");
    let src = rp.field("Source").unwrap().to_string();
    assert!(src.contains("by ear; was 100k (provisional"), "{src}");
    ed.step_value("RP", "120k", 1, false).unwrap();
    let src2 = ed.drawing.symbol("RP").unwrap().field("Source").unwrap();
    assert_eq!(src2, src, "a second step keeps what the first replaced");
    assert!(ed.edited());

    // Drag RL down by 2.54 mm: its wire to CO bends to follow.
    let pl = *ed.drawing.symbol("RL").unwrap().unit(1).unwrap();
    let (sx, sy) = ed.cam.to_screen(pl.x, pl.y);
    ed.moved(sx, sy);
    ed.down(sx, sy, false);
    let (tx, ty) = ed.cam.to_screen(pl.x, pl.y + 2.54);
    ed.moved(tx, ty);
    assert!(ed.preview.is_some(), "a drag previews");
    ed.up(tx, ty);
    assert_eq!(
        ed.drawing.symbol("RL").unwrap().unit(1).unwrap().y,
        pl.y + 2.54
    );
    assert!(ed.analysis.ok());
    ed.check_now();
    assert_eq!(ed.faults(), 0, "{:?}", ed.markers);

    // Copy RL and paste it: RL1? No: R1 is free, the copy is named after its letters.
    ed.select(varimu_app::editor::geom::Sel::symbol("RL"), -1);
    let ctrl = Mods {
        ctrl: true,
        ..Mods::default()
    };
    assert!(ed.key(Key::Char('d'), ctrl));
    assert_eq!(ed.sel.symbols, ["RL1"]);
    assert!(ed.key(Key::Delete, Mods::default()));
    assert!(ed.drawing.symbol("RL1").is_none());
    assert!(ed.playable().is_some(), "it can be heard");
}

/// Component versions (docs/COMPONENT_EDITOR_PLAN.md, C1): the model picker offers every
/// saved version as `NAME@N`; swapping one is an edit that rebuilds the circuit (a
/// different IR), its source saying what it was; undo takes it back.
#[test]
fn swapping_a_pinned_device_version() {
    let mut ed = Editor::new(&config());
    let refs: Vec<&str> = ed.parts.devices.iter().map(|(r, _)| r.as_str()).collect();
    for want in ["12AX7@1", "12AU7@1", "6386@1", "GZ34@1", "6973@1"] {
        assert!(refs.contains(&want), "{want} in {refs:?}");
    }
    assert!(refs.iter().all(|r| r.contains('@')), "{refs:?}");

    ed.open("triode_stage_drawn").unwrap();
    let ir = |ed: &Editor| {
        let s = compiled_spec(&ed.analysis.compiled).unwrap();
        let ir = build_ir(&ed.lib, &s, &resolve(&s, &[]).unwrap(), Cores::Linear).unwrap();
        serde_json::to_string(&ir).unwrap()
    };
    let before = ir(&ed);
    assert_eq!(ed.drawing.symbol("V1").unwrap().value, "12AX7@1");
    ed.set_device("V1", "12AU7@1");
    let v1 = ed.drawing.symbol("V1").unwrap();
    assert_eq!(v1.value, "12AU7@1");
    assert!(
        v1.field("Source").unwrap_or("").contains("12AX7@1"),
        "{:?}",
        v1.field("Source")
    );
    assert!(ed.analysis.ok(), "{:?}", ed.analysis.errors());
    assert_eq!(ed.check_now(), &[]);
    assert_ne!(
        ir(&ed),
        before,
        "a different tube builds a different circuit"
    );
    ed.undo();
    assert_eq!(ed.drawing.symbol("V1").unwrap().value, "12AX7@1");
    assert_eq!(ir(&ed), before);
}
