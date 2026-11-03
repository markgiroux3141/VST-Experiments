//! `varimu-components`: compile a transformer design and save it as a component version.
//!
//! ```sh
//! cargo run -p varimu-components -- compile config/designs/ot_5e3.yaml   # the report
//! cargo run -p varimu-components -- compile DESIGN --yaml                # the version file it would save
//! cargo run -p varimu-components -- save DESIGN                          # config/components/<name>/<N>.yaml + the lock
//! ```
//! `--config DIR` names the config directory (default: the repo's `config`).

use std::path::PathBuf;
use std::process::ExitCode;

use varimu_components::compile::{Compiled, LeakageModel, compile_file};
use varimu_components::design::Arrangement;
use varimu_components::fem;
use varimu_components::leakage::series_short_circuit;
use varimu_components::store;

const USAGE: &str = "usage: varimu-components (compile [--yaml] | save | fem) DESIGN.yaml [--config DIR] [--short DRIVE:SHORTED ...]\n  --short p1+p2:s  the leakage of p1 and p2 in series with s shorted\n  fem: every winding pair (and each --short) by the 2D field solution against the 1D formula";

fn default_config() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn print_report(c: &Compiled) {
    let d = &c.design;
    println!(
        "{} ({}; {} on {})",
        d.name,
        c.lamination.name,
        d.core.material.value,
        d.core.stacking.value_name()
    );
    println!(
        "  core: area {:.3} cm^2, path {:.2} cm, gap {:.1} um{}",
        c.area_m2 * 1e4,
        c.path_m * 1e2,
        c.gap_m * 1e6,
        c.fringing
            .map_or(String::new(), |f| format!(" (fringing {f:.3})"))
    );
    let (along, room) = match c.layout.arrangement {
        Arrangement::Layer => ("build", c.layout.window_width_m),
        Arrangement::Disc => ("length", c.layout.traverse_m),
    };
    println!(
        "  window: {:.2} x {:.2} mm, traverse {:.2} mm; the sections' {along} {:.2} mm of {:.2} mm; copper fill {:.1}%; field length {:.2} mm",
        c.layout.window_width_m * 1e3,
        c.layout.window_height_m * 1e3,
        c.layout.traverse_m * 1e3,
        c.layout.extent_m() * 1e3,
        room * 1e3,
        100.0 * c.copper_fill,
        c.layout.field_length_m * 1e3
    );
    println!(
        "  {:<6} {:>9} {:>8} {:>10} {:>10} {:>10} {:>10} {:>10}",
        "", "turns", "ratio", "DCR ohm", "Lm H", "leak mH", "star mH", "C pF"
    );
    for (k, w) in c.windings.iter().enumerate() {
        println!(
            "  {:<6} {:>9.1} {:>8.5} {:>10.3} {:>10.4} {:>10.4} {:>10.4} {:>10.2}",
            w.label,
            w.turns,
            w.ratio,
            w.r_ohm,
            c.magnetizing_h * w.ratio * w.ratio,
            w.leak_h * 1e3,
            c.star_h[k] * 1e3,
            w.c_f * 1e12
        );
    }
    let n = c.windings.len();
    for j in 0..n {
        for k in 0..n {
            if j != k {
                println!(
                    "  leakage of {} with {} shorted: {:.4} mH",
                    c.windings[j].label,
                    c.windings[k].label,
                    c.short_circuit_h(j, k) * 1e3
                );
            }
        }
    }
    if let LeakageModel::Coupled(ks) = &c.leakage_model {
        for (j, k, x) in ks {
            println!(
                "  coupling {}-{}: k = {x:.5}",
                c.windings[*j].label, c.windings[*k].label
            );
        }
    }
    for b in &c.capacitance.between {
        println!(
            "  capacitance {}-{} (sections {} and {}): {:.2} pF",
            c.windings[b.a].label,
            c.windings[b.b].label,
            b.sections.0,
            b.sections.1,
            b.c_f * 1e12
        );
    }
    for s in &c.capacitance.to_shields {
        println!(
            "  capacitance {}-{} (sections {} and {}): {:.2} pF",
            c.windings[s.winding].label,
            s.shield,
            s.sections.0,
            s.sections.1,
            s.c_f * 1e12
        );
    }
    if let Some(b) = c.b_peak_t {
        let r = d.rating.as_ref().unwrap();
        println!(
            "  flux: {:.4} mT peak at {} V rms, {} Hz across {} (saturation {:.3} T)",
            b * 1e3,
            r.v_rms.value,
            r.f_hz.value,
            r.windings.join("+"),
            c.b_saturation_t
        );
    }
    for w in &c.warnings {
        println!("  warning: {w}");
    }
}

