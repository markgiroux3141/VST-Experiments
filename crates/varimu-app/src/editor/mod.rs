//! The schematic editor's logic (R3; the web editor's page logic in
//! `varimu/listen/editor/*.js`, ported): everything but the painting, so it can be driven
//! and tested without a window.
//!
//! - `eng`: numbers as the editor shows and steps them (eng.js);
//! - `geom`: topology edits: place, move with rubber-banding wires, rotate, mirror,
//!   delete, copy / paste, wires, segment dragging (geom.js);
//! - `edits`: value edits with their sources, shared parameters, undo history
//!   (edits.js);
//! - `analysis`: a drawing compiled, with its parameters (editor_api.py's `analyze`);
//! - `scene`: the drawing laid out: pins, boxes, texts, hit testing (view.js);
//! - `camera`: pan and zoom (camera.js);
//! - `session`: the editor's state, the tools, the inspector's edits, the checks
//!   (main.js, tools.js, inspector.js).
//!
//! The drawing format, the connectivity, the compile and the checks are
//! `varimu_circuit`'s (R3a).

pub mod analysis;
pub mod camera;
pub mod edits;
pub mod eng;
pub mod geom;
pub mod scene;
pub mod session;

pub use session::Editor;
