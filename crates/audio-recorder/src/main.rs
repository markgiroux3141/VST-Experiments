//! Records what the computer plays into a WAV: pick an output device, Start, Stop.
//!
//! On Windows an input stream built on an *output* device is a WASAPI loopback of its
//! mix (cpal). WASAPI delivers nothing while nothing plays, so a silent output stream
//! runs on the same device during a recording: quiet stretches are recorded as silence
//! instead of dropped. Every channel is kept, as 32-bit float at the device's rate,
//! written to disk as it arrives (`recordings/` at the repo root, git-ignored).
//!
//! `cargo run --release -p audio-recorder` (`-- --for SECONDS` records the default output
//! without a window and prints where it went).

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicU64, Ordering};
use std::thread::JoinHandle;
use std::time::{Duration, Instant};

use cpal::traits::{DeviceTrait, HostTrait, StreamTrait};
use cpal::{FromSample, Sample, SizedSample};
use eframe::egui;

fn main() -> eframe::Result {
    let args: Vec<String> = std::env::args().collect();
    if let Some(i) = args.iter().position(|a| a == "--for") {
        let seconds: f64 = args.get(i + 1).and_then(|s| s.parse().ok()).unwrap_or(5.0);
        let result = Recording::start(None).and_then(|r| {
            std::thread::sleep(Duration::from_secs_f64(seconds));
            r.stop()
        });
        match result {
            Ok(f) => println!(
                "saved {} ({:.2} s, {} frames lost)",
                display(&f.path),
                f.seconds,
                f.dropped
            ),
            Err(e) => {
                eprintln!("{e}");
                std::process::exit(1);
            }
        }
        return Ok(());
    }
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Audio Recorder")
            .with_inner_size([460.0, 260.0])
            .with_min_inner_size([360.0, 220.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Audio Recorder",
        options,
        Box::new(|_| Ok(Box::new(App::new()))),
    )
}

/// Where recordings go: `recordings/` at the repo root.
fn recordings_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("recordings")
}

fn device_name(d: &cpal::Device) -> String {
    d.description()
        .map_or_else(|_| "?".to_string(), |x| x.name().to_string())
}

fn output_devices() -> Vec<String> {
    cpal::default_host()
        .output_devices()
        .into_iter()
        .flatten()
        .map(|d| device_name(&d))
        .collect()
}

struct Shared {
    stop: AtomicBool,
    /// The last block's peak (f32 bits), for the meter.
    peak: AtomicU32,
    /// Frames written to the file.
    frames: AtomicU64,
    /// Frames dropped because the writer fell behind.
    dropped: AtomicU64,
}

/// A recording in progress.
struct Recording {
    _capture: cpal::Stream,
    _keep_alive: Option<cpal::Stream>,
    shared: Arc<Shared>,
    writer: Option<JoinHandle<Result<(), String>>>,
    path: PathBuf,
    rate: u32,
    channels: u16,
    started: Instant,
}

impl Recording {
    fn start(device_label: Option<&str>) -> Result<Recording, String> {
        let host = cpal::default_host();
        let device = match device_label {
            None => host.default_output_device(),
            Some(n) => host
                .output_devices()
                .into_iter()
                .flatten()
                .find(|d| device_name(d) == n),
        }
        .ok_or("output device not found")?;
        let name = device_name(&device);
        let config = device
            .default_output_config()
            .map_err(|e| format!("{name}: {e}"))?;
        let rate = config.sample_rate();
        let channels = config.channels();
        let cfg: cpal::StreamConfig = config.config();

        let dir = recordings_dir();
        std::fs::create_dir_all(&dir).map_err(|e| format!("{}: {e}", dir.display()))?;
        let path = dir.join(format!("recording_{}.wav", timestamp()));
        let spec = hound::WavSpec {
            channels,
            sample_rate: rate,
            bits_per_sample: 32,
            sample_format: hound::SampleFormat::Float,
        };
        let mut wav = hound::WavWriter::create(&path, spec)
            .map_err(|e| format!("{}: {e}", path.display()))?;

        let shared = Arc::new(Shared {
            stop: AtomicBool::new(false),
            peak: AtomicU32::new(0),
            frames: AtomicU64::new(0),
            dropped: AtomicU64::new(0),
        });
        // Four seconds of headroom between the audio callback and the disk.
        let (producer, mut consumer) =
            rtrb::RingBuffer::<f32>::new(4 * rate as usize * channels as usize);

        use cpal::SampleFormat as F;
        let sh = shared.clone();
        let capture = match config.sample_format() {
            F::F32 => build::<f32>(&device, &cfg, producer, sh),
            F::F64 => build::<f64>(&device, &cfg, producer, sh),
            F::I16 => build::<i16>(&device, &cfg, producer, sh),
            F::I32 => build::<i32>(&device, &cfg, producer, sh),
            F::U16 => build::<u16>(&device, &cfg, producer, sh),
            f => return Err(format!("{name}: sample format {f} isn't supported")),
        }
        .map_err(|e| format!("{name}: {e}"))?;

        // Silence on the same output keeps the loopback delivering through quiet parts.
        let keep_alive = device
            .build_output_stream(
                cfg,
                |data: &mut [f32], _: &cpal::OutputCallbackInfo| data.fill(0.0),
                |e| eprintln!("keep-alive: {e}"),
                None,
            )
            .ok();
        if let Some(s) = &keep_alive {
            let _ = s.play();
        }
        capture.play().map_err(|e| format!("{name}: {e}"))?;

        let sh = shared.clone();
        let ch = channels as u64;
        let writer = std::thread::Builder::new()
            .name("wav writer".into())
            .spawn(move || {
                let mut drain = |wav: &mut hound::WavWriter<_>| -> Result<(), String> {
                    let n = consumer.slots();
                    if let Ok(chunk) = consumer.read_chunk(n) {
                        let (a, b) = chunk.as_slices();
                        for &x in a.iter().chain(b) {
                            wav.write_sample(x).map_err(|e| e.to_string())?;
                        }
                        chunk.commit_all();
                        sh.frames.fetch_add(n as u64 / ch, Ordering::Relaxed);
                    }
                    Ok(())
                };
                while !sh.stop.load(Ordering::Relaxed) {
                    drain(&mut wav)?;
                    std::thread::sleep(Duration::from_millis(10));
                }
                drain(&mut wav)?;
                wav.finalize().map_err(|e| e.to_string())
            })
            .map_err(|e| e.to_string())?;

        Ok(Recording {
            _capture: capture,
            _keep_alive: keep_alive,
            shared,
            writer: Some(writer),
            path,
            rate,
            channels,
            started: Instant::now(),
        })
    }

