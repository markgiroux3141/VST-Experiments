//! The saved transformer versions against their published figures (docs/
//! COMPONENT_EDITOR_PLAN.md C2 step 5), and every design still compiling to its latest
//! saved version (a design edited without saving shows up here), and every version this
//! compiler saved recompiling from its own construction to its own text (what the
//! Components view relies on when it opens a version to edit).
//!
//! - BV191@3 (BV191@2 with its capacitor network), the V72's input transformer by its
//!   construction (NWDR Bauvorschrift 191, Blatt 4): the primary halves in series 25 H
//!   +- 10% (50 Hz, 10 mV); with the secondary shorted an impedance <= 140 ohm at 1 kHz and
//!   ~500 ohm at 15 kHz.
//! - OT_5E3@2 (OT_5E3@1 with its capacitor network, the version the 5E3 pins), the 5E3's
//!   output transformer fitted to Amplified Parts P-TGO-002: 8000 CT : 8 ohm; DCR 147.2 /
//!   195.3 / 0.493 ohm; 3.67 H per half (1 kHz, 1 V); leakage 40.47 / 19.31 mH per half
//!   with the secondary shorted.

use std::f64::consts::PI;
use std::path::{Path, PathBuf};

use varimu_circuit::Library;
use varimu_circuit::versions::{self, Ref};
use varimu_circuit::yaml::{self, Map, Value};
use varimu_components::COMPILER;
use varimu_components::compile::{compile, compile_file};
use varimu_components::design::Design;
use varimu_components::edit::design_of_version;
use varimu_components::store;
use varimu_components::tables::Tables;

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn version(name: &str, v: u32) -> Value {
    let root = config().join("components");
    let r = Ref {
        name: name.into(),
        version: Some(v),
    };
    let (_, text) = versions::read_text(&root, &r).unwrap();
    yaml::parse(&text, name).unwrap()
}

fn get<'a>(v: &'a Value, path: &[&str]) -> &'a Value {
    path.iter().fold(v, |x, k| {
        x.as_map()
            .and_then(|m| m.get(k))
            .unwrap_or_else(|| panic!("{k}"))
    })
}

fn num(v: &Value, path: &[&str]) -> f64 {
    get(v, path).as_f64().unwrap()
}

/// The compiled series leakages as a matrix over `labels` (the star's diagonal plus any
/// couplings), and the energy of currents `i` in it: the leakage those currents see.
fn leakage(v: &Value, labels: &[&str], i: &[f64]) -> f64 {
    let c = get(v, &["compiled"]);
    let l: Vec<f64> = labels
        .iter()
        .map(|w| num(c, &["windings", w, "leak"]))
        .collect();
    let mut m: Vec<Vec<f64>> = (0..labels.len())
        .map(|j| {
            (0..labels.len())
                .map(|k| if j == k { l[j] } else { 0.0 })
                .collect()
        })
        .collect();
    if let Some(ks) = c
        .as_map()
        .and_then(|m: &Map| m.get("leak_couplings"))
        .and_then(Value::as_list)
    {
        for d in ks {
            let b = get(d, &["between"]).as_list().unwrap();
            let j = labels.iter().position(|w| *w == b[0].py_str()).unwrap();
            let k = labels.iter().position(|w| *w == b[1].py_str()).unwrap();
            let x = num(d, &["k"]) * (l[j] * l[k]).sqrt();
            m[j][k] = x;
            m[k][j] = x;
        }
    }
    (0..labels.len())
        .flat_map(|j| (0..labels.len()).map(move |k| (j, k)))
        .map(|(j, k)| m[j][k] * i[j] * i[k])
        .sum()
}

#[test]
fn bv191_meets_the_v72s_figures() {
    let v = version("BV191", 3);
    let w = |k: &str, x: &str| num(&v, &["compiled", "windings", k, x]);
    // The halves in series (800 turns) against the 8000-turn secondary: 1:10.
    let n = 0.1;
    let l_open = 4.0 * num(&v, &["report", "windings", "p1", "magnetizing_h"]);
    assert!((l_open / 25.0 - 1.0).abs() < 0.10, "{l_open} H");
    let r = w("p1", "r") + w("p2", "r") + w("s", "r") * n * n;
    let l_sc = leakage(&v, &["p1", "p2", "s"], &[1.0, 1.0, -n]);
    let z = |f: f64| (r * r + (2.0 * PI * f * l_sc).powi(2)).sqrt();
    println!(
        "BV191@3: {l_open:.2} H, R {r:.1} ohm, L_sc {:.3} mH, |Z| {:.0} / {:.0} ohm",
        l_sc * 1e3,
        z(1e3),
        z(15e3)
    );
    assert!(z(1e3) <= 140.0, "{}", z(1e3));
    // ~500 ohm at 15 kHz: within 20% (the Trolitul masks' thickness is provisional).
    assert!((z(15e3) / 500.0 - 1.0).abs() < 0.20, "{}", z(15e3));
}

