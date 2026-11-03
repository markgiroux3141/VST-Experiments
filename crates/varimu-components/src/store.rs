//! Saving component versions: `config/components/<name>/<N>.yaml` and its sha256 line in
//! `versions.lock`, the same files `varimu/devices/versions.py`'s `save` writes (and
//! `varimu-circuit`'s `versions.rs` reads). The lock is written exactly as Python's
//! `write_lock` writes it, so the two writers never disagree on its bytes.

use std::collections::BTreeMap;
use std::path::Path;

use varimu_circuit::versions::{self, LOCK_NAME, Ref};

use crate::{Error, err};

/// Python's `versions._LOCK_HEADER`.
const LOCK_HEADER: &str = "\
# The sha256 of every saved component version (config/components/<name>/<N>.yaml),
# its text with LF line ends. A version never changes once saved: save the next one
# instead (varimu.devices.versions, docs/COMPONENT_EDITOR_PLAN.md C1).
";

/// The lock's text for `lock` ({folder: {version: sha256}}).
pub fn lock_text(lock: &BTreeMap<String, BTreeMap<u32, String>>) -> String {
    let mut out = String::from(LOCK_HEADER);
    for (folder, vs) in lock {
        out.push_str(&format!("{folder}:\n"));
        for (v, h) in vs {
            out.push_str(&format!("  {v}: {h}\n"));
        }
    }
    out
}

fn io(p: &Path, e: std::io::Error) -> Error {
    Error(format!("{}: {e}", p.display()))
}

/// A version's text without its leading comment lines (the header records the date).
pub fn body(text: &str) -> &str {
    let mut rest = text;
    while rest.starts_with('#') {
        rest = rest.split_once('\n').map_or("", |(_, r)| r);
    }
    rest
}

/// The latest saved version of `name` whose body equals `text`'s, if any.
pub fn unchanged(root: &Path, name: &str, text: &str) -> Result<Option<Ref>, Error> {
    let Some(&latest) = versions::versions(root, name).last() else {
        return Ok(None);
    };
    let r = Ref {
        name: name.to_string(),
        version: Some(latest),
    };
    let (r, old) = versions::read_text(root, &r)?;
    Ok((body(&old).replace("\r\n", "\n") == body(text).replace("\r\n", "\n")).then_some(r))
}

/// Saves `text` as component `name`'s next version and records it in versions.lock.
pub fn save(root: &Path, name: &str, text: &str) -> Result<Ref, Error> {
    let r = versions::parse(name)?;
    if r.version.is_some() {
        return err(format!(
            "save takes a component name, not a version ({name})"
        ));
    }
    let n = versions::versions(root, &r.name)
        .last()
        .copied()
        .unwrap_or(0)
        + 1;
    let folder = root.join(r.folder());
    std::fs::create_dir_all(&folder).map_err(|e| io(&folder, e))?;
    let lf = text.replace("\r\n", "\n");
    let path = folder.join(format!("{n}.yaml"));
    if path.exists() {
        return err(format!("{} exists already", path.display()));
    }
    let mut lock = versions::read_lock(root)?;
    lock.entry(r.folder())
        .or_default()
        .insert(n, versions::text_hash(&lf));
    std::fs::write(&path, &lf).map_err(|e| io(&path, e))?;
    let lp = root.join(LOCK_NAME);
    std::fs::write(&lp, lock_text(&lock)).map_err(|e| io(&lp, e))?;
    Ok(Ref {
        name: r.name,
        version: Some(n),
    })
}

/// Today's date (UTC) as YYYY-MM-DD, for a version's header.
pub fn today() -> String {
    let secs = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map_or(0, |d| d.as_secs());
    let days = (secs / 86_400) as i64;
    // Howard Hinnant's civil_from_days.
    let z = days + 719_468;
    let era = z.div_euclid(146_097);
    let doe = z.rem_euclid(146_097);
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + i64::from(m <= 2);
    format!("{y:04}-{m:02}-{d:02}")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_lock_reads_back_and_matches_the_repo_layout() {
        let root = Path::new(env!("CARGO_MANIFEST_DIR")).join("../../config/components");
        let lock = versions::read_lock(&root).unwrap();
        let text = std::fs::read_to_string(root.join(LOCK_NAME)).unwrap();
        assert_eq!(lock_text(&lock), text.replace("\r\n", "\n"));
    }

    #[test]
    fn body_drops_the_header() {
        assert_eq!(body("# a\n# b\nname: X\n"), "name: X\n");
        assert_eq!(body("name: X\n"), "name: X\n");
    }
}
