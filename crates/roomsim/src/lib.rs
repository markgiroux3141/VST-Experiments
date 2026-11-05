//! Room acoustics on the GPU, each kernel with an f64 CPU reference (docs/ROOM_LOOP_PLAN.md
//! R9-R11; the project's first GPU code, wgpu, so it runs on any vendor and in the native
//! app later):
//!
//! - `rays`: ray tracing for the room's energy decay and the energy at each mic (the port of
//!   `varimu.rooms.polyroom.ray_decay`);
//! - `spectra`: the image sources' spectra (the early part of
//!   `varimu.rooms.shoebox.responses`);
//! - `fdtd`: the wave solver below a crossover (R10).
//!
//! Python reaches it as the module `roomsim` (feature "python", built by maturin like
//! circuitsim) through `varimu.rooms.gpu`, which picks the GPU or the CPU reference.

pub mod fdtd;
pub mod gpu;
pub mod rays;
pub mod spectra;

#[cfg(feature = "python")]
mod python;

pub const VERSION: &str = env!("CARGO_PKG_VERSION");
/// A hash of the crate's sources and shaders at build time (build.rs).
pub const SOURCE_HASH: &str = env!("ROOMSIM_SOURCE_HASH");
