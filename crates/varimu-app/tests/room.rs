//! The Room view's render path end to end (docs/ROOM_LOOP_PLAN.md): a scene written as the
//! view writes it, the Python render run as a background process, its prints read back.
//! Needs `uv` and the repo's Python environment, so it is ignored by default:
//! `cargo test --release -p varimu-app --test room -- --ignored`.

use std::collections::BTreeMap;
use std::path::Path;

use varimu_app::audio;
use varimu_app::room::{RenderJob, RoomMic, RoomSource, Scene};

#[test]
#[ignore]
fn a_scene_renders_into_mic_prints() {
    let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let dir = std::env::temp_dir().join(format!("varimu_room_{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    // a 0.4 s 440 Hz tone with a fade, at 48 kHz
    let rate = 48_000;
    let x: Vec<f64> = (0..(rate as usize * 2 / 5))
        .map(|i| {
            let t = i as f64 / rate as f64;
            (2.0 * std::f64::consts::PI * 440.0 * t).sin() * (t / 0.02).min(1.0)
        })
        .collect();
    let clip = dir.join("a.wav");
    audio::write_wav(&clip, &x, rate).unwrap();
    let mut scene = Scene {
        name: "test".into(),
        plan: varimu_app::room::preset_plan("shoebox", 4.0, 3.0),
        roof: varimu_app::room::Ceiling {
            height: 2.5,
            ..Default::default()
        },
        quality: "draft".into(),
        ..Scene::default()
    };
    scene.sources.push(RoomSource {
        name: "A".into(),
        track: "k".into(),
        spl_db: 94.0,
        pos: [1.5, 1.5, 1.2],
    });
    for (name, chain, x) in [("near", "u47_v76", 1.8), ("far", "omni_clean", 3.2)] {
        let mut m = RoomMic::new(name, chain, [x, 1.5, 1.2], 0.0);
        m.aim_at(1.5, 1.5);
        scene.mics.push(m);
    }
    assert!(scene.problems().is_empty());
    let clips = BTreeMap::from([("A".to_string(), clip)]);
    let scene_path = dir.join("scene.json");
    std::fs::write(&scene_path, scene.render_json(&clips).to_string()).unwrap();
    let mut job = RenderJob::spawn(&root, &scene_path, &dir.join("render")).unwrap();
    let rendered = loop {
        if let Some(r) = job.poll() {
            break r.unwrap();
        }
        std::thread::sleep(std::time::Duration::from_millis(200));
    };
    assert_eq!(rendered.mics.len(), 2);
    let level = |name: &str| {
        let m = rendered.mics.iter().find(|m| m.name == name).unwrap();
        let y = audio::load(&m.file, rate).unwrap();
        assert!(y.len() > x.len());
        (y.iter().map(|v| v * v).sum::<f64>() / y.len() as f64).sqrt()
    };
    let (near, far) = (level("near"), level("far"));
    assert!(near > 0.0 && far > 0.0 && near.is_finite() && far.is_finite());
    let _ = std::fs::remove_dir_all(&dir);
}