#[test]
fn ot_5e3_meets_p_tgo_002() {
    let v = version("OT_5E3", 2);
    let w = |k: &str, x: &str| num(&v, &["compiled", "windings", k, x]);
    let dcr = [w("pa", "r"), w("pb", "r"), w("s", "r")];
    println!("OT_5E3@2: DCR {dcr:?}");
    assert!((dcr[0] / 147.2 - 1.0).abs() < 0.01);
    // One half over the other reaches ~1.23 of the 1.33 resistance ratio (fit_ot_5e3.py).
    assert!((dcr[1] / 195.3 - 1.0).abs() < 0.10);
    // The secondary: the nearest wire size (a gauge is 26% in area).
    assert!((dcr[2] / 0.493 - 1.0).abs() < 0.13);
    // 8000 CT : 8 ohm: secondary turns per half 2 / sqrt(1000), to the turn.
    let ratio = w("s", "ratio");
    assert!(
        (ratio / (2.0 / 1000f64.sqrt()) - 1.0).abs() < 0.01,
        "{ratio}"
    );
    let l_open = num(&v, &["report", "windings", "pa", "magnetizing_h"]) + w("pa", "leak");
    assert!((l_open / 3.67 - 1.0).abs() < 0.01, "{l_open}");
    let labels = ["pa", "pb", "s"];
    let leak_a = leakage(&v, &labels, &[1.0, 0.0, -1.0 / ratio]);
    let leak_b = leakage(&v, &labels, &[0.0, 1.0, -1.0 / ratio]);
    println!(
        "OT_5E3@2: leakage {:.2} / {:.2} mH",
        leak_a * 1e3,
        leak_b * 1e3
    );
    assert!((leak_a / 40.47e-3 - 1.0).abs() < 0.03, "{leak_a}");
    assert!((leak_b / 19.31e-3 - 1.0).abs() < 0.03, "{leak_b}");
}

/// Every design file compiles to one of its saved versions' body (a design edited without
/// saving shows up here). Not necessarily the latest: versions made in the Components view
/// keep their construction in the version itself, not in config/designs.
#[test]
fn designs_match_their_saved_versions() {
    let root = config().join("components");
    for entry in std::fs::read_dir(config().join("designs")).unwrap() {
        let path = entry.unwrap().path();
        if path.extension().is_none_or(|e| e != "yaml") {
            continue;
        }
        let (data, tables, c) = compile_file(&path, &config()).unwrap();
        let text = c.version_text(&data, &tables, &config(), "any").unwrap();
        let body = |t: &str| store::body(t).replace("\r\n", "\n");
        let saved = versions::versions(&root, &c.design.name)
            .into_iter()
            .any(|v| {
                let r = Ref {
                    name: c.design.name.clone(),
                    version: Some(v),
                };
                body(&versions::read_text(&root, &r).unwrap().1) == body(&text)
            });
        assert!(
            saved,
            "{} differs from every saved version: save it (cargo run -p varimu-components -- save {})",
            path.display(),
            path.display()
        );
    }
}

/// Every transformer version this compiler saved recompiles from its construction to its
/// own text: a version opened in the Components view and saved unchanged is that version.
#[test]
fn versions_recompile_from_their_construction() {
    let cfg = config();
    let root = cfg.join("components");
    let lib = Library::new(&cfg);
    let tables = Tables::load(&cfg).unwrap();
    let mut checked = 0;
    for name in versions::names(&root) {
        for v in versions::versions(&root, &name) {
            let r = Ref {
                name: name.clone(),
                version: Some(v),
            };
            let (_, text) = versions::read_text(&root, &r).unwrap();
            let data = yaml::parse(&text, &name).unwrap();
            let m = data.as_map().unwrap();
            if m.get("kind").and_then(Value::as_str) != Some("transformer")
                || m.get("compiler").and_then(Value::as_str) != Some(COMPILER)
            {
                continue;
            }
            let design = design_of_version(&data).unwrap();
            let c = compile(&Design::parse(&design).unwrap(), &tables, &lib).unwrap();
            let again = c.version_text(&design, &tables, &cfg, "any").unwrap();
            assert_eq!(
                store::body(&again),
                store::body(&text).replace("\r\n", "\n"),
                "{name}@{v}"
            );
            checked += 1;
        }
    }
    assert!(checked >= 2, "{checked}");
}
