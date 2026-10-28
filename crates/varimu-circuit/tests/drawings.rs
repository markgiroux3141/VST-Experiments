//! The drawn circuits (config/circuits/*.drawing.json) against the Python editor: read
//! and written back byte for byte (R3's done-when).

use std::path::{Path, PathBuf};

use varimu_circuit::drawing::Drawing;

fn drawings() -> Vec<PathBuf> {
    let dir = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/circuits");
    let mut v: Vec<PathBuf> = std::fs::read_dir(dir)
        .unwrap()
        .map(|e| e.unwrap().path())
        .filter(|p| p.to_string_lossy().ends_with(".drawing.json"))
        .collect();
    v.sort();
    v
}

#[test]
fn drawings_round_trip_byte_for_byte() {
    let paths = drawings();
    assert!(paths.len() >= 3, "{paths:?}");
    for p in paths {
        let text = std::fs::read_to_string(&p).unwrap();
        let d = Drawing::from_text(&text, &p.display().to_string()).unwrap();
        let back = d.to_text();
        if back != text {
            let line = text
                .lines()
                .zip(back.lines())
                .position(|(a, b)| a != b)
                .unwrap_or(0);
            panic!(
                "{}: differs at line {}: {:?} vs {:?}",
                p.display(),
                line + 1,
                text.lines().nth(line),
                back.lines().nth(line)
            );
        }
    }
}

/// Each drawn circuit's compiled file (config/circuits/<name>.yaml, written by the
/// Python editor) is the text the Rust compile writes.
#[test]
fn compiled_files_are_what_python_wrote() {
    use varimu_circuit::Library;
    use varimu_circuit::compile::{GENERATED_MARK, circuit_text, compile_drawing};
    let config = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config");
    let lib = Library::new(&config);
    for p in drawings() {
        let d = Drawing::from_text(&std::fs::read_to_string(&p).unwrap(), "drawing").unwrap();
        let yaml = p.to_string_lossy().replace(".drawing.json", ".yaml");
        let want = std::fs::read_to_string(&yaml).unwrap();
        // The header names where the drawing came from: take it from the file.
        let first = want.lines().next().unwrap();
        let origin = first
            .strip_prefix(&format!("# {GENERATED_MARK} "))
            .and_then(|r| r.split(" by the schematic editor").next())
            .unwrap();
        let got = circuit_text(&compile_drawing(&d, &lib), origin).unwrap();
        assert!(got == want, "{yaml}: the compiled text differs");
    }
}
