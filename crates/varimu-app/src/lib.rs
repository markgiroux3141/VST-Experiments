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
//!
//! Recording (docs/RECORDING_PLAN.md), T1: `transport` (the session's clock and click),
//! `loopback` (an output cabled back to an input: where the clicks come back, and the
//! round trip).
//!
//! The sampler: `sampler` (a kit of sounds, one per key of an octave, and its voices),
//! played through `player` like an instrument.
//!
//! Devices in the session (docs/SESSION_FX_PLAN.md), F1: `print` (a track's audio through
//! a device offline, kept as audio and cached by what it was made from).
//!
//! Components (docs/COMPONENT_EDITOR_PLAN.md C2 step 7): `components` (a transformer's
//! design edited, compiled, heard in a circuit that pins it, saved as a version).
//!
//! Editing (docs/SESSION_EDITING_PLAN.md SE8): `edit` (onsets, silences, zero crossings,
//! splices and varispeed for the Session view's clips).
//!
//! Rooms (docs/ROOM_LOOP_PLAN.md): `room` (a scene of sources and placed mics, rendered
//! into session tracks).

pub mod audio;
pub mod clav_proxy;
pub mod components;
pub mod edit;
pub mod editor;
pub mod live;
pub mod loop_render;
pub mod loopback;
pub mod midi;
pub mod monitor;
pub mod nickel;
pub mod panel;
pub mod performance;
pub mod player;
pub mod prefs;
pub mod print;
pub mod proxy;
pub mod render;
pub mod resample;
pub mod room;
pub mod sampler;
pub mod session;
pub mod settings;
pub mod take_render;
pub mod transport;
