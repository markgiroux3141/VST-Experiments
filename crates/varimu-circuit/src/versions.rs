//! Component versions: `config/components/<name>/<N>.yaml`, never changed once saved.
//!
//! The Rust side of `varimu/devices/versions.py` (docs/COMPONENT_EDITOR_PLAN.md, C1),
//! same layout and rules: a version's text (line ends normalized to LF) must match the
//! sha256 recorded in `config/components/versions.lock`; references are `NAME@N`, a
//! bare `NAME` meaning the latest version; circuits must name a version
//! (`require_pinned`); names are case-insensitive (the folder is the lowercased name).
//! Saving versions stays Python's for now (`varimu fit-devices`).

use std::collections::BTreeMap;
use std::fmt;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use crate::Error;

pub const LOCK_NAME: &str = "versions.lock";

/// A component reference: a name and, when pinned, its version.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Ref {
    pub name: String,
    pub version: Option<u32>,
}

impl Ref {
    pub fn folder(&self) -> String {
        self.name.to_lowercase()
    }
}

impl fmt::Display for Ref {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self.version {
            Some(v) => write!(f, "{}@{v}", self.name),
            None => write!(f, "{}", self.name),
        }
    }
}

pub fn parse(r: &str) -> Result<Ref, Error> {
    let bad = || {
        Error(format!(
            "'{r}' is not a component reference (NAME or NAME@N, N >= 1)"
        ))
    };
    let t = r.trim();
    let (name, version) = match t.split_once('@') {
        Some((n, v)) => {
            let ok = !v.is_empty() && v.bytes().all(|b| b.is_ascii_digit()) && !v.starts_with('0');
            if !ok {
                return Err(bad());
            }
            (n, Some(v.parse::<u32>().map_err(|_| bad())?))
        }
        None => (t, None),
    };
    if name.is_empty() || name.chars().any(|c| c.is_whitespace() || c == '@') {
        return Err(bad());
    }
    Ok(Ref {
        name: name.to_string(),
        version,
    })
}

pub fn text_hash(text: &str) -> String {
    let digest = Sha256::digest(text.replace("\r\n", "\n").as_bytes());
    digest.iter().map(|b| format!("{b:02x}")).collect()
}

/// The saved versions of component `name`, ascending (empty when there is none).
pub fn versions(root: &Path, name: &str) -> Vec<u32> {
    let mut out: Vec<u32> = std::fs::read_dir(root.join(name.to_lowercase()))
        .into_iter()
        .flatten()
        .flatten()
        .filter_map(|e| {
            let f = e.file_name().to_string_lossy().into_owned();
            let n = f.strip_suffix(".yaml")?;
            (!n.is_empty() && !n.starts_with('0') && n.bytes().all(|b| b.is_ascii_digit()))
                .then(|| n.parse().ok())
                .flatten()
        })
        .collect();
    out.sort_unstable();
    out
}

/// Every component's folder name, sorted.
pub fn names(root: &Path) -> Vec<String> {
    let mut out: Vec<String> = std::fs::read_dir(root)
        .into_iter()
        .flatten()
        .flatten()
        .filter(|e| e.path().is_dir())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| !versions(root, n).is_empty())
        .collect();
    out.sort();
    out
}

/// `r` with its version filled in (the latest when it names none).
pub fn resolve(root: &Path, r: &Ref) -> Result<Ref, Error> {
    let have = versions(root, &r.name);
    let Some(&latest) = have.last() else {
        return Err(Error(format!(
            "no component '{}' in {} (run `uv run varimu fit-devices`)",
            r.name,
            root.display()
        )));
    };
    match r.version {
        None => Ok(Ref {
            name: r.name.clone(),
            version: Some(latest),
        }),
        Some(v) if have.contains(&v) => Ok(r.clone()),
        Some(_) => Err(Error(format!(
            "{r} doesn't exist: {} has versions {have:?}",
            r.name
        ))),
    }
}

