//! Tape at the particle level (docs/TAPE_PARTICLES.md): a study, not part of the tape model.
//!
//! - [`sw`]: the Stoner-Wohlfarth particle and its thermally activated switching (f64; the
//!   reference for the WGSL kernels and the port of `varimu/tape_particles/sw.py`).
//! - [`bench`] / [`gpu_bench`]: the interacting-particle bench (a periodic box of needles
//!   with dipolar interactions under one applied field history), f64 CPU and f32 GPU.
//! - [`medium`]: the strip recorded by the moving head (cell-averaged field, f64 CPU).
//! - [`strip`]: the moving head on non-interacting particles by cell, the coating's
//!   demagnetization as a static field per cell (f64 CPU, f32 GPU: `head.wgsl`).
//!
//! The binary `tpsim` runs a scenario directory written by `varimu/tape_particles`.

pub mod bench;
pub mod field;
pub mod gpu;
pub mod gpu_bench;
pub mod head;
pub mod io;
pub mod medium;
pub mod strip;
pub mod sw;
