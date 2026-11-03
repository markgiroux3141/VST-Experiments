"""Hot-cathode gas thyratrons: a lumped plasma (HYBRID_PHYSICS_PLAN.md H1; the 884, 2D21).

A tetrode thyratron (the 2D21) is a device with pins (a, g2, g1, w, k) and four ports
relative to the cathode k: the anode, the shield grid, the control grid, and the plasma's
state w; a triode (the 884: `mu_g2` None) has pins (a, g, w, k) and three. The state is the
logarithm of the ion density in the tube, x = exp(V(w, k)) (dimensionless; 1 V = one
e-fold). The circuit puts a 1 F capacitor from w to k (the state node: its voltage
integrates dw/dt, as the lamp's thermal node does), and the w port's current is -dw/dt
(a current into pin w; the capacitor carries it back to k, so k's KCL sees only the
electrodes' currents). A DC operating point is the plasma's steady state.

The physics, lumped (the parameters are fitted to the RCA and Sylvania sheets by
`varimu.devices.thyratron_fit`; each one's role):

- **The grid's barrier.** Electrons leave the cathode through the control grid's apertures,
  where the grids and the anode set a saddle potential, the control voltage
  V_c = V_g1 + V_g2 / mu_g2 + V_a / mu_a (mu: the control ratios). Ions in the apertures
  raise it: phi = V_c + d y / (1 + y), y = v_x x / d, d = softplus(V_a - V_c): linearly in
  the density at first (v_x volts per unit x: the ions' space charge), up to the plasma's
  potential (~V_a) once the plasma screens the grid. The electrons must also reach the
  anode: phi is softly capped at V_a.
- **The electron supply.** The current through the barrier is space-charge limited,
  perveance * (1 + x / x_n) * (e_v softplus((phi - v0) / e_v))^1.5: a Maxwellian tail
  e^((phi - v0) / e_v) below the barrier's top v0, the 3/2 law above it, and ions
  neutralizing the cathode's space charge (doubling the supply at x = x_n). It is the anode
  current.
- **Ionization.** Each electron reaching the anode makes nu(V_a, x) ions per volt of k_ion
  (dx/dt = k_ion nu I_a + ...): single-step, linear in the excess energy above the gas's
  first ionization potential (v_ion: xenon 12.13 eV, argon 15.76 eV, NIST), and stepwise
  through its lowest metastable level (v_meta: xenon 8.315 eV, argon 11.548 eV), whose
  population grows with the plasma: c_meta (x / x_n) above v_meta. The stepwise term carries
  the dense arc and sets its drop; the single-step term the strike.
- **Losses.** Ambipolar diffusion to the walls (tau_diff) and ion collection by the negative
  grid, k_grid (sheath(V_g1))^p_grid, sheath = t_e softplus((v_float - V_g1) / t_e): the
  more negative the grid, the thicker its sheath and the faster it clears the plasma
  (deionization: the sheet's 35 us at -100 V, 75 us at -10 V).
- **Grid current.** Ions to the grid, q_s x k_grid(...) (q_s: the plasma's charge at
  x = 1), less electrons above the floating potential (the grid as a Langmuir probe: the
  electron current balances the ions' at v_float, grows as e^((V_g1 - v_float) / t_e) below
  the plasma potential and saturates above it), plus the leakage from the anode
  (g_leak).
- **A background.** s0 ion pairs (in x) per second from cosmic rays and photoemission keep
  x off zero (numerics; the floor is far below any density that matters).

What it does, as the sheets show it: below the control characteristic the ion balance has a
stable state (the grid's pre-conduction ion current, rising sharply near the strike); at the
characteristic that state meets the unstable one (a tangency: the strike) and the density
runs away until the plasma screens the grid; the arc's drop is set by the ion balance
(nearly flat in current); at low current the drop rises (negative resistance) and the grid
regains control (extinction); after the anode current stops the plasma decays at
1 / tau_diff + k_grid(V_g1) (deionization).

A tetrode's shield grid draws no current here (the sheets don't give it); it enters only
through mu_g2, fitted to the 2D21's control family at shield-grid volts 0, +2, +8 (its
negative curves have a second barrier at the shield grid, not modelled).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from varimu.devices.triode import num

PINS_TETRODE = ("a", "g2", "g1", "w", "k")
PINS_TRIODE = ("a", "g", "w", "k")
# The gases' first ionization potentials and lowest (metastable) excited levels (NIST
# Atomic Spectra Database, web: https://physics.nist.gov/PhysRefData/ASD/): xenon 6s[3/2]_2,
# argon 4s[3/2]_2.
XE_ION_EV = 12.1298
XE_META_EV = 8.3153
AR_ION_EV = 15.7596
AR_META_EV = 11.5484
# The state's range and the restoring rate past it (numerics only).
W_MIN, W_MAX = -80.0, 40.0
G_EXT_PER_S = 1e6


def softplus(z):
    """ln(1 + e^z), as numpy's logaddexp(0, z) (and Rust's fastmath) computes it."""
    return np.logaddexp(0.0, z)


def sigmoid(z):
    """d softplus / dz."""
    return 0.5 * (1.0 + np.tanh(0.5 * z))


@dataclass(frozen=True)
class Thyratron:
    name: str
    mu_a: float  # anode control ratio
    mu_g2: float | None  # shield-grid control ratio (None: a triode)
    v0_v: float  # the barrier's top relative to the control voltage
    e_v: float  # the barrier's tail energy (V)
    perveance: float  # A / V^1.5
    x_n: float  # density at which ions double the electron supply
    v_x_v: float  # barrier lowering per unit density (V)
    k_ion: float  # ionization rate per (V A) (1 / (V A s))
    v_ion_v: float  # single-step threshold (V)
    w_ion_v: float  # its softness (V)
    c_meta: float  # stepwise ionization, relative to single-step per unit x / x_n
    v_meta_v: float  # stepwise threshold (V)
    w_meta_v: float  # its softness (V)
    tau_diff_s: float  # ambipolar diffusion time
    k_grid: float  # grid ion collection (1 / (s V^p_grid))
    p_grid: float
    v_float_v: float  # grid floating potential in the arc
    t_e_v: float  # arc electron temperature (eV)
    q_s_c: float  # the plasma's charge at x = 1
    g_leak_s: float  # anode-to-grid leakage
    s0_per_s: float  # background ionization (numerics floor)
    c_gk: float = 0.0  # interelectrode capacitances, control grid (the engine stamps them)
    c_ga: float = 0.0
    c_ak: float = 0.0

    @property
    def pins(self) -> tuple[str, ...]:
        return PINS_TRIODE if self.mu_g2 is None else PINS_TETRODE

    # --- the physics, vectorized ----------------------------------------------------

    def control_v(self, va, vg2, vg1):
        if self.mu_g2 is None:
            return vg1 + va / self.mu_a
        return vg1 + vg2 / self.mu_g2 + va / self.mu_a

    def anode_a(self, va, vg2, vg1, x):
        """The electron current to the anode (A)."""
        ev = self.e_v
        vc = self.control_v(va, vg2, vg1)
        d = ev * softplus((va - vc) / ev)
        vx = self.v_x_v * x
        phi = vc + d * vx / (vx + d)
        phi = phi - ev * softplus((phi - va) / ev)
        u = ev * softplus((phi - self.v0_v) / ev)
        return self.perveance * (1.0 + x / self.x_n) * u**1.5

    def nu_v(self, va, x):
        """Ions per electron, in volts of k_ion: single-step plus stepwise."""
        single = self.w_ion_v * softplus((va - self.v_ion_v) / self.w_ion_v)
        step = self.c_meta * (x / self.x_n) * self.w_meta_v
        step = step * softplus((va - self.v_meta_v) / self.w_meta_v)
        return single + step

    def sheath(self, vg1):
        return self.t_e_v * softplus((self.v_float_v - vg1) / self.t_e_v)

    def grid_loss_per_s(self, vg1):
        return self.k_grid * self.sheath(vg1) ** self.p_grid

    def loss_per_s(self, vg1):
        return 1.0 / self.tau_diff_s + self.grid_loss_per_s(vg1)

    def dx_dt(self, va, vg2, vg1, x):
        ia = self.anode_a(va, vg2, vg1, x)
        return self.k_ion * self.nu_v(va, x) * ia + self.s0_per_s - x * self.loss_per_s(vg1)

    def grid1_a(self, va, vg1, x):
        """The current into the control grid (A): leakage, electrons less ions."""
        k_f = self.grid_loss_per_s(self.v_float_v)
        electrons = 2.0 * k_f * np.exp(-softplus((self.v_float_v - vg1) / self.t_e_v))
        return self.g_leak_s * (vg1 - va) + self.q_s_c * x * (electrons - self.grid_loss_per_s(vg1))

    def currents(self, *ports):
        """Port currents at the port voltages (arrays broadcast): a tetrode's
        (V_a, V_g2, V_g1, V_w) -> (I_a, I_g2, I_g1, I_w), a triode's (V_a, V_g, V_w) ->
        (I_a, I_g, I_w). The state is held to [W_MIN, W_MAX] (x from e^-80 to e^40), past
        which the w port restores it at G_EXT_PER_S per e-fold (numerics, as the lamp's
        range)."""
        if self.mu_g2 is None:
            va, vg, w = ports
            ia, _, ig, iw = self._currents(va, 0.0, vg, w)
            return ia, ig, iw
        return self._currents(*ports)

    def _currents(self, va, vg2, vg1, w):
        va, vg2, vg1, wraw = (np.asarray(a, float) for a in (va, vg2, vg1, w))
        w = np.clip(wraw, W_MIN, W_MAX)
        x = np.exp(w)
        ia = self.anode_a(va, vg2, vg1, x)
        ig1 = self.grid1_a(va, vg1, x)
        prod = self.k_ion * self.nu_v(va, x) * ia + self.s0_per_s
        iw = -prod / x + self.loss_per_s(vg1) + G_EXT_PER_S * (wraw - w)
        return ia, np.zeros_like(ia), ig1, iw

    # --- SPICE --------------------------------------------------------------------------

    @property
    def subckt_name(self) -> str:
        return "THY_" + "".join(c if c.isalnum() else "_" for c in self.name).upper()

    def subckt(self) -> str:
        """SPICE subcircuit with the model's pins: behavioural sources for the anode, the
        control grid and the state port, the same equations as `currents`; inner nodes hold
        the clamped state (xw) and the screened barrier (phi)."""

        def sp(z: str) -> str:
            # softplus, overflow-free; SPICE has no log1p, so past |z| = 10 (e < 4.5e-5) its
            # series e - e^2/2 + e^3/3 (relative error < 1e-14) replaces ln(1 + e)
            e = f"exp(-abs({z}))"
            return f"(max({z},0)+(abs({z})>10?{e}*(1-{e}*(0.5-{e}/3)):ln(1+{e})))"

        ev = num(self.e_v)
        tri = self.mu_g2 is None
        g1, k = ("g", "k") if tri else ("g1", "k")
        va, vg = f"V(a,{k})", f"V({g1},{k})"
        vc = (
            f"({vg}+{va}/{num(self.mu_a)})"
            if tri
            else (f"({vg}+V(g2,{k})/{num(self.mu_g2)}+{va}/{num(self.mu_a)})")
        )
        x = "exp(V(xw))"
        d = f"({ev}*{sp(f'({va}-{vc})/{ev}')})"
        vx = f"({num(self.v_x_v)}*{x})"
        phi1 = f"({vc}+{d}*{vx}/({vx}+{d}))"
        u = f"({ev}*{sp(f'(V(phi)-{num(self.v0_v)})/{ev}')})"
        ia = f"({num(self.perveance)}*(1+{x}/{num(self.x_n)})*pwr({u},1.5))"
        single = f"{num(self.w_ion_v)}*{sp(f'({va}-{num(self.v_ion_v)})/{num(self.w_ion_v)}')}"
        step = (
            f"{num(self.c_meta)}*({x}/{num(self.x_n)})*{num(self.w_meta_v)}"
            f"*{sp(f'({va}-{num(self.v_meta_v)})/{num(self.w_meta_v)}')}"
        )
        nu = f"({single}+{step})"
        te = num(self.t_e_v)
        zs = f"({num(self.v_float_v)}-{vg})/{te}"
        gl = f"({num(self.k_grid)}*pwr({te}*{sp(zs)},{num(self.p_grid)}))"
        k_f = float(self.grid_loss_per_s(self.v_float_v))
        el = f"({num(2.0 * k_f)}*exp(-{sp(zs)}))"
        loss = f"({num(1.0 / self.tau_diff_s)}+{gl})"
        prod = f"({num(self.k_ion)}*{nu}*{ia}+{num(self.s0_per_s)})"
        wraw = f"V(w,{k})"
        pins = " ".join(self.pins)
        caps = "".join(
            f"{nm} {p} {q} {num(c)}\n"
            for nm, p, q, c in (
                ("Cgk", g1, k, self.c_gk),
                ("Cga", g1, "a", self.c_ga),
                ("Cak", "a", k, self.c_ak),
            )
            if c > 0
        )
        return (
            f"* {self.name}: generated by varimu.devices.thyratron\n"
            f".subckt {self.subckt_name} {pins}\n"
            f"Bxw xw 0 V={{min(max({wraw},{num(W_MIN)}),{num(W_MAX)})}}\n"
            f"Bp1 p1 0 V={{{phi1}}}\n"
            f"Bphi phi 0 V={{V(p1)-{ev}*{sp(f'(V(p1)-{va})/{ev}')}}}\n"
            f"Ba a {k} I={{{ia}}}\n"
            f"Bg {g1} {k} I={{{num(self.g_leak_s)}*({vg}-{va})"
            f"+{num(self.q_s_c)}*{x}*({el}-{gl})}}\n"
            f"Bw w {k} I={{-{prod}/{x}+{loss}+{num(G_EXT_PER_S)}*({wraw}-V(xw))}}\n"
            f"{caps}.ends {self.subckt_name}\n"
        )


def thyratron_from_data(d: dict, ref: str) -> Thyratron:
    """A thyratron component version's model."""
    m, c = d["model"], d["capacitances_f"]
    return Thyratron(d["name"], **m, c_gk=c["gk"], c_ga=c["ga"], c_ak=c["ak"])
