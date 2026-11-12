//! Scenario directories: `meta.json` (scalars) and raw little-endian f64 arrays
//! (`<name>.f64`), written by varimu/tape_particles; outputs go back the same way.

use std::path::Path;

use rustfft::num_complex::Complex64;
use serde_json::Value;

use crate::field::Kernels;

pub struct Meta(pub Value);

impl Meta {
    pub fn read(dir: &Path) -> Result<Self, String> {
        let s = std::fs::read_to_string(dir.join("meta.json"))
            .map_err(|e| format!("{}: {e}", dir.join("meta.json").display()))?;
        Ok(Meta(serde_json::from_str(&s).map_err(|e| e.to_string())?))
    }
    fn get(&self, k: &str) -> Result<&Value, String> {
        self.0.get(k).ok_or_else(|| format!("meta.json: no {k}"))
    }
    pub fn f64(&self, k: &str) -> Result<f64, String> {
        self.get(k)?.as_f64().ok_or_else(|| format!("meta.json: {k} not a number"))
    }
    pub fn usize(&self, k: &str) -> Result<usize, String> {
        Ok(self.f64(k)? as usize)
    }
    pub fn bool(&self, k: &str) -> Result<bool, String> {
        self.get(k)?.as_bool().ok_or_else(|| format!("meta.json: {k} not a bool"))
    }
    pub fn str(&self, k: &str) -> Result<String, String> {
        Ok(self.get(k)?.as_str().ok_or_else(|| format!("meta.json: {k} not a string"))?.to_string())
    }
    pub fn f64s(&self, k: &str) -> Result<Vec<f64>, String> {
        self.get(k)?
            .as_array()
            .ok_or_else(|| format!("meta.json: {k} not an array"))?
            .iter()
            .map(|v| v.as_f64().ok_or_else(|| format!("meta.json: {k}")))
            .collect()
    }
}

pub fn read_f64(dir: &Path, name: &str, len: usize) -> Result<Vec<f64>, String> {
    let p = dir.join(format!("{name}.f64"));
    let b = std::fs::read(&p).map_err(|e| format!("{}: {e}", p.display()))?;
    if b.len() != 8 * len {
        return Err(format!("{}: {} bytes, expected {}", p.display(), b.len(), 8 * len));
    }
    Ok(b.chunks_exact(8)
        .map(|c| f64::from_le_bytes(c.try_into().unwrap()))
        .collect())
}

pub fn write_f64(dir: &Path, name: &str, data: &[f64]) -> Result<(), String> {
    let mut b = Vec::with_capacity(8 * data.len());
    for v in data {
        b.extend_from_slice(&v.to_le_bytes());
    }
    let p = dir.join(format!("{name}.f64"));
    std::fs::write(&p, b).map_err(|e| format!("{}: {e}", p.display()))
}

/// `<pfx>_kept.f64` (the bins) and `<pfx>_k.f64` (4 x kept x layers x layers complex,
/// re / im interleaved).
pub fn read_kernels(dir: &Path, pfx: &str, layers: usize) -> Result<Kernels, String> {
    let p = dir.join(format!("{pfx}_kept.f64"));
    let nk = std::fs::metadata(&p).map_err(|e| format!("{}: {e}", p.display()))?.len() as usize / 8;
    let kept: Vec<usize> = read_f64(dir, &format!("{pfx}_kept"), nk)?
        .iter()
        .map(|&k| k as usize)
        .collect();
    let per = nk * layers * layers;
    let raw = read_f64(dir, &format!("{pfx}_k"), 4 * per * 2)?;
    let comp = |c: usize| -> Vec<Complex64> {
        (0..per)
            .map(|i| Complex64::new(raw[2 * (c * per + i)], raw[2 * (c * per + i) + 1]))
            .collect()
    };
    Ok(Kernels {
        kept,
        k: [comp(0), comp(1), comp(2), comp(3)],
    })
}
