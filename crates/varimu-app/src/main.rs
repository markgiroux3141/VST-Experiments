//! The native Vari-Mu app (docs/NATIVE_APP_PLAN.md): the schematic editor,
//! real-time play at draft-1x and production render, in one window.
//!
//! R0 (scaffold): the window, the studio look and the two views, empty.

// No console window in release builds (debug builds keep it for logs).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod theme;

use eframe::egui;

fn main() -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("Vari-Mu")
            .with_inner_size([1280.0, 800.0])
            .with_min_inner_size([640.0, 400.0]),
        ..Default::default()
    };
    eframe::run_native(
        "Vari-Mu",
        options,
        Box::new(|cc| {
            theme::apply(&cc.egui_ctx);
            Ok(Box::new(App::default()))
        }),
    )
}

#[derive(Clone, Copy, PartialEq, Eq, Default)]
enum View {
    #[default]
    Editor,
    Play,
}

#[derive(Default)]
struct App {
    view: View,
}

impl eframe::App for App {
    fn ui(&mut self, ui: &mut egui::Ui, _frame: &mut eframe::Frame) {
        egui::Panel::top("bar")
            .frame(
                egui::Frame::NONE
                    .fill(theme::CHROME)
                    .inner_margin(egui::Margin::symmetric(12, 6)),
            )
            .show(ui, |ui| {
                ui.horizontal(|ui| {
                    ui.label(egui::RichText::new("VARI-MU").strong().color(theme::ACCENT));
                    ui.add_space(16.0);
                    ui.selectable_value(&mut self.view, View::Editor, "Editor");
                    ui.selectable_value(&mut self.view, View::Play, "Play");
                });
            });
        egui::CentralPanel::default()
            .frame(egui::Frame::NONE.fill(theme::CANVAS))
            .show(ui, |ui| match self.view {
                View::Editor => canvas_dots(ui),
                View::Play => {
                    ui.centered_and_justified(|ui| {
                        ui.label(egui::RichText::new("Play: R2").color(theme::FAINT));
                    });
                }
            });
    }
}

/// The editor canvas's dot grid, at a fixed spacing until the editor has a
/// camera (R3).
fn canvas_dots(ui: &mut egui::Ui) {
    let rect = ui.max_rect();
    let painter = ui.painter_at(rect);
    let step = 24.0;
    let mut y = rect.top() + step;
    while y < rect.bottom() {
        let mut x = rect.left() + step;
        while x < rect.right() {
            painter.circle_filled(egui::pos2(x, y), 1.0, theme::DOT);
            x += step;
        }
        y += step;
    }
}
