//! The native Vari-Mu app's library (docs/NATIVE_APP_PLAN.md): everything but the
//! window, so it can be tested on its own.
//!
//! R2 (player and render): `audio` (files in and out), `resample` (scipy's
//! `resample_poly`, bit for bit), `settings` (the qualities of `sim_settings.yaml`),
//! `live` (the real-time engine, `varimu/sim/live.py`'s port), `panel` (devices and
//! their knobs), `player` (the engine to an audio output).

pub mod audio;
pub mod live;
pub mod panel;
pub mod player;
pub mod render;
pub mod resample;
pub mod settings;
