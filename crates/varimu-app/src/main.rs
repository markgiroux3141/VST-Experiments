//! The native Vari-Mu app (docs/NATIVE_APP_PLAN.md): the schematic editor,
//! real-time play at draft-1x and production render, in one window.
//!
//! R0 (scaffold): the window, the studio look and the two views. R2: the Play view
//! (`play_view`). R3: the Editor view (`editor_view`), its drawing heard through the
//! Play view's player. The rest is the library (`varimu_app`).

// No console window in release builds (debug builds keep it for logs).
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod editor_view;
mod play_view;
mod theme;

use std::path::{Path, PathBuf};

use eframe::egui;

fn main() -> eframe::Result {
    let args = match play_view::Args::parse(std::env::args()) {
        Ok(a) => a,
        Err(e) => {
            eprintln!(
                "{e}\nusage: varimu-app [FILE] [--play] [--device fairchild_670|pultec_eqp1a] [--input NAME [--channel N]] [--edit DRAWN_CIRCUIT]"
            );
            std::process::exit(2);
        }
    };
    varimu_app::player::raise_priority();
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
            Ok(Box::new(App::new(config_dir(), args)))
        }),
    )
}

/// The project's `config/` directory: `$VARIMU_CONFIG`, else the first `config/`
/// with a `sim_settings.yaml` above the working directory or the executable.
fn config_dir() -> PathBuf {
    if let Some(p) = std::env::var_os("VARIMU_CONFIG") {
        return PathBuf::from(p);
    }
    let starts = [
        std::env::current_dir().ok(),
        std::env::current_exe()
            .ok()
            .and_then(|p| p.parent().map(Path::to_path_buf)),
    ];
    for start in starts.into_iter().flatten() {
        for dir in start.ancestors() {
            let c = dir.join("config");
            if c.join("sim_settings.yaml").is_file() {
                return c;
            }
        }
    }
    PathBuf::from("config")
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum View {
    Editor,
    Play,
}

struct App {
    view: View,
    play: play_view::PlayView,
    editor: editor_view::EditorView,
}

impl App {
    fn new(config_dir: PathBuf, args: play_view::Args) -> App {
        let view = if args.edit.is_some() {
            View::Editor
        } else {
            View::Play
        };
        let name = args
            .edit
            .clone()
            .unwrap_or_else(|| "pultec_eqp1a_drawn".into());
        App {
            view,
            editor: editor_view::EditorView::new(&config_dir, &name),
            play: play_view::PlayView::new(config_dir, args),
        }
    }
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
                View::Editor => self.editor.ui(ui, &mut self.play),
                View::Play => {
                    self.editor.sync_player(&mut self.play);
                    self.play.ui(ui);
                }
            });
    }
}