    /// Stop, flush and close the file.
    fn stop(mut self) -> Result<Finished, String> {
        // Stop the streams first so nothing arrives after the last drain.
        drop(self._keep_alive.take());
        let _ = self._capture.pause();
        self.shared.stop.store(true, Ordering::Relaxed);
        if let Some(w) = self.writer.take() {
            w.join().map_err(|_| "the writer panicked".to_string())??;
        }
        Ok(Finished {
            path: self.path.clone(),
            seconds: self.shared.frames.load(Ordering::Relaxed) as f64 / self.rate as f64,
            dropped: self.shared.dropped.load(Ordering::Relaxed),
        })
    }
}

impl Drop for Recording {
    fn drop(&mut self) {
        self.shared.stop.store(true, Ordering::Relaxed);
        if let Some(w) = self.writer.take() {
            let _ = w.join();
        }
    }
}

fn build<T: SizedSample>(
    device: &cpal::Device,
    config: &cpal::StreamConfig,
    mut ring: rtrb::Producer<f32>,
    shared: Arc<Shared>,
) -> Result<cpal::Stream, cpal::Error>
where
    f32: FromSample<T>,
{
    let channels = config.channels as usize;
    device.build_input_stream(
        *config,
        move |data: &[T], _: &cpal::InputCallbackInfo| {
            // Whole frames only, so the channels never slip.
            let fit = (ring.slots() / channels) * channels;
            let n = data.len().min(fit);
            if n < data.len() {
                shared
                    .dropped
                    .fetch_add(((data.len() - n) / channels) as u64, Ordering::Relaxed);
            }
            let mut peak = 0.0f32;
            if let Ok(mut chunk) = ring.write_chunk_uninit(n) {
                let (a, b) = chunk.as_mut_slices();
                for (d, &x) in a.iter_mut().chain(b.iter_mut()).zip(data) {
                    let v = f32::from_sample(x);
                    peak = peak.max(v.abs());
                    d.write(v);
                }
                // SAFETY: the chunk is `n` <= data.len() long and every slot was written.
                unsafe { chunk.commit_all() };
            }
            shared.peak.store(peak.to_bits(), Ordering::Relaxed);
        },
        |e| eprintln!("capture: {e}"),
        None,
    )
}

struct Finished {
    path: PathBuf,
    seconds: f64,
    dropped: u64,
}

struct App {
    devices: Vec<String>,
    /// None = the system's default output.
    device: Option<String>,
    recording: Option<Recording>,
    meter: f32,
    message: String,
}

impl App {
    fn new() -> App {
        App {
            devices: output_devices(),
            device: None,
            recording: None,
            meter: 0.0,
            message: format!("Saves to {}", display(&recordings_dir())),
        }
    }
}

