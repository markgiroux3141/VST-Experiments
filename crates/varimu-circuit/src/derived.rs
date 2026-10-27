//! Derived values: functions of the resolved parameters that a circuit file names under
//! `derived` (module + value names). Python looks each up in the named module; here the
//! modules are a table. Only `varimu.circuit.fairchild_670` exists (the 670's channel 2
//! lumped; its docstrings are the reference).

use crate::Error;
use crate::spec::Params;
use crate::yaml::Value;

const FAIRCHILD_670: &str = "varimu.circuit.fairchild_670";
/// The 6386 triodes of each bank (`BANK_TRIODES` in Python).
const BANK_TRIODES: usize = 4;

fn get(p: &Params, key: &str) -> Result<f64, Error> {
    p.get(key)
        .and_then(Value::as_f64)
        .ok_or_else(|| Error(format!("derived: parameter {key} is not a number")))
}

/// Derived value `name` of `module` for resolved parameters `p`.
pub fn derive(module: &str, name: &str, p: &Params) -> Result<Value, Error> {
    if module != FAIRCHILD_670 {
        return Err(Error(format!(
            "derived: unknown module {module} (the Rust builder knows {FAIRCHILD_670})"
        )));
    }
    Ok(match name {
        "ch2_6386_parallel" => {
            let per_side = get(p, "v6386_per_side")?.trunc() as i64;
            if per_side != BANK_TRIODES as i64 {
                return Err(Error(
                    "v6386_per_side: the banks are the drawing's four triodes each".into(),
                ));
            }
            Value::Int(2 * per_side)
        }
        "ch2_6386_cathode_ohm" => {
            let (b, rk, rp) = (
                get(p, "balance")?,
                get(p, "r103_r104_ohm")?,
                get(p, "r105_ohm")?,
            );
            let ka = rk + b * rp;
            let kb = rk + (1.0 - b) * rp;
            Value::Float(ka * kb / (ka + kb))
        }
        "ch2_6386_plate_ohm" => Value::Float(
            get(p, "r111_ohm")? + 0.5 * (get(p, "r107_r108_ohm")? + get(p, "t102_r_half_ohm")?),
        ),
        "ch2_12bh7_cathode_ohm" => {
            let (r34, r35) = (get(p, "r134_ohm")?, get(p, "r135_ohm")?);
            let r_fb = get(p, "r_fb_ohm")? / 2.0 + r34 * r35 / (r34 + r35);
            Value::Float(1.0 / (2.0 / get(p, "r124_r125_ohm")? + 1.0 / r_fb))
        }
        other => return Err(Error(format!("derived: {module} has no {other}"))),
    })
}
