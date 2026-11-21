//! A session's source take replaced and everything made from it made again, headless: the
//! room tracks rendered again from it, every insert and the master chain printed, the mix
//! exported. The Session and Room views' own code paths, without the app.
//!
//!     cargo run --release -p varimu-app --example session_rerender -- --session DIR
//!         --track NAME --import FILE [--gain-db G] [--room] [--room-from lane|playing]
//!         [--export NAME]
//!
//! - `--import FILE` (with `--gain-db`, the import's gain) becomes a new take of track
//!   `--track`, laid where its active clip was with that clip's gain, fades and envelope
//!   (the old take stays in the track's takes: undo-free, but nothing is lost).
//! - `--room`: the session's `rooms/scene.json` rendered again into a new
//!   `rooms/render_<stamp>/` (`room_print.py`, as the Room view's Render), its sources
//!   written from each source track's lane (`lane`, the default: the clips with their
//!   gains, no inserts) or as the mix plays it (`playing`: its print, the Room view's way
//!   today); each mic's print replaces the take of the track `<scene> · <mic>` the same way.
//! - Then every track's chain and the master's are printed (into the session's print
//!   cache, as the app prints them) and the mix is exported to
//!   `<session>/exports/<NAME>.wav` with its JSON (⤓ Export mix…).
//!
//! The session is saved after each step; `session.json` is copied to
//! `session.before-rerender.json` first.

use std::collections::BTreeMap;
use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::{Duration, Instant};

use serde_json::{Value, json};
use varimu_app::audio;
use varimu_app::print::{ChainResult, Job, Slot};
use varimu_app::room::{self, RenderJob, Scene};
use varimu_app::session::{OVERVIEW_BIN, Overview, Printed, Session};

fn wait_print(job: &Job, what: &str) -> ChainResult {
    let t0 = Instant::now();
    let mut last = Instant::now();
    while !job.is_finished() {
        std::thread::sleep(Duration::from_millis(200));
        if last.elapsed() > Duration::from_secs(20) {
            last = Instant::now();
            let (k, f) = job.progress();
            eprintln!(
                "  {what}: insert {} {:.0}% ({:.0} s)",
                k + 1,
                f * 100.0,
                t0.elapsed().as_secs_f64()
            );
        }
    }
    job.join().ok_or("the print was cancelled")?
}

/// The Session view's `Printed` from a chain's prints (`poll_prints`).
fn printed(
    prints: Vec<varimu_app::print::Print>,
    signature: String,
    lane: String,
    start: i64,
    stereo_lane: bool,
) -> Result<Printed, String> {
    let audio = prints.last().map(|p| p.audio.clone()).ok_or("no print")?;
    let stereo = stereo_lane || prints.iter().any(|p| p.right.is_some());
    let right_of =
        |p: &varimu_app::print::Print| p.right.clone().unwrap_or_else(|| p.audio.clone());
    let right = stereo.then(|| prints.last().map(right_of)).flatten();
    Ok(Printed {
        signature,
        lane,
        start,
        overview: Arc::new(Overview::of_lr(
            &audio,
            right.as_deref().map(Vec::as_slice),
            OVERVIEW_BIN,
        )),
        audio,
        right,
        stages: prints.iter().map(|p| p.audio.clone()).collect(),
        stages_right: if stereo {
            prints.iter().map(right_of).collect()
        } else {
            Vec::new()
        },
    })
}

/// `samples` as a new take of track `t`, in place of its active clip (its position, gain,
/// fades, envelope); the old clip removed, its take kept.
fn replace_take(
    s: &mut Session,
    t: usize,
    samples: Vec<f32>,
    right: Option<Vec<f32>>,
    position: Option<i64>,
    from: Value,
) -> Result<String, String> {
    let track = &s.tracks[t];
    let active = track
        .active_take()
        .ok_or("the track has no take")?
        .id
        .clone();
    let c = track
        .clips
        .iter()
        .position(|c| c.take == active)
        .ok_or("the active take has no clip")?;
    let old = track.clips[c].clone();
    let id = s.add_rendered_take(t, samples, right, position.unwrap_or(old.position), from)?;
    let track = &mut s.tracks[t];
    let new = track.clips.last_mut().expect("just added");
    new.gain_db = old.gain_db;
    new.fade_in = old.fade_in;
    new.fade_out = old.fade_out;
    new.muted = old.muted;
    new.invert = old.invert;
    new.curve = old.curve;
    new.env = old.env.clone();
    track.clips.remove(c);
    s.save()?;
    Ok(id)
}

