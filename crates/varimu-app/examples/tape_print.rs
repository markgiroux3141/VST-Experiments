//! The session's tape deck from the command line (docs/PERIOD_GEAR_BACKLOG.md, PG1, MT6):
//! a session made from stems, its tracks assigned to the Ampex 300-4's tape tracks, and
//! the deck's print, as the Session view's Tape deck window makes it.
//!
//!     cargo run --release -p varimu-app --example tape_print -- --session DIR
//!         [--stems DIR --tracks "bass,guitar,lead vocal,harmonies" [--from S] [--seconds S]]
//!         [--rate 48000] [--no-noise] [--measure CHUNK_S] [--out DIR]
//!
//! Without a `session.json` in `--session`, the session is made: a track per stem named in
//! `--tracks` (`<stems>/<name>.wav`, in tape-track order: the first on tape track 1), each
//! imported as Import… does with normalizing off (cut to `--seconds` from `--from`), the
//! deck added with those tracks assigned and their record trims set from their lanes. Then
//! the deck prints (or finds its print in `<session>/prints/`) and the session is saved:
//! opened in the app, its tracks play their tape tracks.
//!
//! `--measure CHUNK_S`: not the session's print, a measurement (TAPE_SPEED_PLAN.md P3's on
//! the deck): the same input printed in pieces of CHUNK_S and as one run, each timed, both
//! written to `--out` (`pieces_tape<k>.wav`, `whole_tape<k>.wav`, `meta.json`) for
//! scripts/deck_pieces_study.py.

use std::path::PathBuf;
use std::sync::atomic::AtomicBool;

use serde_json::json;
use varimu_app::audio;
use varimu_app::deck::{self, Deck};
use varimu_app::render::{PRINT_PIECES, Pieces};
use varimu_app::session::{Session, Track};
use varimu_app::transport::TransportSettings;

