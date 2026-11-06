"""The Clavinet's live tier in Python: exactly what circuitsim's `clavinet.rs` does, from the
compiled strings (`varimu.clavinet.compile`), sample by sample (docs/CLAVINET_PLAN.md, CL3).
`note.play` is its reference (the full band, the exact projections).

**A voice** is one key's string, in one of three phases:

- **free** (released, or at rest): the released system's modes (halved: `compile`'s
  docstring), each a decaying rotation per internal sample; the pickups read through the
  released rows.
- **contact**: `note.py`'s `_ContactStepper` ported, the released modes stepped exactly
  for forces linear over a substep (first-order hold), the tangent's rubber
  (Hunt-Crossley) and the anvil (a spring and dashpot along its tilted normal) solved
  inside each substep with the rubber's sideways grip (its shear, stuck where it first
  touched; a 3x3 Newton on a forward-difference Jacobian), the contacts' forces at the
  run's start taken from its state. Two runs:
  - the **strike** (a key down): the tangent thrown up from `travel_m` below the string at
    the key's speed, pushed by the finger's force; it ends at a sample's end once both
    contacts have been closed `settle_s` and the run is `strike_window_s` old. While the
    tangent flies (no force since the run's start), a whole internal sample is stepped at
    once (the rotation and the tangent's parabola are exact without force); a sample
    that would end with the tangent past the string or the string on the anvil is
    stepped again in substeps, and every sample after it too. A key down while the
    string rings (free, or in a release) strikes it as it is.
  - the **release** (a key up; during the strike it waits for the strike's end): the
    held state, the press included, moved onto the released modes (`release`), the
    tangent where the held state has it, pulled away by the key's return force; it ends
    once both contacts have been open `open_s` and the run is `open_window_s` old.
  Either ends at `max_s`.
- **held**: `to_held` moves the state onto the held system's modes about the static
  press; its modes rotate; the pickups read through the held rows plus the static y.

The pickups' EMF each internal sample, per pickup: `h = clearance + sgn y` (y with the
press's static y while held) clipped into the table, `emf = -dL/dh(h) sgn vy`, the table
linear between its points. Modes above the internal rate's Nyquist frequency don't reach
the outputs in the free and held phases (`note.py`'s closed form drops them too); in the
contact runs every mode does (as `note.py`'s stepper).

**Aftertouch** (a pressure 0-127, every key): the hold force from the tuned one (0) to the
bend's largest (127); the held modes' frequencies scaled by the bend table's ratio
(2^(cents / 1200), linear in force between the table's points), their decay rates and
shapes kept: an approximation (the press's static shift and the held system's new shapes
are left out). It acts while a key is held.

**Sleep**: every `SLEEP_EVERY` internal samples of a free or held voice its EMF's bound
(each mode's |z| times its pickup velocity rows' |c| times the table's largest |dL/dh|) is
checked; under `sleep_v` the voice sleeps (its modes zeroed). A mode under `MODE_FLOOR`
is zeroed at the same checks.
"""

from __future__ import annotations

import math

import numpy as np

from varimu.clavinet.wear import Wear
from varimu.clavinet.wear import apply as apply_wear

SLEEP_EVERY = 1024
MODE_FLOOR = 1e-100
PICKUPS = ("centre", "bridge")


