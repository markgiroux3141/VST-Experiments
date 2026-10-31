//! The Session view (docs/RECORDING_PLAN.md). T1: the transport (play / stop, the
//! position as heard, tempo, meter, click, count-in, pre-roll, start bar), the latency
//! the player hears with, and the loopback calibration of an interface's round trip.
//!
//! The transport runs on the Play view's player: whatever device and source Play has
//! chosen keeps playing, and the click is mixed after it. The settings and the
//! calibrations are the user's (`%APPDATA%\varimu\session.json`, next to the app's
//! prefs), kept apart from `app.json` so that file's other writers can't drop them.

use std::path::PathBuf;
use std::sync::mpsc::{self, Receiver};
use std::time::Duration;

use eframe::egui::{self, RichText};
use serde_json::{Value, json};
use varimu_app::loopback::{self, Analysis, Calibration, Run};
use varimu_app::player::{BLOCK, InputDevice, State, input_devices};
use varimu_app::transport::{ClickMode, Phase, TransportSettings};

use crate::play_view::PlayView;
use crate::theme;

/// How long a calibration plays the click (s).
const CALIBRATE_S: f64 = 8.0;

enum Calibrate {
    Idle,
    /// Capturing: the run, the input's label and where position 0 left the app.
    Running {
        run: Box<Run>,
        input: String,
        output: String,
        origin: Option<i64>,
    },
    Analysing {
        rx: Receiver<Result<Analysis, String>>,
        input: String,
        output: String,
    },
}

pub struct SessionView {
    settings: TransportSettings,
    inputs: Vec<InputDevice>,
    /// 0: the output's own mix (WASAPI loopback); i + 1: `inputs[i]`.
    cal_source: usize,
    cal_channel: usize,
    calibrate: Calibrate,
    calibrations: Vec<Calibration>,
    last: Option<(String, Analysis)>,
    error: Option<String>,
}

fn prefs_path() -> Option<PathBuf> {
    varimu_app::prefs::path().map(|p| p.with_file_name("session.json"))
}

impl SessionView {
    pub fn new() -> SessionView {
        let mut v = SessionView {
            settings: TransportSettings::default(),
            inputs: Vec::new(),
            cal_source: 0,
            cal_channel: 0,
            calibrate: Calibrate::Idle,
            calibrations: Vec::new(),
            last: None,
            error: None,
        };
        v.load();
        v
    }