/// `r` parsed, refused when it names no version (what a circuit must do).
pub fn require_pinned(root: &Path, r: &str) -> Result<Ref, Error> {
    let p = parse(r)?;
    if p.version.is_none() {
        let hint = resolve(root, &p)
            .map(|x| format!(", e.g. {x}"))
            .unwrap_or_default();
        return Err(Error(format!(
            "'{r}' names no version: a circuit pins one{hint}"
        )));
    }
    Ok(p)
}

pub fn path(root: &Path, r: &Ref) -> Result<PathBuf, Error> {
    let r = resolve(root, r)?;
    Ok(root
        .join(r.folder())
        .join(format!("{}.yaml", r.version.unwrap())))
}

/// {folder: {version: sha256}} from versions.lock (empty when there is none).
pub fn read_lock(root: &Path) -> Result<BTreeMap<String, BTreeMap<u32, String>>, Error> {
    let lock = root.join(LOCK_NAME);
    let mut out = BTreeMap::new();
    let Ok(text) = std::fs::read_to_string(&lock) else {
        return Ok(out);
    };
    let mut current: Option<String> = None;
    for (n, line) in text.lines().enumerate() {
        let t = line.split('#').next().unwrap_or("").trim_end();
        if t.is_empty() {
            continue;
        }
        let at = || Error(format!("{}:{}: ", lock.display(), n + 1));
        if !t.starts_with(' ') {
            let Some(name) = t.strip_suffix(':') else {
                return Err(Error(format!("{}expected '<name>:'", at().0)));
            };
            current = Some(name.trim().to_string());
            out.insert(name.trim().to_string(), BTreeMap::new());
            continue;
        }
        let (k, v) = t.trim().split_once(':').unwrap_or(("", ""));
        let v = v.trim();
        let version = k
            .parse::<u32>()
            .ok()
            .filter(|_| k.bytes().all(|b| b.is_ascii_digit()));
        let hex = v.len() == 64 && v.bytes().all(|b| matches!(b, b'0'..=b'9' | b'a'..=b'f'));
        match (&current, version) {
            (Some(c), Some(ver)) if hex => {
                out.get_mut(c).unwrap().insert(ver, v.to_string());
            }
            _ => return Err(Error(format!("{}expected '  <version>: <sha256>'", at().0))),
        }
    }
    Ok(out)
}

/// A version's text, checked against versions.lock.
pub fn read_text(root: &Path, r: &Ref) -> Result<(Ref, String), Error> {
    let r = resolve(root, r)?;
    let p = path(root, &r)?;
    let text = std::fs::read_to_string(&p).map_err(|e| Error(format!("{}: {e}", p.display())))?;
    let lock = read_lock(root)?;
    let want = lock
        .get(&r.folder())
        .and_then(|m| m.get(&r.version.unwrap()));
    match want {
        None => Err(Error(format!(
            "{r} ({}) isn't in {LOCK_NAME}: versions are saved with `varimu fit-devices`",
            p.display()
        ))),
        Some(h) if *h != text_hash(&text) => Err(Error(format!(
            "{r} ({}) was edited after it was saved (its sha256 no longer matches \
             {LOCK_NAME}); restore it and save the change as a new version",
            p.display()
        ))),
        Some(_) => Ok((r, text)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_references() {
        assert_eq!(
            parse("12AX7@1").unwrap(),
            Ref {
                name: "12AX7".into(),
                version: Some(1)
            }
        );
        assert_eq!(parse("6386").unwrap().version, None);
        for bad in [
            "", "@1", "12AX7@", "12AX7@0", "12AX7@01", "12AX7@x", "a b", "a@1@2",
        ] {
            assert!(parse(bad).is_err(), "{bad}");
        }
    }

    #[test]
    fn hashes_line_ends_alike() {
        assert_eq!(text_hash("a\r\nb\n"), text_hash("a\nb\n"));
        assert_eq!(
            text_hash(""),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        );
    }
}
