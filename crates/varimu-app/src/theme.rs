//! The editor's dark "studio" look (docs/editor_mockups/direction_studio.png),
//! with the colours of the web editor's tokens (varimu/listen/editor.html).

use eframe::egui::{self, Color32, Stroke};

pub const BG: Color32 = Color32::from_rgb(0x0f, 0x11, 0x14);
pub const CHROME: Color32 = Color32::from_rgb(0x16, 0x19, 0x1d);
pub const CHROME2: Color32 = Color32::from_rgb(0x1c, 0x20, 0x25);
pub const CHROME3: Color32 = Color32::from_rgb(0x23, 0x28, 0x30);
pub const LINE: Color32 = Color32::from_rgb(0x2a, 0x2f, 0x36);
pub const INK: Color32 = Color32::from_rgb(0xe3, 0xe7, 0xec);
pub const MUTED: Color32 = Color32::from_rgb(0x8b, 0x95, 0xa1);
pub const FAINT: Color32 = Color32::from_rgb(0x5d, 0x66, 0x72);
pub const CANVAS: Color32 = Color32::from_rgb(0x12, 0x15, 0x19);
pub const DOT: Color32 = Color32::from_rgb(0x26, 0x2c, 0x34);
pub const ACCENT: Color32 = Color32::from_rgb(0xf0, 0xa2, 0x38);
pub const ACCENT_INK: Color32 = Color32::from_rgb(0x15, 0x12, 0x0c);
pub const FAULT: Color32 = Color32::from_rgb(0xff, 0x5d, 0x5d);
pub const WARN: Color32 = Color32::from_rgb(0xf0, 0xc0, 0x4a);
/// The schematic: parts, wires, part names, a highlighted net, frames, checks passing.
pub const PART: Color32 = Color32::from_rgb(0xd5, 0xdb, 0xe2);
pub const WIRE: Color32 = Color32::from_rgb(0x7f, 0x93, 0xa8);
pub const TEXT_PART: Color32 = Color32::from_rgb(0xc9, 0xd1, 0xda);
pub const NET: Color32 = Color32::from_rgb(0x3f, 0xd0, 0xc0);
pub const FRAME: Color32 = Color32::from_rgb(0x3a, 0x42, 0x4c);
pub const OK: Color32 = Color32::from_rgb(0x5f, 0xd0, 0x8a);

/// `c` at `a` of its opacity (CSS's color-mix with transparent).
pub fn alpha(c: Color32, a: f32) -> Color32 {
    Color32::from_rgba_unmultiplied(c.r(), c.g(), c.b(), (a * 255.0).round() as u8)
}

/// The web editor's font stacks where Windows has them: Segoe UI for text, Cascadia
/// Mono (else Consolas) for numbers and nodes, Segoe UI Symbol for the glyphs egui's
/// own fonts lack (arrows, dots, checks). Missing files keep egui's fonts.
fn fonts(ctx: &egui::Context) {
    let dir = std::env::var_os("WINDIR")
        .map_or_else(
            || std::path::PathBuf::from(r"C:\Windows"),
            std::path::PathBuf::from,
        )
        .join("Fonts");
    let load = |f: &str| std::fs::read(dir.join(f)).ok();
    let mut defs = egui::FontDefinitions::default();
    let mut add = |name: &str, files: &[&str], family: egui::FontFamily, first: bool| {
        let Some(bytes) = files.iter().find_map(|f| load(f)) else {
            return;
        };
        defs.font_data.insert(
            name.into(),
            std::sync::Arc::new(egui::FontData::from_owned(bytes)),
        );
        let list = defs.families.entry(family).or_default();
        if first {
            list.insert(0, name.into());
        } else {
            list.push(name.into());
        }
    };
    add("ui", &["segoeui.ttf"], egui::FontFamily::Proportional, true);
    add(
        "mono",
        &["CascadiaMono.ttf", "consola.ttf"],
        egui::FontFamily::Monospace,
        true,
    );
    add(
        "symbols",
        &["seguisym.ttf"],
        egui::FontFamily::Proportional,
        false,
    );
    add(
        "symbols_mono",
        &["seguisym.ttf"],
        egui::FontFamily::Monospace,
        false,
    );
    ctx.set_fonts(defs);
}

/// Dark mode only: the studio look has no light variant.
pub fn apply(ctx: &egui::Context) {
    fonts(ctx);
    ctx.set_theme(egui::ThemePreference::Dark);
    let mut v = egui::Visuals::dark();
    v.weak_text_color = Some(MUTED);
    v.panel_fill = CHROME;
    v.window_fill = CHROME2;
    v.window_stroke = Stroke::new(1.0, LINE);
    v.extreme_bg_color = BG;
    v.faint_bg_color = CHROME2;
    v.code_bg_color = CHROME3;
    v.warn_fg_color = WARN;
    v.error_fg_color = FAULT;
    v.hyperlink_color = ACCENT;
    v.selection.bg_fill = ACCENT;
    v.selection.stroke = Stroke::new(1.0, ACCENT_INK);
    let w = &mut v.widgets;
    w.noninteractive.bg_fill = CHROME;
    w.noninteractive.bg_stroke = Stroke::new(1.0, LINE);
    w.noninteractive.fg_stroke = Stroke::new(1.0, INK);
    for (state, fill) in [
        (&mut w.inactive, CHROME2),
        (&mut w.hovered, CHROME3),
        (&mut w.active, CHROME3),
        (&mut w.open, CHROME3),
    ] {
        state.bg_fill = fill;
        state.weak_bg_fill = fill;
        state.bg_stroke = Stroke::new(1.0, LINE);
        state.fg_stroke = Stroke::new(1.0, INK);
    }
    w.inactive.fg_stroke = Stroke::new(1.0, MUTED);
    w.hovered.bg_stroke = Stroke::new(1.0, FAINT);
    w.active.bg_stroke = Stroke::new(1.0, ACCENT);
    ctx.set_visuals_of(egui::Theme::Dark, v);
}
