//! Editor edits heard live (R3b): the player's engine on the editor's compiled drawing.
//! A value edit updates the playing stream in place; an edit of the topology restarts it
//! (settled in the background, crossfaded in).

use std::path::{Path, PathBuf};
use std::time::Duration;

use varimu_app::editor::Editor;
use varimu_app::live::{Circuit, Live};
use varimu_app::settings::{Quality, Settings};

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

fn rms(y: &[f32]) -> f64 {
    (y.iter().map(|&v| f64::from(v) * f64::from(v)).sum::<f64>() / y.len() as f64).sqrt()
}

fn blocks(live: &mut Live, n: usize) -> Vec<f32> {
    (0..n)
        .flat_map(|_| live.next_block(480).unwrap().0)
        .collect()
}

#[test]
fn editor_edits_are_heard() {
    let s = Settings::load(&config(), Quality::Draft1x).unwrap();
    let cores = s.cores().unwrap();
    let mut ed = Editor::new(&config());
    ed.open("triode_stage_drawn").unwrap();
    let circuit = |ed: &Editor| Circuit::from_spec(ed.lib.clone(), ed.playable().unwrap(), cores);
    let n = s.sample_rate as usize / 2;
    let tone: Vec<f64> = (0..n)
        .map(|i| 0.05 * (std::f64::consts::TAU * 1000.0 * i as f64 / s.sample_rate as f64).sin())
        .collect();
    let mut live = Live::new(&tone, Vec::new(), circuit(&ed), s.clone()).unwrap();
    blocks(&mut live, 20);
    let before = rms(&blocks(&mut live, 40));
    assert!(before > 1e-3, "the stage plays: {before}");

    // A value (the load, 470k -> 4.7k): the stream updates in place.
    ed.commit_value("RL", "4.7k", "test: a heavy load").unwrap();
    live.set_circuit(circuit(&ed), Vec::new());
    std::thread::sleep(Duration::from_millis(500));
    blocks(&mut live, 20);
    let loaded = rms(&blocks(&mut live, 40));
    assert_eq!(live.error(), None);
    assert_eq!(live.restarts, 0, "a value updates the stream");
    let db = 20.0 * (loaded / before).log10();
    assert!(db < -10.0, "the load is heard: {db:.1} dB");

    // The topology (the cathode bypass deleted): a restart.
    ed.select(varimu_app::editor::geom::Sel::symbol("CK"), -1);
    assert!(ed.key(
        varimu_app::editor::session::Key::Delete,
        varimu_app::editor::session::Mods::default()
    ));
    live.set_circuit(circuit(&ed), Vec::new());
    std::thread::sleep(Duration::from_secs(3));
    let y = blocks(&mut live, 40);
    assert_eq!(live.error(), None);
    assert_eq!(live.restarts, 1, "a new structure restarts the stream");
    assert!(y.iter().all(|v| v.is_finite()));
    let unbypassed = rms(&blocks(&mut live, 40));
    let db = 20.0 * (unbypassed / loaded).log10();
    assert!(db < -2.0, "less gain without the bypass: {db:.1} dB");
}