fn display(p: &std::path::Path) -> String {
    std::fs::canonicalize(p)
        .unwrap_or_else(|_| p.to_path_buf())
        .display()
        .to_string()
        .trim_start_matches(r"\\?\")
        .to_string()
}

fn clock(seconds: f64) -> String {
    let s = seconds as u64;
    format!("{:02}:{:02}:{:02}", s / 3600, s / 60 % 60, s % 60)
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.inner_margin(egui::Margin::same(16)))
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label("Output");
                    ui.add_enabled_ui(self.recording.is_none(), |ui| {
                        egui::ComboBox::from_id_salt("device")
                            .width(280.0)
                            .selected_text(self.device.as_deref().unwrap_or("Default output"))
                            .show_ui(ui, |ui| {
                                ui.selectable_value(&mut self.device, None, "Default output");
                                for d in &self.devices {
                                    ui.selectable_value(&mut self.device, Some(d.clone()), d);
                                }
                            });
                        if ui.button("⟳").on_hover_text("Rescan devices").clicked() {
                            self.devices = output_devices();
                        }
                    });
                });
                ui.add_space(12.0);

                let big = egui::vec2(120.0, 40.0);
                ui.horizontal(|ui| match &self.recording {
                    None => {
                        let start = egui::Button::new(egui::RichText::new("● Start").size(18.0));
                        if ui.add_sized(big, start).clicked() {
                            match Recording::start(self.device.as_deref()) {
                                Ok(r) => {
                                    self.message = format!("Recording to {}", display(&r.path));
                                    self.recording = Some(r);
                                }
                                Err(e) => self.message = format!("Couldn't start: {e}"),
                            }
                        }
                    }
                    Some(r) => {
                        let stop = egui::Button::new(egui::RichText::new("■ Stop").size(18.0));
                        let clicked = ui.add_sized(big, stop).clicked();
                        ui.label(
                            egui::RichText::new(clock(r.started.elapsed().as_secs_f64()))
                                .size(22.0)
                                .monospace()
                                .color(egui::Color32::from_rgb(220, 70, 60)),
                        );
                        if clicked {
                            let r = self.recording.take().expect("recording");
                            self.message = match r.stop() {
                                Ok(f) => {
                                    let lost = if f.dropped > 0 {
                                        format!(" ({} frames lost)", f.dropped)
                                    } else {
                                        String::new()
                                    };
                                    format!(
                                        "Saved {} ({}){lost}",
                                        display(&f.path),
                                        clock(f.seconds)
                                    )
                                }
                                Err(e) => format!("Couldn't finish the file: {e}"),
                            };
                            self.meter = 0.0;
                        }
                    }
                });
                ui.add_space(12.0);

                if let Some(r) = &self.recording {
                    let peak = f32::from_bits(r.shared.peak.load(Ordering::Relaxed));
                    self.meter = peak.max(self.meter * 0.85);
                    let db = 20.0 * self.meter.max(1e-6).log10();
                    let fill = ((db + 60.0) / 60.0).clamp(0.0, 1.0);
                    ui.add(
                        egui::ProgressBar::new(fill)
                            .desired_height(10.0)
                            .text(format!("{db:.1} dBFS")),
                    );
                    ui.small(format!("{} Hz, {} ch, 32-bit float", r.rate, r.channels));
                    ui.ctx().request_repaint_after(Duration::from_millis(33));
                }
                ui.add_space(8.0);
                ui.horizontal_wrapped(|ui| {
                    ui.label(&self.message);
                });
                if self.recording.is_none() && ui.button("Open folder").clicked() {
                    let dir = recordings_dir();
                    let _ = std::fs::create_dir_all(&dir);
                    open_folder(&dir);
                }
            });
    }
}

fn open_folder(dir: &std::path::Path) {
    #[cfg(windows)]
    let _ = std::process::Command::new("explorer")
        .arg(display(dir))
        .spawn();
    #[cfg(target_os = "macos")]
    let _ = std::process::Command::new("open").arg(dir).spawn();
    #[cfg(all(unix, not(target_os = "macos")))]
    let _ = std::process::Command::new("xdg-open").arg(dir).spawn();
}

/// Local time as `YYYY-MM-DD_HH-MM-SS`.
#[cfg(windows)]
fn timestamp() -> String {
    // SAFETY: GetLocalTime only writes the struct it is given.
    let t = unsafe {
        let mut t = std::mem::zeroed::<windows_sys::Win32::Foundation::SYSTEMTIME>();
        windows_sys::Win32::System::SystemInformation::GetLocalTime(&mut t);
        t
    };
    format!(
        "{:04}-{:02}-{:02}_{:02}-{:02}-{:02}",
        t.wYear, t.wMonth, t.wDay, t.wHour, t.wMinute, t.wSecond
    )
}

/// UTC as `YYYY-MM-DD_HH-MM-SS` (no local-time source without a dependency).
#[cfg(not(windows))]
fn timestamp() -> String {
    let s = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs()) as i64;
    let (days, rem) = (s.div_euclid(86400), s.rem_euclid(86400));
    // Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z - era * 146097;
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!(
        "{y:04}-{m:02}-{d:02}_{:02}-{:02}-{:02}",
        rem / 3600,
        rem / 60 % 60,
        rem % 60
    )
}
