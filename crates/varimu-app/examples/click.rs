//! The transport's click with a device playing (RECORDING_PLAN.md, T1's done-when): the
//! load with the click off and on, and a loopback capture of the output analysed for
//! where every click came back.
//!
//!     cargo run --release -p varimu-app --example click -- [--device tube_synth]
//!         [--file FILE] [--notes] [--for SECONDS] [--bpm B] [--meter 4] [--click-db G]
//!         [--buffer S] [--ab SECONDS]
//!         [--output NAME] [--loopback output | --loopback input [NAME] [--channel N]]
//!         [--save DIR]
//!
//! Without `--file` the device plays from silent keys (`--notes`: a note every quarter of a
//! second, so a synth works while the click runs). `--ab S` turns the click off and on
//! every S seconds and reports load and dropouts per condition. `--loopback output`
//! captures the output's own mix (`--output NAME`: play on that device, not the default;
//! a device nothing else plays into keeps other programs' sound out of the capture) (WASAPI loopback: digital); `--loopback input`
//! an input device (an output cabled to it). `--save DIR` writes the clicks found
//! (`clicks.csv`, `summary.json`), `--save-audio` the capture too (`capture.wav`: generated
//! audio, never committed; 115 MB for 10 minutes). With a loopback the device
//! is muted at the monitor (it still computes: its load counts) so the capture holds only
//! the click; `--hear-device` keeps it.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::{Duration, Instant};

use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::loopback::{self, Run};
use varimu_app::midi::{Keys, Wave};
use varimu_app::panel::{DEVICES, knobs, values};
use varimu_app::player::{INPUT_BUFFER_S, Player, Source, State};
use varimu_app::settings::Settings;
use varimu_app::transport::{ClickMode, TransportSettings};

fn num(s: Option<String>, what: &str) -> Result<f64, String> {
    s.ok_or(format!("{what} needs a value"))?
        .parse()
        .map_err(|e| format!("{what}: {e}"))
}