/// A progress line on stderr every 2 %.
fn reporter() -> impl FnMut(f64) {
    let mut last = -1.0;
    move |f: f64| {
        if f - last >= 0.02 {
            last = f;
            eprint!(
                "
  {:.0} %   ",
                100.0 * f
            );
        }
    }
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1);
    let (mut dir, mut stems, mut tracks, mut out) = (None, None, None, None);
    let (mut from_s, mut seconds, mut rate) = (0.0f64, None::<f64>, 48_000u32);
    let (mut noise, mut measure) = (true, None::<f64>);
    while let Some(a) = args.next() {
        let mut val = || args.next().ok_or(format!("{a} needs a value"));
        match a.as_str() {
            "--session" => dir = Some(PathBuf::from(val()?)),
            "--stems" => stems = Some(PathBuf::from(val()?)),
            "--tracks" => tracks = Some(val()?),
            "--from" => from_s = val()?.parse().map_err(|e| format!("--from: {e}"))?,
            "--seconds" => seconds = Some(val()?.parse().map_err(|e| format!("--seconds: {e}"))?),
            "--rate" => rate = val()?.parse().map_err(|e| format!("--rate: {e}"))?,
            "--no-noise" => noise = false,
            "--measure" => measure = Some(val()?.parse().map_err(|e| format!("--measure: {e}"))?),
            "--out" => out = Some(PathBuf::from(val()?)),
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let dir = dir.ok_or("--session DIR")?;
    let repo = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..");
    let config = repo.join("config");
    let mut session = if dir.join("session.json").is_file() {
        Session::load(&dir)?
    } else {
        let stems = stems.ok_or("a new session needs --stems DIR")?;
        let names: Vec<String> = tracks
            .ok_or("a new session needs --tracks")?
            .split(',')
            .map(|s| s.trim().to_string())
            .collect();
        if names.len() > deck::TRACKS {
            return Err(format!(
                "{} tracks for {} tape tracks",
                names.len(),
                deck::TRACKS
            ));
        }
        let mut s = Session::new(dir.clone(), rate, TransportSettings::default());
        s.tracks.clear();
        let mut d = Deck {
            noise,
            ..Deck::default()
        };
        for (k, name) in names.iter().enumerate() {
            let path = stems.join(format!("{name}.wav"));
            eprintln!("importing {}", path.display());
            let mut ch = audio::load_channels(&path, rate)?;
            let a = ((from_s * rate as f64) as usize).min(ch[0].len());
            let b = seconds.map_or(ch[0].len(), |x| {
                (a + (x * rate as f64) as usize).min(ch[0].len())
            });
            for c in &mut ch {
                *c = c[a..b].to_vec();
            }
            let f32s = |x: &[f64]| x.iter().map(|&v| v as f32).collect::<Vec<f32>>();
            let (left, right) = (f32s(&ch[0]), ch.get(1).map(|r| f32s(r)));
            let mut t = Track::new(name);
            t.midi = false;
            s.tracks.push(t);
            let i = s.tracks.len() - 1;
            let from = json!({
                "device": format!("import of {name}.wav"),
                "import": {
                    "file": path.to_string_lossy(),
                    "rate": rate,
                    "normalize": "off",
                    "gain_db": 0.0,
                    "channels": if right.is_some() { 2 } else { 1 },
                    "from_s": from_s,
                    "samples": b - a,
                },
            });
            s.add_rendered_take(i, left, right, 0, from)?;
            d.tracks[k] = Some(s.tracks[i].id.clone());
            let (_, l, r) = s.tracks[i].clips_lr().ok_or("an empty stem")?;
            let m: Vec<f32> = match r {
                Some(r) => l.iter().zip(r.iter()).map(|(a, b)| 0.5 * (a + b)).collect(),
                None => l.to_vec(),
            };
            d.trims_db[k] = deck::trim_for(&m, rate);
            eprintln!(
                "  tape track {}: {name}, record trim {:+.1} dB",
                k + 1,
                d.trims_db[k]
            );
        }
        s.armed = None;
        s.deck = Some(d);
        s.save()?;
        s
    };
    let deck = session.deck.clone().ok_or("the session has no deck")?;
    let input = session
        .deck_input()
        .ok_or("no assigned track has a sound")?;
    let prep = deck::prepare(&config, &deck)?;
    let audio_s = input.len() as f64 / session.rate as f64;
    eprintln!(
        "{:.1} s of four tracks; settings tape_gpu {}, {} pieces at once",
        audio_s,
        prep.settings.tape_gpu,
        deck::piece_workers()
    );
    let no = AtomicBool::new(false);
    if let Some(chunk_s) = measure {
        let out = out.ok_or("--measure needs --out DIR")?;
        std::fs::create_dir_all(&out).map_err(|e| e.to_string())?;
        let cut = Pieces {
            chunk_s,
            ..PRINT_PIECES
        };
        let mut meta = json!({"rate": session.rate, "audio_s": audio_s, "pieces": {
            "chunk_s": cut.chunk_s, "warmup_s": cut.warmup_s, "fade_s": cut.fade_s,
            "workers": deck::piece_workers()}, "trims_db": deck.trims_db,
            "latency_s": deck::latency_s(&prep, &deck)?, "tape_gpu": prep.settings.tape_gpu,
            "runs": {}});
        for (name, p) in [("pieces", Some(cut)), ("whole", None)] {
            eprintln!("{name}:");
            let mut progress = reporter();
            let t0 = std::time::Instant::now();
            let (tape, _sync, _) = deck::print_uncached_with(
                &prep,
                &deck,
                &input,
                session.rate,
                p,
                &mut progress,
                &no,
            )?;
            let wall = t0.elapsed().as_secs_f64();
            eprintln!("\r  {wall:.0} s, {:.1}x real time", wall / audio_s);
            meta["runs"][name] = json!({"wall_s": wall, "x_real_time": wall / audio_s});
            for (k, t) in tape.iter().enumerate() {
                if let Some(a) = t {
                    let x: Vec<f64> = a.iter().map(|&v| v as f64).collect();
                    audio::write_wav(
                        &out.join(format!("{name}_tape{}.wav", k + 1)),
                        &x,
                        session.rate,
                    )?;
                }
            }
            std::fs::write(
                out.join("meta.json"),
                serde_json::to_string_pretty(&meta).unwrap(),
            )
            .map_err(|e| e.to_string())?;
        }
        return Ok(());
    }
    let mut progress = reporter();
    let t0 = std::time::Instant::now();
    let p = deck::print(
        &prep,
        &deck,
        &input,
        session.rate,
        Some(&session.dir.join("prints")),
        &mut progress,
        &no,
        true,
    )?;
    let wall = t0.elapsed().as_secs_f64();
    eprintln!(
        "\r  {} in {wall:.0} s ({:.1}x real time), key {}",
        if p.cached { "found" } else { "printed" },
        wall / audio_s,
        p.key
    );
    if let Some(o) = &out {
        std::fs::create_dir_all(o).map_err(|e| e.to_string())?;
        for (k, t) in p.tape.iter().enumerate() {
            if let Some(a) = t {
                let x: Vec<f64> = a.iter().map(|&v| v as f64).collect();
                audio::write_wav(&o.join(format!("tape{}.wav", k + 1)), &x, session.rate)?;
            }
        }
    }
    session.set_deck_print(p);
    for t in &session.tracks {
        eprintln!(
            "  {}: {}",
            t.name,
            if t.tape_playing().is_some() {
                "plays its tape track"
            } else {
                "plays its lane"
            }
        );
    }
    session.save()?;
    Ok(())
}
