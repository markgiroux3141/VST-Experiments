//! Component versions (docs/COMPONENT_EDITOR_PLAN.md, C1): the same store and rules as
//! `varimu/devices/versions.py` (tests/test_versions.py).

use std::path::{Path, PathBuf};

use varimu_circuit::versions::{self, Ref};
use varimu_circuit::yaml::Value;
use varimu_circuit::{Cores, Library, build_ir, spec};

fn config() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config")
}

#[test]
fn every_saved_version_matches_the_lock() {
    let root = config().join("components");
    let lock = versions::read_lock(&root).unwrap();
    let names = versions::names(&root);
    assert!(!names.is_empty());
    assert_eq!(lock.keys().cloned().collect::<Vec<_>>(), names);
    for folder in &names {
        for v in versions::versions(&root, folder) {
            let r = Ref {
                name: folder.clone(),
                version: Some(v),
            };
            versions::read_text(&root, &r).unwrap();
        }
    }
}

/// A copy of the config tree whose component store can be changed.
fn scratch(tag: &str) -> PathBuf {
    let dir = std::env::temp_dir().join(format!("varimu_versions_{tag}_{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&dir);
    let src = config().join("components");
    for folder in versions::names(&src) {
        let to = dir.join("components").join(&folder);
        std::fs::create_dir_all(&to).unwrap();
        for v in versions::versions(&src, &folder) {
            let f = format!("{v}.yaml");
            std::fs::copy(src.join(&folder).join(&f), to.join(&f)).unwrap();
        }
    }
    std::fs::copy(
        src.join(versions::LOCK_NAME),
        dir.join("components").join(versions::LOCK_NAME),
    )
    .unwrap();
    dir
}

#[test]
fn a_version_edited_after_saving_is_refused() {
    let dir = scratch("edited");
    let p = dir.join("components/12ax7/1.yaml");
    let text = std::fs::read_to_string(&p).unwrap().replace("kp:", "kp:  ");
    std::fs::write(&p, text).unwrap();
    let err = Library::new(&dir).device("12AX7@1").unwrap_err().0;
    assert!(
        err.contains("12AX7@1") && err.contains("was edited after it was saved"),
        "{err}"
    );
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_bare_name_is_the_latest_version_and_line_ends_dont_matter() {
    let dir = scratch("latest");
    let p = dir.join("components/12ax7/1.yaml");
    let lf = std::fs::read_to_string(&p).unwrap().replace("\r\n", "\n");
    let crlf = lf.replace('\n', "\r\n");
    std::fs::write(&p, crlf).unwrap();
    let lib = Library::new(&dir);
    assert_eq!(lib.device("12AX7").unwrap(), lib.device("12ax7@1").unwrap());
    let err = lib.device("12AX7@2").unwrap_err().0;
    assert!(err.contains("12AX7@2 doesn't exist"), "{err}");
    let _ = std::fs::remove_dir_all(&dir);
}

#[test]
fn a_circuit_naming_no_version_is_refused() {
    let lib = Library::new(config());
    let c =
        spec::load_circuit(&spec::circuit_path(lib.config_dir(), "pultec_eqp1a").unwrap()).unwrap();
    let pinned = [("rectifier_tube".to_string(), Value::Str("6X4@1".into()))];
    spec::resolve(&c, &pinned)
        .and_then(|p| build_ir(&lib, &c, &p, Cores::Linear))
        .unwrap();
    let bare = [("rectifier_tube".to_string(), Value::Str("6X4".into()))];
    let err = spec::resolve(&c, &bare)
        .and_then(|p| build_ir(&lib, &c, &p, Cores::Linear))
        .unwrap_err()
        .0;
    assert!(
        err.contains("devices.V3")
            && err.contains("'6X4' names no version")
            && err.contains("6X4@1"),
        "{err}"
    );
}