def phi12(x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(e^x - 1) / x and (e^x - 1 - x) / x^2 (harp.rs's phi12: their series to x^10 under
    |x| = 0.1)."""
    e1 = np.empty_like(x)
    e2 = np.empty_like(x)
    small = np.abs(x) < 0.1
    xs = x[small]
    p = np.ones_like(xs)
    s1 = np.zeros_like(xs)
    s2 = np.zeros_like(xs)
    fact = 1.0
    for n in range(11):
        fact *= n + 1
        s1 = s1 + p / fact
        s2 = s2 + p / (fact * (n + 2))
        p = p * xs
    e1[small], e2[small] = s1, s2
    xb = x[~small]
    em1 = np.exp(xb) - 1
    e1[~small] = em1 / xb
    e2[~small] = (em1 - xb) / (xb * xb)
    return e1, e2


def solve3(a: np.ndarray, b: list[float]) -> list[float]:
    """a x = b for a 3x3 a: Gaussian elimination with partial pivoting (clavinet.rs's)."""
    m = [[float(a[i, j]) for j in range(3)] + [float(b[i])] for i in range(3)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(c + 1, 3):
            f = m[r][c] / m[c][c]
            for k in range(c, 4):
                m[r][k] -= f * m[c][k]
    x = [0.0, 0.0, 0.0]
    for r in (2, 1, 0):
        x[r] = (m[r][3] - sum(m[r][k] * x[k] for k in range(r + 1, 3))) / m[r][r]
    return x


def substeps(fs_hz: float, k: int, contact_rate_hz: float) -> int:
    return max(1, math.ceil(contact_rate_hz / (fs_hz * k) - 1e-9))


def internal(fs_hz: float, rate_hz: float) -> int:
    return max(1, math.ceil(rate_hz / fs_hz - 1e-9))


class Voice:
    """One key's string (see the module docstring)."""

    def __init__(
        self, header: dict, kd: dict, arrays: dict[str, np.ndarray], fs_int: float, s: int
    ):
        self.kd = kd
        self.a = arrays
        self.fs = fs_int
        self.s = s
        self.h = 1.0 / (fs_int * s)
        self.num = header["contact"]
        self.sleep_v = header["sleep_v"]
        self.max_force = header["pressure"]["max_force_n"]
        self.c = kd["contact"]
        # a worn tangent's rubber (wear.py): the compression's difference under the hold force
        self.shift = self.c.get("hold_shift_m", 0.0)
        lam_r, lam_h = arrays["released.lam"], arrays["held.lam"]
        # a worn instrument's free rotations (wear.py; the contacts step lam_r)
        lam_f = arrays.get("released.lam_free", lam_r)
        self.lam_r, self.lam_h = lam_r, lam_h
        self.rot_r = np.exp(lam_f / fs_int)
        self.ratio = 1.0
        self._set_rot_h()
        nyq = np.pi * fs_int
        rr, hr = arrays["released.rows"], arrays["held.rows"]
        self.rows_contact = rr[4:]  # the pickups through every mode (note.py's stepper)
        self.rows_r = rr[4:] * (np.abs(lam_f.imag) < nyq)[None, :]
        self.rows_h = hr * (np.abs(lam_h.imag) < nyq)[None, :]
        # the contacts' substep
        x = lam_r * self.h
        e1, e2 = phi12(x)
        by, bx = arrays["released.b_y"], arrays["released.b_x"]
        self.phi = np.exp(x)
        e0h, e1h = (e1 - e2) * self.h, e2 * self.h
        self.g0y, self.g1y, self.g0x, self.g1x = by * e0h, by * e1h, bx * e0h, bx * e1h
        self.cy, self.cx, self.cvy, self.cvx = rr[0], rr[1], rr[2], rr[3]

        def re(c_, g):
            return float(np.sum(c_.real * g.real - c_.imag * g.imag))

        self.gyy, self.gyx = re(self.cy, self.g1y), re(self.cy, self.g1x)
        self.gxy, self.gxx = re(self.cx, self.g1y), re(self.cx, self.g1x)
        self.hyy, self.hyx = re(self.cvy, self.g1y), re(self.cvy, self.g1x)
        self.hxy, self.hxx = re(self.cvx, self.g1y), re(self.cvx, self.g1x)
        self.phi_sample = np.exp(lam_r / fs_int)
        # pickups
        npts = header["table_points"]
        self.pk = kd["pickups"]
        self.tab = {w: arrays[f"tables.{w}.dh"] for w in PICKUPS}
        self.step = {w: (self.pk[w]["h_hi_m"] - self.pk[w]["h_lo_m"]) / (npts - 1) for w in PICKUPS}
        self.static = kd["static_y_m"]
        self.bend_f = np.array(kd["bend"]["forces_n"])
        self.bend_c = np.array(kd["bend"]["cents"])
        # state
        self.phase = "free"
        self.z = np.zeros(lam_r.size, complex)
        self.asleep = True
        self.release_pending = False
        self.since_check = 0
        self.run: dict | None = None
        self.pressure = 0

    # --- events ---
    def _set_rot_h(self) -> None:
        lam = self.lam_h
        pair = np.abs(lam.imag) > 1e-12 * np.abs(lam)
        bent = np.where(pair, lam.real + 1j * lam.imag * self.ratio, lam)
        self.rot_h = np.exp(bent / self.fs)

    def set_pressure(self, value: int) -> None:
        self.pressure = value
        f0 = self.c["hold_force_n"]
        f = f0 + (self.max_force - f0) * value / 127.0
        cents = np.interp(f, self.bend_f, self.bend_c) - np.interp(f0, self.bend_f, self.bend_c)
        self.ratio = float(2.0 ** (cents / 1200.0))
        self._set_rot_h()

    def on(self, speed_m_s: float) -> None:
        if self.phase == "held":
            self.z = self._to_released()
        self.release_pending = False
        if self.asleep:
            self.z[:] = 0
        self.asleep = False
        self._start(-self.c["travel_m"], speed_m_s, self.c["hold_force_n"], "closed")

    def off(self) -> None:
        if self.phase == "contact" and self.run["until"] == "closed":
            self.release_pending = True
        elif self.phase == "held":
            self._release()

    def _to_released(self) -> np.ndarray:
        zh = self.z
        a = self.a
        return a["release.a"] @ zh + a["release.b"] @ zh.conj() + a["release.c"]

    def _release(self) -> None:
        t = self.a["held.tangent"]
        zt = float(np.sum(t[0].real * self.z.real - t[0].imag * self.z.imag))
        vt = float(np.sum(t[1].real * self.z.real - t[1].imag * self.z.imag))
        self.z = self._to_released()
        self.asleep = False
        zt0 = zt + self.kd["static_tangent_m"] - self.shift
        self._start(zt0, vt, -self.c["return_force_n"], "open")

    def _start(self, zt: float, vt: float, f_h: float, until: str) -> None:
        fr, fa = self._forces(zt, vt)
        c = self.c
        cs, sn = math.cos(c["tilt_rad"]), math.sin(c["tilt_rad"])
        z = self.z
        x_now = float(np.sum(self.cx.real * z.real - self.cx.imag * z.imag))
        vx_now = float(np.sum(self.cvx.real * z.real - self.cvx.imag * z.imag))
        # entering from the hold (the release), the grip carries the state's sideways force
        # about its anchor, x = 0
        fg = -c["grip_k_n_m"] * x_now - c["grip_c_ns_m"] * vx_now if fr > 0 else 0.0
        self.phase = "contact"
        self.run = {
            "zt": zt,
            "vt": vt,
            "f_h": f_h,
            "until": until,
            "fr": fr,
            "fa": fa,
            "fg": fg,
            "fy": fr - fa * cs,
            "fx": -fa * sn + fg,
            "x_stick": 0.0 if fr > 0 else None,
            "i": 0,
            "flight": until == "closed" and fr == 0.0 and fa == 0.0,
            "closed_since": None,
            "open_since": None,
        }

    def _forces(self, zt: float, vt: float) -> tuple[float, float]:
        """The contacts' forces at the state (note.py's `_forces`)."""
        c, z = self.c, self.z
        cs, sn = math.cos(c["tilt_rad"]), math.sin(c["tilt_rad"])

        def re(row):
            return float(np.sum(row.real * z.real - row.imag * z.imag))

        ya, xa, vya, vxa = re(self.cy), re(self.cx), re(self.cvy), re(self.cvx)
        dr, ddr = zt - ya, vt - vya
        fr = 0.0
        if dr > 0:
            fr = c["rubber_k"] * dr ** c["rubber_p"] * max(1 + c["rubber_alpha_s_m"] * ddr, 0.0)
        da, dda = cs * ya + sn * xa - c["anvil_gap_m"], cs * vya + sn * vxa
        fa = max(c["anvil_k_n_m"] * da + c["anvil_c_ns_m"] * dda, 0.0) if da > 0 else 0.0
        return fr, fa

    def _end_strike(self) -> None:
        st = self.run
        a = self.a
        z = self.z
        self.z = (
            a["to_held.a"] @ z
            + a["to_held.b"] @ z.conj()
            + a["to_held.t_z"] * (st["zt"] + self.shift)
            + a["to_held.t_v"] * st["vt"]
            + a["to_held.c"]
        )
        self.phase = "held"
        self.run = None
        self.since_check = 0
        if self.release_pending:
            self.release_pending = False
            self._release()

    # --- the contacts ---
    def _substeps(self, st: dict) -> None:
        """One internal sample of a contact run in `s` substeps (note.py's loop): the
        unknowns the rubber's push fr, the anvil's fa and the rubber's sideways grip fg
        (its shear about where it first touched), a 3x3 Newton on a forward-difference
        Jacobian."""
        c = self.c
        h = self.h
        cs, sn = math.cos(c["tilt_rad"]), math.sin(c["tilt_rad"])
        m_t, f_h = c["tangent_mass_kg"], st["f_h"]
        k_r, p_r, a_r = c["rubber_k"], c["rubber_p"], c["rubber_alpha_s_m"]
        k_a, c_a, gap = c["anvil_k_n_m"], c["anvil_c_ns_m"], c["anvil_gap_m"]
        k_g, c_g = c["grip_k_n_m"], c["grip_c_ns_m"]
        gyy, gyx, gxy, gxx = self.gyy, self.gyx, self.gxy, self.gxx
        hyy, hyx, hxy, hxx = self.hyy, self.hyx, self.hxy, self.hxx
        cz, cv = h * h / (6 * m_t), h / (2 * m_t)
        z = self.z
        zt, vt = st["zt"], st["vt"]
        fr_prev, fa_prev, fg_prev = st["fr"], st["fa"], st["fg"]
        fy_prev, fx_prev = st["fy"], st["fx"]
        x_stick = st["x_stick"]

        def re(row, v):
            return float(np.sum(row.real * v.real - row.imag * v.imag))

        for _ in range(self.s):
            zf = self.phi * z + self.g0y * fy_prev + self.g0x * fx_prev
            yf, xf = re(self.cy, zf), re(self.cx, zf)
            vyf, vxf = re(self.cvy, zf), re(self.cvx, zf)
            a_prev = (f_h - fr_prev) / m_t
            ztf = zt + h * vt + h * h * (2 * a_prev) / 6 + cz * f_h
            vtf = vt + h * a_prev / 2 + cv * f_h
            if x_stick is None and fr_prev > 0:
                x_stick = re(self.cx, z)

            def resid(f: list[float], x_stick=x_stick, xf=xf, yf=yf, vyf=vyf, vxf=vxf,
                      ztf=ztf, vtf=vtf) -> list[float]:  # fmt: skip
                fr_, fa_, fg_ = f
                fy_, fx_ = fr_ - fa_ * cs, -fa_ * sn + fg_
                ya_ = yf + gyy * fy_ + gyx * fx_
                xa_ = xf + gxy * fy_ + gxx * fx_
                vya_ = vyf + hyy * fy_ + hyx * fx_
                vxa_ = vxf + hxy * fy_ + hxx * fx_
                dr_, ddr_ = ztf - cz * fr_ - ya_, vtf - cv * fr_ - vya_
                da_, dda_ = cs * ya_ + sn * xa_ - gap, cs * vya_ + sn * vxa_
                frh = k_r * dr_**p_r * max(1 + a_r * ddr_, 0.0) if dr_ > 0 else 0.0
                fah = max(k_a * da_ + c_a * dda_, 0.0) if da_ > 0 else 0.0
                stick = x_stick if x_stick is not None else xa_
                fgh = -k_g * (xa_ - stick) - c_g * vxa_ if dr_ > 0 else 0.0
                return [fr_ - frh, fa_ - fah, fg_ - fgh]

            f = [fr_prev, fa_prev, fg_prev]
            for _ in range(40):
                r = resid(f)
                jac = np.empty((3, 3))
                for k in range(3):
                    d = 1e-7 * max(1.0, abs(f[k]))
                    fp = list(f)
                    fp[k] += d
                    rp = resid(fp)
                    for j in range(3):
                        jac[j, k] = (rp[j] - r[j]) / d
                step = solve3(jac, r)
                f_new = [max(f[0] - step[0], 0.0), max(f[1] - step[1], 0.0), f[2] - step[2]]
                done = all(abs(f_new[k] - f[k]) < 1e-10 * max(1.0, abs(f[k])) for k in range(3))
                f = f_new
                if done:
                    break
            fr, fa, fg = f
            if fr == 0.0:
                fg = 0.0
            fy, fx = fr - fa * cs, -fa * sn + fg
            z = zf + self.g1y * fy + self.g1x * fx
            zt, vt = ztf - cz * fr, vtf - cv * fr
            fr_prev, fa_prev, fg_prev, fy_prev, fx_prev = fr, fa, fg, fy, fx
            if fr == 0.0:
                x_stick = None
            st["i"] += 1
            t = st["i"] * h
            if fr > 0 and fa > 0:
                if st["closed_since"] is None:
                    st["closed_since"] = t
            else:
                st["closed_since"] = None
            if fr == 0 and fa == 0:
                if st["open_since"] is None:
                    st["open_since"] = t
            else:
                st["open_since"] = None
        self.z = z
        st.update(
            zt=zt, vt=vt, fr=fr_prev, fa=fa_prev, fg=fg_prev, fy=fy_prev, fx=fx_prev,
            x_stick=x_stick,
        )  # fmt: skip

    def _contact_sample(self) -> None:
        st = self.run
        if st["flight"]:
            # no force yet: a whole sample at once, unless it ends in contact
            hh = 1.0 / self.fs
            acc = st["f_h"] / self.c["tangent_mass_kg"]
            z1 = self.phi_sample * self.z
            zt1 = st["zt"] + hh * st["vt"] + 0.5 * acc * hh * hh
            ya = float(np.sum(self.cy.real * z1.real - self.cy.imag * z1.imag))
            xa = float(np.sum(self.cx.real * z1.real - self.cx.imag * z1.imag))
            cs, sn = math.cos(self.c["tilt_rad"]), math.sin(self.c["tilt_rad"])
            if zt1 - ya <= 0 and cs * ya + sn * xa - self.c["anvil_gap_m"] <= 0:
                if st["open_since"] is None:
                    st["open_since"] = (st["i"] + 1) * self.h
                self.z = z1
                st["zt"] = zt1
                st["vt"] = st["vt"] + acc * hh
                st["i"] += self.s
                return
            st["flight"] = False
        self._substeps(st)

    def _run_done(self) -> bool:
        st, num = self.run, self.num
        t = st["i"] * self.h
        if st["until"] == "closed":
            cl = st["closed_since"]
            if t >= num["strike_window_s"] and cl is not None and t - cl >= num["settle_s"]:
                return True
        else:
            op = st["open_since"]
            if t >= num["open_window_s"] and op is not None and t - op >= num["open_s"]:
                return True
        return st["i"] >= round(num["max_s"] / self.h)

    # --- rendering ---
    def _read(self, z: np.ndarray, rows: np.ndarray, static: bool) -> np.ndarray:
        """rows (4, m) on z (m,) or (m, t): the two pickups' EMF."""
        o = rows.real @ z.real - rows.imag @ z.imag
        out = []
        for j, w in enumerate(PICKUPS):
            pk = self.pk[w]
            y, vy = o[2 * j], o[2 * j + 1]
            if static:
                y = y + self.static[w]
            h = np.clip(pk["clearance_m"] + pk["sgn"] * y, pk["h_lo_m"], pk["h_hi_m"])
            tab = self.tab[w]
            u = (h - pk["h_lo_m"]) / self.step[w]
            i = np.minimum(np.floor(u), tab.size - 2).astype(int)
            f = u - i
            d = tab[i] + f * (tab[i + 1] - tab[i])
            out.append(-(d * pk["sgn"] * vy))
        return np.array(out)

    def _sleep_check(self) -> None:
        rows = self.rows_h if self.phase == "held" else self.rows_r
        az = np.abs(self.z)
        bound = 0.0
        for j, w in enumerate(PICKUPS):
            bound += float(az @ np.abs(rows[2 * j + 1])) * self.pk[w]["dmax_dh"]
        if bound < self.sleep_v:
            self.asleep = True
            self.z[:] = 0
        else:
            tiny = (np.abs(self.z.real) < MODE_FLOOR) & (np.abs(self.z.imag) < MODE_FLOOR)
            self.z[tiny] = 0

    def render(self, n: int) -> np.ndarray:
        """(2, n): the pickups' EMF over the next n internal samples."""
        out = np.zeros((2, n))
        i = 0
        while i < n:
            if self.phase == "contact":
                self._contact_sample()
                out[:, i] = self._read(self.z, self.rows_contact, False)
                i += 1
                if self._run_done():
                    if self.run["until"] == "closed":
                        self._end_strike()
                    else:
                        self.phase = "free"
                        self.run = None
                        self.since_check = 0
                continue
            if self.asleep:
                return out
            m = min(n - i, SLEEP_EVERY - self.since_check)
            held = self.phase == "held"
            rot = self.rot_h if held else self.rot_r
            rows = self.rows_h if held else self.rows_r
            # the rotations taken one by one (as Rust), the outputs vectorized
            zs = np.empty((self.z.size, m), complex)
            z = self.z
            for j in range(m):
                z = z * rot
                zs[:, j] = z
            self.z = z
            out[:, i : i + m] = self._read(zs, rows, held)
            i += m
            self.since_check += m
            if self.since_check >= SLEEP_EVERY:
                self.since_check = 0
                self._sleep_check()
        return out


class Strings:
    """Every key's voice at internal rate fs k with s contact substeps per internal
    sample, the instrument worn by `wear` (`varimu.clavinet.wear`; None: as compiled);
    events by MIDI note: ("on", note, velocity), ("off", note), ("pressure", value)."""

    def __init__(
        self,
        header: dict,
        arrays: dict[int, dict[str, np.ndarray]],
        fs_hz: float,
        rate_hz: float = 96000.0,
        contact_rate_hz: float = 96000.0 * 16,
        wear: Wear | None = None,
    ):
        header, arrays = apply_wear(header, arrays, wear)
        self.header = header
        self.k = internal(fs_hz, rate_hz)
        self.s = substeps(fs_hz, self.k, contact_rate_hz)
        fs_int = fs_hz * self.k
        self.voices = {
            kd["note"]: Voice(header, kd, arrays[kd["key"]], fs_int, self.s)
            for kd in header["keys"]
        }
        self.pressure = 0

    def speed(self, velocity: int) -> float:
        v = self.header["velocity"]
        vel = min(max(int(velocity), 1), 127)
        return v["lo_m_s"] + (v["hi_m_s"] - v["lo_m_s"]) * (vel - 1) / 126.0

    def event(self, ev: tuple) -> None:
        kind = ev[0]
        if kind == "on" and ev[2] == 0:
            ev, kind = ("off", ev[1]), "off"
        if kind == "on":
            v = self.voices.get(ev[1])
            if v is not None:
                v.on(self.speed(ev[2]))
        elif kind == "off":
            v = self.voices.get(ev[1])
            if v is not None:
                v.off()
        elif kind == "pressure":
            self.pressure = int(ev[1])
            for v in self.voices.values():
                v.set_pressure(self.pressure)

    def render(self, n: int, events: list[tuple[int, tuple]] = ()) -> np.ndarray:
        """(2, n) internal samples: events at offsets into them (in order), each applied
        before the sample at its offset (offsets past n after the last)."""
        out = np.zeros((2, n))
        evs = list(events)
        j = 0
        t = 0
        while True:
            while j < len(evs) and min(evs[j][0], n) <= t:
                self.event(evs[j][1])
                j += 1
            if t >= n:
                break
            end = min(evs[j][0], n) if j < len(evs) else n
            for v in self.voices.values():
                if v.asleep and v.phase != "contact":
                    continue
                out[:, t:end] += v.render(end - t)
            t = end
        return out


def play_note(
    header: dict,
    arrays: dict[int, dict[str, np.ndarray]],
    n: int,
    velocity_m_s: float,
    hold_s: float,
    tail_s: float,
    fs_hz: float = 96000.0,
    contact_rate_hz: float = 96000.0 * 16,
) -> np.ndarray:
    """Key n alone: struck at sample 0 at `velocity_m_s`, released after `hold_s` (as
    `note.play`: at the strike's end plus the rest of hold_s in whole samples), followed
    for `tail_s` from the release. (2, samples), from sample 1 on as `note.play`'s."""
    kd = next(k for k in header["keys"] if k["key"] == n)
    v = Voice(header, kd, arrays[n], fs_hz, substeps(fs_hz, 1, contact_rate_hz))
    v.on(velocity_m_s)
    chunks = []
    while v.phase == "contact":
        chunks.append(v.render(1))
    t_hold0 = len(chunks) / fs_hz
    chunks.append(v.render(max(int(round((hold_s - t_hold0) * fs_hz)), 0)))
    v.off()
    chunks.append(v.render(int(round(tail_s * fs_hz))))
    return np.hstack(chunks)