fn safe(name: &str) -> String {
    name.chars()
        .map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut dir, mut track, mut import, mut export) = (None, None, None, None);
    let (mut gain_db, mut do_room, mut room_from) = (0.0f64, false, "lane".to_string());
    while let Some(a) = args.next() {
        let mut val = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--session" => dir = Some(PathBuf::from(val()?)),
            "--track" => track = Some(val()?),
            "--import" => import = Some(PathBuf::from(val()?)),
            "--gain-db" => gain_db = val()?.parse().map_err(|e| format!("--gain-db: {e}"))?,
            "--room" => do_room = true,
            "--room-from" => room_from = val()?,
            "--export" => export = Some(val()?),
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let dir = dir.ok_or("--session DIR")?;
    let repo = Path::new(env!("CARGO_MANIFEST_DIR")).join("../..");
    let repo = repo.canonicalize().map_err(|e| e.to_string())?;
    let config = repo.join("config");
    std::fs::copy(
        dir.join("session.json"),
        dir.join("session.before-rerender.json"),
    )
    .map_err(|e| e.to_string())?;
    let mut s = Session::load(&dir)?;
    let rate = s.rate;

    // 1. The new source take.
    if let Some(file) = &import {
        let name = track.as_deref().ok_or("--import needs --track")?;
        let t = s
            .tracks
            .iter()
            .position(|x| x.name == name)
            .ok_or(format!("no track {name}"))?;
        let chans = audio::load_channels(file, rate)?;
        let g = 10f64.powf(gain_db / 20.0);
        let scaled = |x: &[f64]| x.iter().map(|&v| (v * g) as f32).collect::<Vec<f32>>();
        let left = scaled(&chans[0]);
        let right = chans.get(1).map(|r| scaled(r));
        let file_name = file
            .file_name()
            .map_or("?".into(), |n| n.to_string_lossy().to_string());
        let from = json!({
            "device": format!("import of {file_name}"),
            "import": {
                "file": file.to_string_lossy(),
                "rate": rate,
                "normalize": "off",
                "gain_db": gain_db,
                "channels": chans.len(),
            },
        });
        let id = replace_take(&mut s, t, left, right, None, from)?;
        eprintln!("{name}: new take {id} from {file_name} ({gain_db:+.3} dB)");
    }

    // 2. The room, rendered again from its sources' tracks.
    if do_room {
        if let Some(e) = room::init_chains(&config) {
            return Err(e.to_string());
        }
        let state: Value = serde_json::from_str(
            &std::fs::read_to_string(dir.join("rooms").join("scene.json"))
                .map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        let scene = Scene::from_state(&state);
        let stamp = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_or(0, |d| d.as_secs());
        let rdir = dir.join("rooms").join(format!("render_{stamp}"));
        std::fs::create_dir_all(rdir.join("sources")).map_err(|e| e.to_string())?;
        let mut takes = Vec::new();
        for src in &scene.sources {
            let i = s
                .track_index(&src.track)
                .ok_or(format!("{}: its track is gone", src.name))?;
            let tr = &s.tracks[i];
            let (pos, l, r) = if room_from == "playing" {
                if !s.print_current(i) {
                    return Err(format!("{}: its inserts aren't printed", src.name));
                }
                tr.playing_lr(rate).ok_or("no take")?.0
            } else {
                tr.lane_lr().ok_or("no take")?
            };
            takes.push((src.name.clone(), pos, l, r));
        }
        let start = takes.iter().map(|t| t.1).min().unwrap_or(0);
        let (mut clips, mut rights) = (BTreeMap::new(), BTreeMap::new());
        for (name, pos, l, r) in &takes {
            let lead = (pos - start).max(0) as usize;
            let write = |x: &[f32], suffix: &str| -> Result<PathBuf, String> {
                let mut y = vec![0.0f64; lead];
                y.extend(x.iter().map(|&v| v as f64));
                let p = rdir
                    .join("sources")
                    .join(format!("{}{suffix}.wav", safe(name)));
                audio::write_wav(&p, &y, rate)?;
                Ok(p)
            };
            match r {
                Some(r) => {
                    clips.insert(name.clone(), write(l, ".L")?);
                    rights.insert(name.clone(), write(r, ".R")?);
                }
                None => {
                    clips.insert(name.clone(), write(l, "")?);
                }
            }
        }
        let scene_json = scene.render_json_lr(&clips, &rights);
        let scene_path = rdir.join("scene.json");
        std::fs::write(
            &scene_path,
            serde_json::to_string_pretty(&scene_json).unwrap(),
        )
        .map_err(|e| e.to_string())?;
        eprintln!("room: rendering into {}", rdir.display());
        let mut job = RenderJob::spawn(&repo, &scene_path, &rdir.join("render"))?;
        let t0 = Instant::now();
        let mut last = Instant::now();
        let rendered = loop {
            if let Some(r) = job.poll() {
                break r.map_err(|e| format!("{e}\n{}", job.tail(30).join("\n")))?;
            }
            std::thread::sleep(Duration::from_millis(500));
            if last.elapsed() > Duration::from_secs(60) {
                last = Instant::now();
                eprintln!(
                    "  room: {:.0}% ({:.0} s) {}",
                    job.progress() * 100.0,
                    t0.elapsed().as_secs_f64(),
                    job.tail(1).join("")
                );
            }
        };
        for m in &rendered.mics {
            let tname = format!("{} · {}", scene.name, m.name);
            let t = s
                .tracks
                .iter()
                .position(|x| x.name == tname)
                .ok_or(format!("no track {tname}"))?;
            let x = audio::load(&m.file, rate)?;
            let from = json!({
                "take": format!("room {}", scene.name),
                "room": {"scene": scene_json, "mic": m.name, "render": rendered.json},
            });
            let samples = x.iter().map(|&v| v as f32).collect();
            let id = replace_take(&mut s, t, samples, None, Some(start), from)?;
            eprintln!("{tname}: new take {id}");
        }
    }

    // 3. Every chain printed, then the master's.
    let cache = dir.join("prints");
    for t in 0..s.tracks.len() {
        let (Some(sig), Some((start, lane, lane_r))) =
            (s.chain_signature(t), s.tracks[t].lane_lr())
        else {
            continue;
        };
        let tr = &s.tracks[t];
        let slots: Vec<Slot> = tr.inserts.iter().filter(|x| !x.bypass).cloned().collect();
        let stereo = lane_r.is_some();
        let job = Job::spawn(
            config.clone(),
            slots,
            s.sidechains(t),
            lane,
            lane_r,
            rate,
            Some(cache.clone()),
        );
        let name = tr.name.clone();
        let lane_sig = tr.source_signature();
        let t0 = Instant::now();
        let prints = wait_print(&job, &name)?;
        let p = printed(prints, sig.clone(), lane_sig, start, stereo)?;
        for i in 0..s.tracks.len() {
            if s.chain_signature(i).as_deref() == Some(sig.as_str()) {
                s.tracks[i].printed = Some(p.clone());
            }
        }
        eprintln!("{name}: printed ({:.0} s)", t0.elapsed().as_secs_f64());
    }
    if let Some(sig) = s.master_signature() {
        let (start, l, r) = s.master_input().ok_or("nothing to print on the master")?;
        let slots: Vec<Slot> = s
            .master_inserts
            .iter()
            .filter(|x| !x.bypass)
            .cloned()
            .collect();
        let sides = vec![None; slots.len()];
        let job = Job::spawn(config.clone(), slots, sides, l, Some(r), rate, Some(cache));
        let t0 = Instant::now();
        let prints = wait_print(&job, "Master")?;
        s.master_printed = Some(printed(prints, sig, s.master_mix_signature(), start, true)?);
        eprintln!("Master: printed ({:.0} s)", t0.elapsed().as_secs_f64());
    }
    s.save()?;

    // 4. The export.
    if let Some(name) = export {
        let problems = s.export_problems(false);
        if !problems.is_empty() {
            return Err(format!("can't export: {}", problems.join("; ")));
        }
        let md = s.mixdown();
        let mut record = s.export_record();
        record["final"] = json!(false);
        let path = dir.join("exports").join(format!("{name}.wav"));
        let peak = md.write(&path, false, &record)?;
        eprintln!("exported {} (peak {peak:+.2} dBFS)", path.display());
    }
    Ok(())
}