    fn load(&mut self) {
        let Some(text) = prefs_path().and_then(|p| std::fs::read_to_string(p).ok()) else {
            return;
        };
        let v: Value = serde_json::from_str(&text).unwrap_or(Value::Null);
        let t = &v["transport"];
        let d = TransportSettings::default();
        let u = |k: &str, def: u32| t[k].as_u64().map_or(def, |x| x as u32);
        self.settings = TransportSettings {
            bpm: t["bpm"].as_f64().unwrap_or(d.bpm),
            beats_per_bar: u("beats_per_bar", d.beats_per_bar),
            beat_unit: u("beat_unit", d.beat_unit),
            click: t["click"]
                .as_str()
                .and_then(ClickMode::from_id)
                .unwrap_or(d.click),
            click_db: t["click_db"].as_f64().unwrap_or(d.click_db),
            count_in_bars: u("count_in_bars", d.count_in_bars),
            pre_roll_bars: u("pre_roll_bars", d.pre_roll_bars),
            start_bar: t["start_bar"].as_i64().unwrap_or(d.start_bar),
        }
        .clamped();
        self.calibrations = v["calibrations"]
            .as_array()
            .map(|a| {
                a.iter()
                    .filter_map(|c| {
                        Some(Calibration {
                            output: c["output"].as_str()?.to_string(),
                            input: c["input"].as_str()?.to_string(),
                            round_trip_s: c["round_trip_s"].as_f64()?,
                            cpal_round_trip_s: c["cpal_round_trip_s"].as_f64()?,
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
    }

    fn save(&mut self) {
        let Some(p) = prefs_path() else { return };
        let s = &self.settings;
        let cals: Vec<Value> = self
            .calibrations
            .iter()
            .map(|c| {
                json!({
                    "output": c.output,
                    "input": c.input,
                    "round_trip_s": c.round_trip_s,
                    "cpal_round_trip_s": c.cpal_round_trip_s,
                })
            })
            .collect();
        let v = json!({
            "transport": {
                "bpm": s.bpm,
                "beats_per_bar": s.beats_per_bar,
                "beat_unit": s.beat_unit,
                "click": s.click.id(),
                "click_db": s.click_db,
                "count_in_bars": s.count_in_bars,
                "pre_roll_bars": s.pre_roll_bars,
                "start_bar": s.start_bar,
            },
            "calibrations": cals,
        });
        let r = p
            .parent()
            .map_or(Ok(()), std::fs::create_dir_all)
            .and_then(|_| {
                std::fs::write(
                    &p,
                    serde_json::to_string_pretty(&v).unwrap_or_default() + "\n",
                )
            });
        if let Err(e) = r {
            self.error = Some(format!("{}: {e}", p.display()));
        }
    }

    pub fn ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        play.tick(ui.ctx());
        self.poll_calibration(play);
        // The transport's settings go to the player every frame (a restarted player
        // picks them up), except while a calibration plays its own.
        if matches!(self.calibrate, Calibrate::Idle)
            && let Some(p) = play.player()
        {
            p.set_transport(&self.settings);
        }
        egui::CentralPanel::default()
            .frame(
                egui::Frame::NONE
                    .fill(theme::CANVAS)
                    .inner_margin(egui::Margin::same(18)),
            )
            .show(ui, |ui| {
                egui::ScrollArea::vertical().show(ui, |ui| {
                    self.transport_ui(ui, play);
                    ui.add_space(14.0);
                    self.settings_ui(ui);
                    ui.add_space(18.0);
                    self.latency_ui(ui, play);
                    ui.add_space(18.0);
                    self.calibrate_ui(ui, play);
                    if let Some(e) = &self.error {
                        ui.add_space(8.0);
                        ui.colored_label(theme::FAULT, e);
                    }
                });
            });
        if play.player().is_some() || !matches!(self.calibrate, Calibrate::Idle) {
            ui.ctx().request_repaint_after(Duration::from_millis(33));
        }
    }

    fn heading(ui: &mut egui::Ui, text: &str) {
        ui.label(RichText::new(text).small().color(theme::FAINT));
        ui.add_space(4.0);
    }

    fn transport_ui(&mut self, ui: &mut egui::Ui, play: &mut PlayView) {
        Self::heading(ui, "TRANSPORT");
        let Some(p) = play.player() else {
            ui.horizontal(|ui| {
                let go = egui::Button::new(
                    RichText::new("▶  Start the device")
                        .strong()
                        .color(theme::ACCENT_INK),
                )
                .fill(theme::ACCENT)
                .min_size(egui::vec2(160.0, 30.0));
                if ui
                    .add(go)
                    .on_hover_text(
                        "Start what Play has chosen (device and source); the transport runs on it",
                    )
                    .clicked()
                {
                    play.start_device();
                }
                ui.label(RichText::new(play.listen_line()).color(theme::MUTED));
            });
            return;
        };
        let st = p.status();
        let t = &st.transport;
        let busy = !matches!(self.calibrate, Calibrate::Idle);
        ui.horizontal(|ui| {
            let ready = st.state == State::Playing && !busy;
            if t.running {
                if ui
                    .add_enabled(
                        !busy,
                        egui::Button::new("■  Stop").min_size(egui::vec2(96.0, 30.0)),
                    )
                    .clicked()
                {
                    p.transport_run(false);
                }
            } else {
                let go =
                    egui::Button::new(RichText::new("▶  Play").strong().color(theme::ACCENT_INK))
                        .fill(theme::ACCENT)
                        .min_size(egui::vec2(96.0, 30.0));
                if ui
                    .add_enabled(ready, go)
                    .on_hover_text("From the start bar, after the count-in and pre-roll")
                    .clicked()
                {
                    p.transport_run(true);
                }
            }
            ui.add_space(12.0);
            let label = t.grid.map_or("---.-.-".into(), |g| g.label(t.heard));
            ui.label(
                RichText::new(label)
                    .monospace()
                    .size(26.0)
                    .color(theme::INK),
            );
            ui.add_space(8.0);
            let (badge, colour) = match t.phase {
                Some(Phase::CountIn) => ("COUNT-IN", theme::WARN),
                Some(Phase::PreRoll) => ("PRE-ROLL", theme::WARN),
                Some(Phase::Rolling) => ("ROLLING", theme::OK),
                None => ("STOPPED", theme::FAINT),
            };
            ui.label(RichText::new(badge).strong().color(colour));
            ui.add_space(12.0);
            ui.label(
                RichText::new(format!(
                    "load {:.0}% · {} dropouts",
                    st.load * 100.0,
                    p.dropouts()
                ))
                .small()
                .color(theme::MUTED),
            );
        });
        ui.label(
            RichText::new(play.listen_line())
                .small()
                .color(theme::MUTED),
        );
    }

    fn settings_ui(&mut self, ui: &mut egui::Ui) {
        let before = self.settings.clone();
        let s = &mut self.settings;
        ui.horizontal_wrapped(|ui| {
            ui.add(
                egui::DragValue::new(&mut s.bpm)
                    .range(20.0..=400.0)
                    .speed(0.25)
                    .max_decimals(2)
                    .suffix(" bpm"),
            );
            ui.add_space(10.0);
            ui.add(egui::DragValue::new(&mut s.beats_per_bar).range(1..=16));
            ui.label("/");
            egui::ComboBox::from_id_salt("beat_unit")
                .width(48.0)
                .selected_text(s.beat_unit.to_string())
                .show_ui(ui, |ui| {
                    for u in [2, 4, 8, 16] {
                        ui.selectable_value(&mut s.beat_unit, u, u.to_string());
                    }
                });
            ui.add_space(16.0);
            ui.label("click");
            egui::ComboBox::from_id_salt("click_mode")
                .width(110.0)
                .selected_text(s.click.label())
                .show_ui(ui, |ui| {
                    for m in ClickMode::ALL {
                        ui.selectable_value(&mut s.click, m, m.label());
                    }
                });
            ui.add(
                egui::DragValue::new(&mut s.click_db)
                    .range(-60.0..=0.0)
                    .speed(0.25)
                    .suffix(" dBFS"),
            )
            .on_hover_text("The click's peak level (it is mixed after the device)");
        });
        ui.add_space(4.0);
        ui.horizontal_wrapped(|ui| {
            ui.label("count-in");
            ui.add(
                egui::DragValue::new(&mut s.count_in_bars)
                    .range(0..=4)
                    .suffix(" bars"),
            )
            .on_hover_text("Click only, before the pre-roll");
            ui.add_space(10.0);
            ui.label("pre-roll");
            ui.add(
                egui::DragValue::new(&mut s.pre_roll_bars)
                    .range(0..=16)
                    .suffix(" bars"),
            )
            .on_hover_text("The timeline plays; a take starts after it");
            ui.add_space(10.0);
            ui.label("start at bar");
            ui.add(egui::DragValue::new(&mut s.start_bar).range(1..=9999));
        });
        if self.settings != before {
            self.settings = self.settings.clone().clamped();
            self.save();
        }
    }

    fn latency_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        Self::heading(ui, "LATENCY");
        let Some(p) = play.player() else {
            ui.label(
                RichText::new("(while a device plays)")
                    .small()
                    .color(theme::MUTED),
            );
            return;
        };
        let st = p.status();
        let out = p.output_latency_s();
        let queue = p.queued_s();
        let block = BLOCK as f64 / p.rate as f64;
        let heard = out + queue;
        ui.label(format!(
            "output device {:.1} ms (cpal) · queue {:.1} ms · block {:.1} ms",
            out * 1e3,
            queue * 1e3,
            block * 1e3
        ));
        ui.label(
            RichText::new(format!(
                "the click and the device are heard {:.0} ms after they are computed; a key, about {:.0} ms after it is played",
                heard * 1e3,
                (heard + block * (1.0 + st.load)) * 1e3
            ))
            .small()
            .color(theme::MUTED),
        );
        let mine: Vec<&Calibration> = self
            .calibrations
            .iter()
            .filter(|c| c.output == st.device)
            .collect();
        for c in mine {
            ui.label(format!(
                "round trip via {}: {:.2} ms measured, {:.2} ms by cpal ({:+.2} ms)",
                c.input,
                c.round_trip_s * 1e3,
                c.cpal_round_trip_s * 1e3,
                (c.round_trip_s - c.cpal_round_trip_s) * 1e3
            ));
        }
    }

    fn calibrate_ui(&mut self, ui: &mut egui::Ui, play: &PlayView) {
        Self::heading(ui, "LOOPBACK CALIBRATION");
        ui.label(
            RichText::new(
                "Cable an output of the interface to one of its inputs (or take the output's own mix: \
                 digital, it leaves the converters out). The click plays for 8 s with the device muted, \
                 is captured and found: the round trip a recording is placed by.",
            )
            .small()
            .color(theme::MUTED),
        );
        ui.add_space(4.0);
        let idle = matches!(self.calibrate, Calibrate::Idle);
        ui.horizontal(|ui| {
            if self.inputs.is_empty() && ui.small_button("list inputs").clicked() {
                self.inputs = input_devices();
            }
            let label = |i: usize, inputs: &[InputDevice]| match i {
                0 => "the output's own mix (no cable)".to_string(),
                i => inputs
                    .get(i - 1)
                    .map_or("?".into(), |d| format!("{} ({} ch)", d.name, d.channels)),
            };
            ui.add_enabled_ui(idle, |ui| {
                egui::ComboBox::from_id_salt("cal_source")
                    .width(300.0)
                    .selected_text(label(self.cal_source, &self.inputs))
                    .show_ui(ui, |ui| {
                        for i in 0..=self.inputs.len() {
                            ui.selectable_value(&mut self.cal_source, i, label(i, &self.inputs));
                        }
                    });
                if let Some(d) = self
                    .cal_source
                    .checked_sub(1)
                    .and_then(|i| self.inputs.get(i))
                {
                    ui.label("ch");
                    let mut ch = self.cal_channel + 1;
                    ui.add(egui::DragValue::new(&mut ch).range(1..=d.channels as usize));
                    self.cal_channel = ch - 1;
                }
            });
            let can = idle
                && play
                    .player()
                    .is_some_and(|p| p.status().state == State::Playing);
            if ui
                .add_enabled(can, egui::Button::new("Calibrate"))
                .on_hover_text("Needs a device playing (Start the device above)")
                .clicked()
            {
                self.start_calibration(play);
            }
            if let Calibrate::Running { run, .. } = &self.calibrate {
                let f = (run.started.elapsed().as_secs_f64() / CALIBRATE_S).min(1.0) as f32;
                ui.add(egui::ProgressBar::new(f).desired_width(160.0));
            } else if matches!(self.calibrate, Calibrate::Analysing { .. }) {
                ui.spinner();
            }
        });
        if let Some((input, a)) = &self.last {
            let ok = a.found == a.scheduled && a.max_residual <= 1.0;
            ui.add_space(4.0);
            ui.colored_label(
                if ok { theme::OK } else { theme::WARN },
                format!(
                    "{input}: {} of {} clicks found · each within {:.3} samples of its line · drift {:+.1} ppm · downbeats {:+.2} samples",
                    a.found, a.scheduled, a.max_residual, a.drift_ppm, a.accent_minus_beat
                ),
            );
            if let (Some(rt), Some(c)) = (a.round_trip_s, a.cpal_round_trip_s) {
                ui.label(format!(
                    "round trip {:.2} ms measured, {:.2} ms by cpal ({:+.2} ms)",
                    rt * 1e3,
                    c * 1e3,
                    (rt - c) * 1e3
                ));
            }
        }
    }

    fn start_calibration(&mut self, play: &PlayView) {
        let Some(p) = play.player() else { return };
        let source = match self
            .cal_source
            .checked_sub(1)
            .and_then(|i| self.inputs.get(i))
        {
            None => loopback::Source::Output { device: None },
            Some(d) => loopback::Source::Input {
                device: Some(d.name.clone()),
                channel: self.cal_channel,
            },
        };
        match Run::start(&source) {
            Ok(run) => {
                p.set_compensation(false);
                p.set_output_db(-300.0);
                p.set_transport(&TransportSettings {
                    click: ClickMode::On,
                    click_db: -20.0,
                    count_in_bars: 0,
                    pre_roll_bars: 0,
                    ..self.settings.clone()
                });
                p.transport_run(true);
                self.calibrate = Calibrate::Running {
                    input: run.name().to_string(),
                    output: p.status().device,
                    run: Box::new(run),
                    origin: None,
                };
                self.error = None;
            }
            Err(e) => self.error = Some(e),
        }
    }

    fn poll_calibration(&mut self, play: &PlayView) {
        match std::mem::replace(&mut self.calibrate, Calibrate::Idle) {
            Calibrate::Idle => {}
            Calibrate::Running {
                run,
                input,
                output,
                mut origin,
            } => {
                let Some(p) = play.player() else {
                    self.error = Some("the device stopped during the calibration".into());
                    return;
                };
                run.note_output(p.output_clock());
                let st = p.status();
                origin = origin.or(st.transport.origin);
                if run.started.elapsed().as_secs_f64() < CALIBRATE_S {
                    self.calibrate = Calibrate::Running {
                        run,
                        input,
                        output,
                        origin,
                    };
                    return;
                }
                p.transport_run(false);
                play.apply_monitor();
                let (Some(grid), Some(origin)) = (st.transport.grid, origin) else {
                    self.error = Some("the transport didn't run".into());
                    return;
                };
                let captured = (*run).stop();
                let (rate, out_s) = (p.rate, p.output_latency_s());
                let (tx, rx) = mpsc::channel();
                std::thread::spawn(move || {
                    let r = captured.analyse(&grid, origin, rate, out_s).map(|(a, _)| a);
                    let _ = tx.send(r);
                });
                self.calibrate = Calibrate::Analysing { rx, input, output };
            }
            Calibrate::Analysing { rx, input, output } => match rx.try_recv() {
                Ok(Ok(a)) => {
                    if let (Some(rt), Some(c)) = (a.round_trip_s, a.cpal_round_trip_s)
                        && a.found > 0
                    {
                        self.calibrations
                            .retain(|x| !(x.output == output && x.input == input));
                        self.calibrations.push(Calibration {
                            output,
                            input: input.clone(),
                            round_trip_s: rt,
                            cpal_round_trip_s: c,
                        });
                        self.save();
                    }
                    self.last = Some((input, a));
                }
                Ok(Err(e)) => self.error = Some(e),
                Err(mpsc::TryRecvError::Empty) => {
                    self.calibrate = Calibrate::Analysing { rx, input, output };
                }
                Err(mpsc::TryRecvError::Disconnected) => {
                    self.error = Some("the analysis stopped".into());
                }
            },
        }
    }
}
