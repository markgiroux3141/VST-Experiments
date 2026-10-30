//! The native Vari-Mu app's library (docs/NATIVE_APP_PLAN.md): everything but the
//! window, so it can be tested on its own.
//!
//! R2 (player and render): `audio` (files in and out), `resample` (scipy's
//! `resample_poly`, bit for bit), `settings` (the qualities of `sim_settings.yaml`),
//! `live` (the real-time engine, `varimu/sim/live.py`'s port), `panel` (devices and
//! their knobs), `player` (the engine to an audio output), `midi` (keyboards, and the
//! test oscillator they play into a device; the tube synth).
//!
//! R3 (the editor): `editor`, the schematic editor's logic (the web editor's page
//! logic, ported); the window paints it.

pub mod audio;
pub mod editor;
pub mod live;
pub mod midi;
pub mod monitor;
pub mod panel;
pub mod player;
pub mod prefs;
pub mod render;
pub mod resample;
pub mod settings;