trait StackingName {
    fn value_name(&self) -> &'static str;
}

impl StackingName for varimu_components::sourced::Sourced<varimu_components::design::Stacking> {
    fn value_name(&self) -> &'static str {
        match self.value {
            varimu_components::design::Stacking::Butt => "butt stacking",
            varimu_components::design::Stacking::Interleaved => "interleaved stacking",
        }
    }
}

fn groups(c: &Compiled, g: &str) -> Result<Vec<usize>, String> {
    g.split('+')
        .map(|w| {
            c.design
                .windings
                .iter()
                .position(|x| x == w)
                .ok_or(format!("--short: no winding {w}"))
        })
        .collect()
}

fn run() -> Result<(), String> {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut config = default_config();
    let mut yaml = false;
    let mut shorts = Vec::new();
    let mut rest = Vec::new();
    let mut it = args.iter();
    while let Some(a) = it.next() {
        match a.as_str() {
            "--config" => config = PathBuf::from(it.next().ok_or(USAGE)?),
            "--yaml" => yaml = true,
            "--short" => shorts.push(it.next().ok_or(USAGE)?.clone()),
            "-h" | "--help" => return Err(USAGE.into()),
            _ => rest.push(a.clone()),
        }
    }
    let [cmd, design] = &rest[..] else {
        return Err(USAGE.into());
    };
    let (data, tables, c) = compile_file(&PathBuf::from(design), &config).map_err(|e| e.0)?;
    let text = c
        .version_text(&data, &tables, &config, &store::today())
        .map_err(|e| e.0)?;
    let root = config.join("components");
    match cmd.as_str() {
        "compile" if yaml => print!("{text}"),
        "fem" => {
            let n = c.windings.len();
            let z0 = c.design.bobbin.cheek_m.value + c.design.bobbin.margin_m.value;
            let mut cases: Vec<(String, Vec<usize>, Vec<usize>)> = Vec::new();
            for j in 0..n {
                for k in 0..n {
                    if j != k {
                        let l = |i: usize| c.windings[i].label.clone();
                        cases.push((format!("{}:{}", l(j), l(k)), vec![j], vec![k]));
                    }
                }
            }
            for s in &shorts {
                let (drive, shorted) = s.split_once(':').ok_or(USAGE)?;
                cases.push((s.clone(), groups(&c, drive)?, groups(&c, shorted)?));
            }
            println!(
                "{} ({}): leakage, 1D formula vs 2D field solution",
                c.design.name, c.lamination.name
            );
            for (label, d, s) in cases {
                let one = series_short_circuit(&c.layout, n, &d, &s);
                let two = fem::series_short_circuit(&c.layout, z0, n, &d, &s, fem::Mesh::default());
                println!(
                    "  {label:<12} 1D {:>10.4} mH   2D {:>10.4} mH   1D/2D {:+.1}%",
                    one * 1e3,
                    two * 1e3,
                    100.0 * (one / two - 1.0)
                );
            }
        }
        "compile" => {
            print_report(&c);
            for s in &shorts {
                let (drive, shorted) = s.split_once(':').ok_or(USAGE)?;
                let ix = |g: &str| -> Result<Vec<usize>, String> {
                    g.split('+')
                        .map(|w| {
                            c.design
                                .windings
                                .iter()
                                .position(|x| x == w)
                                .ok_or(format!("--short: no winding {w}"))
                        })
                        .collect()
                };
                let l = c.group_short_circuit_h(&ix(drive)?, &ix(shorted)?);
                println!(
                    "  leakage of {drive} with {shorted} shorted: {:.4} mH",
                    l * 1e3
                );
            }
        }
        "save" => {
            print_report(&c);
            if let Some(r) = store::unchanged(&root, &c.design.name, &text).map_err(|e| e.0)? {
                println!("unchanged: {r} has this design and compiled form; nothing saved");
            } else {
                let r = store::save(&root, &c.design.name, &text).map_err(|e| e.0)?;
                println!("saved {r}");
            }
        }
        _ => return Err(USAGE.into()),
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("{e}");
            ExitCode::from(2)
        }
    }
}