#[derive(Default)]
struct Tally {
    seconds: usize,
    load_sum: f64,
    worst: f64,
    dropouts: u64,
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1).peekable();
    let mut device = "tube_synth".to_string();
    let (mut file, mut notes, mut seconds) = (None::<String>, false, 30.0);
    let mut ts = TransportSettings::default();
    let (mut buffer, mut ab) = (None::<f64>, None::<f64>);
    let mut loop_src: Option<loopback::Source> = None;
    let mut save: Option<PathBuf> = None;
    let mut save_audio = false;
    let mut hear_device = false;
    let mut output: Option<String> = None;
    while let Some(a) = args.next() {
        match a.as_str() {
            "--device" => device = args.next().ok_or("--device needs a value")?,
            "--file" => file = Some(args.next().ok_or("--file needs a value")?),
            "--notes" => notes = true,
            "--hear-device" => hear_device = true,
            "--output" => output = Some(args.next().ok_or("--output needs a device name")?),
            "--for" => seconds = num(args.next(), &a)?,
            "--bpm" => ts.bpm = num(args.next(), &a)?,
            "--meter" => ts.beats_per_bar = num(args.next(), &a)? as u32,
            "--click-db" => ts.click_db = num(args.next(), &a)?,
            "--buffer" => buffer = Some(num(args.next(), &a)?),
            "--ab" => ab = Some(num(args.next(), &a)?),
            "--save-audio" => save_audio = true,
            "--save" => save = Some(PathBuf::from(args.next().ok_or("--save needs a dir")?)),
            "--loopback" => match args.next().as_deref() {
                Some("output") => loop_src = Some(loopback::Source::Output { device: None }),
                Some("input") => {
                    let name = match args.peek() {
                        Some(n) if !n.starts_with("--") => args.next(),
                        _ => None,
                    };
                    loop_src = Some(loopback::Source::Input {
                        device: name,
                        channel: 0,
                    });
                }
                _ => return Err("--loopback output | input [NAME]".into()),
            },
            "--channel" => {
                let c = num(args.next(), &a)? as usize;
                match &mut loop_src {
                    Some(loopback::Source::Input { channel, .. }) => *channel = c.max(1) - 1,
                    _ => return Err("--channel after --loopback input".into()),
                }
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    if let Some(loopback::Source::Output { device }) = &mut loop_src {
        device.clone_from(&output);
    }
    ts.count_in_bars = 0;
    ts = ts.clamped();
    let config = Path::new("config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("unknown device {device}"))?;
    let s = dev.play_settings(&Settings::load(config, dev.quality)?);
    let circuit = Circuit::load(config, dev.circuit, s.cores()?)?;
    let v = values(&knobs(dev, circuit.spec()));
    let keys = Arc::new(Keys::default());
    let (source, buffer) = match &file {
        Some(f) => (
            Source::Loop(audio::load(Path::new(f), s.sample_rate)?),
            buffer.unwrap_or(dev.ahead_s),
        ),
        None => {
            let feeds = varimu_app::panel::key_feeds(dev, circuit.spec())?;
            (
                Source::Keys(keys.clone(), Wave::Saw, feeds),
                buffer.unwrap_or(INPUT_BUFFER_S.max(0.05)),
            )
        }
    };
    varimu_app::player::raise_priority();
    let player = Player::start_on(output.as_deref(), source, v, circuit, s, 1.0, buffer)?;
    while player.status().state == State::Starting {
        std::thread::sleep(Duration::from_millis(20));
    }
    if let State::Failed(e) = player.status().state {
        return Err(e);
    }
    let rate = player.rate;
    if loop_src.is_some() && !hear_device {
        player.set_compensation(false);
        player.set_output_db(-300.0);
    }
    println!(
        "{} on {} at {rate} Hz · buffer {:.0} ms · {} bpm {}/{}",
        dev.label,
        player.status().device,
        buffer * 1000.0,
        ts.bpm,
        ts.beats_per_bar,
        ts.beat_unit
    );
    // A note every quarter second, two notes apart, while the run lasts.
    let playing = Arc::new(AtomicBool::new(true));
    let notes_thread = notes.then(|| {
        let (k, on) = (keys.clone(), playing.clone());
        std::thread::spawn(move || {
            let mut i = 0u8;
            while on.load(Ordering::Relaxed) {
                let n = 45 + (i % 12) * 2;
                k.message(&[0x90, n, 100]);
                std::thread::sleep(Duration::from_millis(200));
                k.message(&[0x80, n, 0]);
                std::thread::sleep(Duration::from_millis(50));
                i = i.wrapping_add(1);
            }
        })
    });
    // Let the device settle into playing before measuring.
    std::thread::sleep(Duration::from_secs(2));
    let run = match &loop_src {
        Some(src) => Some(Run::start(src)?),
        None => None,
    };
    if let Some(r) = &run {
        println!("capturing {}", r.name());
    }
    ts.click = ClickMode::On;
    player.set_transport(&ts);
    player.transport_run(true);
    let t0 = Instant::now();
    let (mut off, mut on) = (Tally::default(), Tally::default());
    let mut click_on = true;
    let mut last = Instant::now();
    let mut drops = player.dropouts();
    while t0.elapsed().as_secs_f64() < seconds {
        if let Some(r) = &run {
            r.note_output(player.output_clock());
        }
        std::thread::sleep(Duration::from_millis(3));
        if last.elapsed() < Duration::from_secs(1) {
            continue;
        }
        last = Instant::now();
        let st = player.status();
        if let State::Failed(e) = &st.state {
            return Err(e.clone());
        }
        let d = player.dropouts();
        let t = if click_on { &mut on } else { &mut off };
        t.seconds += 1;
        t.load_sum += st.load;
        t.worst = t.worst.max(st.load_max);
        t.dropouts += d - drops;
        drops = d;
        let label = st
            .transport
            .grid
            .map_or("-".into(), |g| g.label(st.transport.heard));
        println!(
            "{:4.0} s  {label}  click {:3}  load {:3.0}% (worst {:4.0}%)  dropouts {d}",
            t0.elapsed().as_secs_f64(),
            if click_on { "on" } else { "off" },
            st.load * 100.0,
            st.load_max * 100.0,
        );
        if let Some(p) = ab {
            let want = ((t0.elapsed().as_secs_f64() / p) as u64).is_multiple_of(2);
            if want != click_on {
                click_on = want;
                ts.click = if want { ClickMode::On } else { ClickMode::Off };
                player.set_transport(&ts);
            }
        }
    }
    playing.store(false, Ordering::Relaxed);
    if let Some(h) = notes_thread {
        let _ = h.join();
    }
    let st = player.status();
    for (name, t) in [("click on", &on), ("click off", &off)] {
        if t.seconds > 0 {
            println!(
                "{name}: {} s, load {:.1}% mean, worst block {:.0}%, {} dropouts",
                t.seconds,
                t.load_sum / t.seconds as f64 * 100.0,
                t.worst * 100.0,
                t.dropouts
            );
        }
    }
    let Some(run) = run else { return Ok(()) };
    let (grid, origin) = match (st.transport.grid, st.transport.origin) {
        (Some(g), Some(o)) => (g, o),
        _ => return Err("the transport didn't run".into()),
    };
    if ab.is_some() {
        println!("(the analysis expects the click on throughout: run it without --ab)");
    }
    let captured = run.stop();
    let (a, clicks) = captured.analyse(&grid, origin, rate, player.output_latency_s())?;
    let rec = captured.rec;
    drop(player);
    println!(
        "capture: {} at {} Hz, {:.1} s, {} samples lost",
        rec.name,
        rec.rate,
        rec.samples.len() as f64 / rec.rate as f64,
        rec.overflows
    );
    println!(
        "clicks: {} of {} found over {:.1} s; against one line per pitch: worst {:.3} samples, rms {:.3}; drift {:+.2} ppm; downbeats {:+.3} samples from the beats' line",
        a.found,
        a.scheduled,
        a.span_s,
        a.max_residual,
        a.rms_residual,
        a.drift_ppm,
        a.accent_minus_beat
    );
    if let (Some(rt), Some(c)) = (a.round_trip_s, a.cpal_round_trip_s) {
        println!(
            "round trip (output callback to input callback): loopback {:.2} ms, cpal {:.2} ms, difference {:+.2} ms",
            rt * 1e3,
            c * 1e3,
            (rt - c) * 1e3
        );
    }
    // Clicks missed under other programs' sound (louder than -40 dBFS around them), and
    // the rest.
    let masked = clicks
        .iter()
        .filter(|c| c.found.is_none() && c.background_dbfs > -40.0)
        .count();
    if a.found < a.scheduled {
        println!(
            "missed: {masked} under other sound (> -40 dBFS around them), {} otherwise",
            a.scheduled - a.found - masked
        );
    }
    let missed: Vec<String> = clicks
        .iter()
        .filter(|c| c.found.is_none())
        .take(10)
        .map(|c| format!("{} (score {:.2})", grid.label(c.position), c.score))
        .collect();
    if !missed.is_empty() {
        println!("missed (first 10): {}", missed.join(", "));
    }
    if let Some(dir) = save {
        std::fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
        if save_audio {
            let x: Vec<f64> = rec.samples.iter().map(|&v| v as f64).collect();
            audio::write_wav(&dir.join("capture.wav"), &x, rec.rate)?;
        }
        let ratio = rec.rate as f64 / rate as f64;
        let mut csv =
            String::from("position,label,accent,predicted,found,residual,score,background_dbfs\n");
        for c in &clicks {
            let d = if c.accent { a.accent_minus_beat } else { 0.0 };
            let res = c.found.map_or(String::new(), |f| {
                format!("{:.4}", f - (a.offset + d + c.position as f64 * ratio))
            });
            csv += &format!(
                "{},{},{},{:.3},{},{res},{:.4},{:.1}\n",
                c.position,
                grid.label(c.position),
                c.accent,
                c.predicted,
                c.found.map_or(String::new(), |f| format!("{f:.4}")),
                c.score,
                c.background_dbfs
            );
        }
        std::fs::write(dir.join("clicks.csv"), csv).map_err(|e| e.to_string())?;
        let summary = serde_json::json!({
            "device": dev.id,
            "capture": rec.name,
            "rate_out": rate,
            "rate_in": rec.rate,
            "bpm": ts.bpm,
            "seconds": seconds,
            "scheduled": a.scheduled,
            "found": a.found,
            "missed_under_other_sound": masked,
            "span_s": a.span_s,
            "max_residual_samples": a.max_residual,
            "rms_residual_samples": a.rms_residual,
            "drift_ppm": a.drift_ppm,
            "accent_minus_beat_samples": a.accent_minus_beat,
            "round_trip_s": a.round_trip_s,
            "cpal_round_trip_s": a.cpal_round_trip_s,
            "capture_samples_lost": rec.overflows,
            "click_on": {"seconds": on.seconds, "load_mean": on.load_sum / on.seconds.max(1) as f64, "worst_block": on.worst, "dropouts": on.dropouts},
            "click_off": {"seconds": off.seconds, "load_mean": off.load_sum / off.seconds.max(1) as f64, "worst_block": off.worst, "dropouts": off.dropouts},
        });
        std::fs::write(
            dir.join("summary.json"),
            serde_json::to_string_pretty(&summary).map_err(|e| e.to_string())? + "\n",
        )
        .map_err(|e| e.to_string())?;
        println!("saved to {}", dir.display());
    }
    Ok(())
}
