//! The player without the window, for measurements (NATIVE_APP_PLAN.md, R2's
//! done-when): a file's loop or live input through a device at draft-1x, out of the
//! default output, with a line of stats per second and a summary.
//!
//!     cargo run --release -p varimu-app --example play -- --device fairchild_670
//!         (--file FILE [--start S] [--seconds S] | --input [NAME] [--channel N]
//!          | --midi [NAME] [--wave saw|square])
//!         [--for SECONDS] [--buffer S] [--gain-db G] [--set KEY=VALUE ...] [--turn KEY=A,B]
//!
//! `--gain-db G` is the input gain (the Play view's normalization and trim).
//! `--record FILE` records live input for the run and saves the take (as the app does).
//! The process runs at high priority, as the app does (`--normal-priority`: not).
//! `--turn` switches a knob between two values every 2 s and reports how long each
//! change took to reach the output (`Status::knob_to_ear_s`). `--input` without a
//! name is the default input device; `--list-inputs` lists them.
//! `--midi` plays the device from a MIDI keyboard (the first port, or the first named
//! like NAME; `--list-midi` lists them): its keys play the test oscillator
//! (`midi::TestOsc`) into the device's input, and its mod wheel turns the device's
//! `mod_wheel` control over its range (the reactor filter's cutoff).

use std::path::Path;
use std::time::{Duration, Instant};

use varimu_app::audio;
use varimu_app::live::Circuit;
use varimu_app::midi::{self, Keyboard, MOD_WHEEL, Wave};
use varimu_app::panel::{DEVICES, Kind, knobs, values};
use varimu_app::player::{INPUT_BUFFER_S, Player, Source, State, input_devices};
use varimu_app::settings::Settings;
use varimu_circuit::yaml::Value;

fn value(s: &str) -> Value {
    if let Ok(i) = s.parse::<i64>() {
        Value::Int(i)
    } else if let Ok(x) = s.parse::<f64>() {
        Value::Float(x)
    } else {
        Value::Str(s.to_string())
    }
}

fn set(v: &mut Vec<(String, Value)>, key: &str, to: Value) {
    match v.iter_mut().find(|(k, _)| k == key) {
        Some(e) => e.1 = to,
        None => v.push((key.to_string(), to)),
    }
}

fn num(s: Option<String>, what: &str) -> Result<f64, String> {
    s.ok_or(format!("{what} needs a value"))?
        .parse()
        .map_err(|e| format!("{what}: {e}"))
}

