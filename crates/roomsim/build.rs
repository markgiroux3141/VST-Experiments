//! Embeds a hash of the crate's sources as `ROOMSIM_SOURCE_HASH` (`roomsim.SOURCE_HASH` in
//! Python), as circuitsim's build.rs does; `varimu.rooms.gpu` refuses a stale build.
//!
//! FNV-1a 64 over, for each file in sorted order of its path relative to the crate (`/`
//! separators): the path, a 0 byte, the file's bytes, a 0 byte. Files: `Cargo.toml`,
//! `src/**/*.rs` and `src/**/*.wgsl` (the shaders).

use std::fs;
use std::path::{Path, PathBuf};

fn sources(dir: &Path, out: &mut Vec<PathBuf>) {
    for entry in fs::read_dir(dir).expect("read src") {
        let path = entry.expect("dir entry").path();
        if path.is_dir() {
            sources(&path, out);
        } else if path.extension().is_some_and(|e| e == "rs" || e == "wgsl") {
            out.push(path);
        }
    }
}

fn main() {
    let root = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("manifest dir"));
    let mut files = vec![root.join("Cargo.toml")];
    sources(&root.join("src"), &mut files);
    let mut named: Vec<(String, PathBuf)> = files
        .into_iter()
        .map(|p| {
            let rel = p.strip_prefix(&root).expect("under the crate");
            let name = rel
                .components()
                .map(|c| c.as_os_str().to_string_lossy().into_owned())
                .collect::<Vec<_>>()
                .join("/");
            (name, p)
        })
        .collect();
    named.sort();
    let mut h: u64 = 0xcbf2_9ce4_8422_2325;
    let mut feed = |bytes: &[u8]| {
        for &b in bytes {
            h ^= u64::from(b);
            h = h.wrapping_mul(0x0000_0100_0000_01b3);
        }
    };
    for (name, path) in &named {
        feed(name.as_bytes());
        feed(&[0]);
        feed(&fs::read(path).expect("read source"));
        feed(&[0]);
        println!("cargo:rerun-if-changed={}", path.display());
    }
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rustc-env=ROOMSIM_SOURCE_HASH={h:016x}");
}
