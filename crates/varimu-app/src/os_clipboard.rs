//! Ctrl+V and files on the system clipboard, read from the OS.
//!
//! egui-winit turns Ctrl+V into `Event::Paste` only when the system clipboard holds text,
//! and drops the key otherwise (egui-winit 0.35, `on_keyboard_input`), so an app's own
//! clipboard (the Session view's clips, the roll's notes) never saw the press unless some
//! text happened to be copied. On Windows the key is read from the OS instead, one paste
//! per press; elsewhere egui's events. Files copied in Explorer (CF_HDROP) are listed so
//! Ctrl+V can bring them in as a drop does.

use std::path::PathBuf;

use eframe::egui;

/// Ctrl+V's state from frame to frame: [`PasteKey::pressed`] is true once per press.
/// Call it every frame (gate what it does, not the call), so the edge isn't stale.
#[derive(Debug, Default)]
pub struct PasteKey {
    down: bool,
}

impl PasteKey {
    /// Whether Ctrl+V went down since the last frame, with the window focused.
    pub fn pressed(&mut self, ctx: &egui::Context) -> bool {
        #[cfg(windows)]
        {
            let down = ctx.input(|i| i.focused) && win::ctrl_v_down();
            let edge = down && !self.down;
            self.down = down;
            edge
        }
        #[cfg(not(windows))]
        {
            let _ = &mut self.down;
            ctx.input(|i| {
                i.events.iter().any(|e| match e {
                    egui::Event::Paste(_) => true,
                    egui::Event::Key {
                        key: egui::Key::V,
                        pressed: true,
                        modifiers,
                        ..
                    } => modifiers.command,
                    _ => false,
                })
            })
        }
    }
}

/// The files on the system clipboard (copied in Explorer), in their order; none when it
/// holds anything else.
pub fn files() -> Vec<PathBuf> {
    #[cfg(windows)]
    {
        win::files()
    }
    #[cfg(not(windows))]
    {
        Vec::new()
    }
}

/// A number that changes whenever anything is copied to the system clipboard (0 where the
/// OS has none): what was copied last, the app's own clipboard or the system's.
pub fn sequence() -> u32 {
    #[cfg(windows)]
    {
        win::sequence()
    }
    #[cfg(not(windows))]
    {
        0
    }
}

#[cfg(windows)]
mod win {
    use std::ffi::OsString;
    use std::os::windows::ffi::OsStringExt;
    use std::path::PathBuf;

    use windows_sys::Win32::System::DataExchange::{
        CloseClipboard, GetClipboardData, GetClipboardSequenceNumber, IsClipboardFormatAvailable,
        OpenClipboard,
    };
    use windows_sys::Win32::UI::Input::KeyboardAndMouse::{GetAsyncKeyState, VK_CONTROL, VK_V};
    use windows_sys::Win32::UI::Shell::DragQueryFileW;

    /// The clipboard format of a file list (Ole's CF_HDROP).
    const CF_HDROP: u32 = 15;

    pub fn ctrl_v_down() -> bool {
        // The high bit: the key is down now.
        // SAFETY: GetAsyncKeyState takes a virtual-key code and has no other inputs.
        unsafe { GetAsyncKeyState(VK_CONTROL as i32) < 0 && GetAsyncKeyState(VK_V as i32) < 0 }
    }

    pub fn sequence() -> u32 {
        // SAFETY: no arguments; returns 0 without clipboard access.
        unsafe { GetClipboardSequenceNumber() }
    }

    pub fn files() -> Vec<PathBuf> {
        let mut out = Vec::new();
        // SAFETY: the clipboard is opened for this thread and closed before returning; the
        // HDROP handle is only read while it is open, and each path is read into a buffer
        // of the length DragQueryFileW reported (plus the terminating nul).
        unsafe {
            if IsClipboardFormatAvailable(CF_HDROP) == 0 {
                return out;
            }
            if OpenClipboard(std::ptr::null_mut()) == 0 {
                return out;
            }
            let h = GetClipboardData(CF_HDROP);
            if !h.is_null() {
                let n = DragQueryFileW(h, u32::MAX, std::ptr::null_mut(), 0);
                for k in 0..n {
                    let len = DragQueryFileW(h, k, std::ptr::null_mut(), 0);
                    if len == 0 {
                        continue;
                    }
                    let mut buf = vec![0u16; len as usize + 1];
                    let got = DragQueryFileW(h, k, buf.as_mut_ptr(), buf.len() as u32);
                    buf.truncate(got as usize);
                    out.push(PathBuf::from(OsString::from_wide(&buf)));
                }
            }
            CloseClipboard();
        }
        out
    }
}