fn main() -> Result<(), String> {
    let mut args = std::env::args().skip(1).peekable();
    let (mut device, mut file, mut input) = ("fairchild_670".to_string(), None, None);
    let (mut channel, mut seconds, mut start, mut excerpt) = (0usize, 30.0, 0.0, 8.0);
    let mut buffer: Option<f64> = None;
    let mut gain_db = 0.0;
    let mut sets = Vec::new();
    let mut turn: Option<(String, Value, Value)> = None;
    let mut normal_priority = false;
    let mut record: Option<String> = None;
    let (mut midi_name, mut wave): (Option<Option<String>>, Wave) = (None, Wave::Saw);
    while let Some(a) = args.next() {
        match a.as_str() {
            "--device" => device = args.next().ok_or("--device needs a value")?,
            "--file" => file = Some(args.next().ok_or("--file needs a value")?),
            "--input" => {
                let name = match args.peek() {
                    Some(n) if !n.starts_with("--") => args.next(),
                    _ => None,
                };
                input = Some(name);
            }
            "--midi" => {
                let name = match args.peek() {
                    Some(n) if !n.starts_with("--") => args.next(),
                    _ => None,
                };
                midi_name = Some(name);
            }
            "--wave" => {
                wave = match args.next().as_deref() {
                    Some("saw") => Wave::Saw,
                    Some("square") => Wave::Square,
                    _ => return Err("--wave saw|square".into()),
                }
            }
            "--list-midi" => {
                for p in midi::ports()? {
                    println!("{p}");
                }
                return Ok(());
            }
            "--channel" => channel = num(args.next(), &a)? as usize,
            "--for" => seconds = num(args.next(), &a)?,
            "--start" => start = num(args.next(), &a)?,
            "--seconds" => excerpt = num(args.next(), &a)?,
            "--buffer" => buffer = Some(num(args.next(), &a)?),
            "--gain-db" => gain_db = num(args.next(), &a)?,
            "--set" | "--turn" => {
                let kv = args.next().ok_or(format!("{a} needs KEY=VALUE"))?;
                let (k, v) = kv.split_once('=').ok_or(format!("{a} KEY=VALUE"))?;
                if a == "--set" {
                    sets.push((k.to_string(), value(v)));
                } else {
                    let (x, y) = v.split_once(',').ok_or("--turn KEY=A,B")?;
                    turn = Some((k.to_string(), value(x), value(y)));
                }
            }
            "--normal-priority" => normal_priority = true,
            "--record" => record = Some(args.next().ok_or("--record needs a file")?),
            "--list-inputs" => {
                for d in input_devices() {
                    println!("{} ({} ch, {} Hz)", d.name, d.channels, d.rate);
                }
                return Ok(());
            }
            _ => return Err(format!("unknown argument {a}")),
        }
    }
    let config = Path::new("config");
    let dev = DEVICES
        .iter()
        .find(|d| d.id == device)
        .ok_or(format!("unknown device {device}"))?;
    let s = dev.play_settings(&Settings::load(config, dev.quality)?);
    let circuit = Circuit::load(config, dev.circuit, s.cores()?)?;
    let panel = knobs(dev, circuit.spec());
    let mut v = values(&panel);
    for (k, x) in sets {
        set(&mut v, &k, x);
    }
    let keyboard = match &midi_name {
        Some(name) => Some(Keyboard::open(name.as_deref())?),
        None => None,
    };
    // The mod wheel's control and its range.
    let wheel = dev.mod_wheel.and_then(|key| {
        panel
            .iter()
            .find(|k| k.key == key)
            .and_then(|k| match k.kind {
                Kind::Range { min, max } => Some((key, min, max)),
                _ => None,
            })
    });
    let feeds = varimu_app::panel::key_feeds(dev, circuit.spec())?;
    let (source, buffer) = match (&file, input) {
        _ if keyboard.is_some() => {
            let kb = keyboard.as_ref().expect("a keyboard");
            (
                Source::Keys(kb.keys.clone(), wave, feeds),
                buffer.unwrap_or(INPUT_BUFFER_S),
            )
        }
        (Some(f), _) => {
            let x = audio::load(Path::new(f), s.sample_rate)?;
            let a = ((start * s.sample_rate as f64) as usize).min(x.len());
            let b = (a + (excerpt * s.sample_rate as f64) as usize).min(x.len());
            if b - a < s.sample_rate as usize / 10 {
                return Err(format!(
                    "{f} is {:.1} s long: --start {start} leaves less than 0.1 s",
                    x.len() as f64 / s.sample_rate as f64
                ));
            }
            (
                Source::Loop(x[a..b].to_vec()),
                buffer.unwrap_or(dev.ahead_s),
            )
        }
        (None, Some(name)) => (
            Source::Input {
                device: name,
                channel,
            },
            buffer.unwrap_or(INPUT_BUFFER_S),
        ),
        (None, None) => return Err("--file, --input or --midi".into()),
    };
    if !normal_priority {
        varimu_app::player::raise_priority();
    }
    let gain = 10f64.powf(gain_db / 20.0);
    let player = Player::start(source, v.clone(), circuit, s, gain, buffer)?;
    let t0 = Instant::now();
    while player.status().state == State::Starting {
        std::thread::sleep(Duration::from_millis(20));
    }
    if let State::Failed(e) = player.status().state {
        return Err(e);
    }
    let st = player.status();
    let input_name = st
        .input
        .as_deref()
        .map_or(String::new(), |i| format!(" · input {i}"));
    println!(
        "{} on {}{input_name} · buffer {:.0} ms · started in {:.1} s",
        dev.label,
        st.device,
        buffer * 1000.0,
        t0.elapsed().as_secs_f64()
    );
    if let Some(kb) = &keyboard {
        let w = wheel.map_or(String::new(), |(k, a, b)| {
            format!("; the mod wheel turns {k} from {a} to {b}")
        });
        println!("playing from {}{w}", kb.name);
    }
    if record.is_some() {
        player.record(true);
    }
    let t1 = Instant::now();
    let mut worst_load = 0.0f64;
    let (mut knob_times, mut latencies) = (Vec::new(), Vec::new());
    let (mut flip, mut last_turn, mut last_knob) = (false, Instant::now(), None);
    let (mut last_print, mut wheel_seen) = (Instant::now(), 0u64);
    while t1.elapsed().as_secs_f64() < seconds {
        std::thread::sleep(Duration::from_millis(20));
        if let (Some(kb), Some((key, a, b))) = (&keyboard, wheel) {
            let (cc, n) = kb.keys.cc(MOD_WHEEL);
            if n != wheel_seen {
                wheel_seen = n;
                set(&mut v, key, Value::Float(a + (b - a) * cc as f64 / 127.0));
                player.set(v.clone());
            }
        }
        if last_print.elapsed() < Duration::from_secs(1) {
            continue;
        }
        last_print = Instant::now();
        let st = player.status();
        if let State::Failed(e) = &st.state {
            return Err(e.clone());
        }
        worst_load = worst_load.max(st.load_max);
        if let Some(l) = st.latency_s {
            latencies.push(l);
        }
        if st.knob_to_ear_s != last_knob
            && let Some(k) = st.knob_to_ear_s
        {
            knob_times.push(k);
            last_knob = st.knob_to_ear_s;
        }
        let (over, skip) = player.input_losses();
        let live = st.latency_s.map_or(String::new(), |l| {
            format!(
                "  latency {:.1} ms  lost {over} / skipped {skip}",
                l * 1000.0
            )
        });
        let mut knob = st.knob_to_ear_s.map_or(String::new(), |k| {
            format!("  knob->ear {:.0} ms", k * 1000.0)
        });
        if let (Some(kb), Some((key, ..))) = (&keyboard, wheel) {
            let at = v
                .iter()
                .find(|(k, _)| k == key)
                .and_then(|(_, x)| x.as_f64());
            let note = kb
                .keys
                .sounding()
                .map_or("-".into(), |(n, vel)| format!("{n}/{vel}"));
            knob += &format!("  key {note}  {key} {:.1}", at.unwrap_or(f64::NAN));
        }
        println!(
            "{:5.0} s  load {:3.0}% (worst block {:4.0}%)  queued {:4.0} ms  dropouts {}  gain {:+5.1} dB  out {:6.1} dBFS{live}{knob}",
            t1.elapsed().as_secs_f64(),
            st.load * 100.0,
            st.load_max * 100.0,
            player.queued_s() * 1000.0,
            player.dropouts(),
            st.meter.gain_db,
            st.meter.out_dbfs,
        );
        if let Some((k, a, b)) = &turn
            && last_turn.elapsed() >= Duration::from_secs(2)
        {
            flip = !flip;
            set(&mut v, k, if flip { b.clone() } else { a.clone() });
            player.set(v.clone());
            last_turn = Instant::now();
        }
    }
    if let Some(path) = &record {
        player.record(false);
        let t = Instant::now();
        let take = loop {
            if let Some(t) = player.take() {
                break t;
            }
            if t.elapsed() > Duration::from_secs(2) {
                return Err("no take came back".into());
            }
            std::thread::sleep(Duration::from_millis(5));
        };
        audio::write_wav(Path::new(path), &take.samples, take.rate)?;
        println!(
            "take: {:.2} s at {} Hz -> {path}",
            take.samples.len() as f64 / take.rate as f64,
            take.rate
        );
    }
    let (over, skip) = player.input_losses();
    let mean = |x: &[f64]| x.iter().sum::<f64>() / x.len().max(1) as f64;
    let max = |x: &[f64]| x.iter().copied().fold(0.0, f64::max);
    println!(
        "summary: {:.0} s played, {} dropouts, worst block load {:.0}%, restarts {}",
        player.played_s(),
        player.dropouts(),
        worst_load * 100.0,
        player.status().restarts
    );
    if !latencies.is_empty() {
        println!(
            "live input: latency {:.1} ms mean, {:.1} ms max; input lost {over} samples, {skip} blocks skipped; output device {:.1} ms",
            mean(&latencies) * 1000.0,
            max(&latencies) * 1000.0,
            player.output_latency_s() * 1000.0
        );
    }
    if !knob_times.is_empty() {
        println!(
            "knob->ear: {} changes, {:.0} ms mean, {:.0} ms max",
            knob_times.len(),
            mean(&knob_times) * 1000.0,
            max(&knob_times) * 1000.0
        );
    }
    Ok(())
}
