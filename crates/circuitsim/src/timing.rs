//! Where a DK step's time goes, for `examples/profile.rs`: CPU cycles per
//! part of the step, counted when the cargo feature `timing` is on (and
//! nothing at all without it).

/// The parts of a step that are timed.
#[derive(Debug, Clone, Copy)]
pub enum Part {
    /// Device evaluations in Newton.
    Devices,
    /// Building and factoring the Newton matrix.
    Factor,
    /// The rest of a Newton iteration (equivalent currents, solve, test).
    Iteration,
    /// A stage's linear algebra outside Newton (inputs, state, F).
    Stage,
    /// Once per step: the step base, the unknowns, the error estimate.
    Step,
}

pub const PARTS: [(Part, &str); 5] = [
    (Part::Devices, "devices"),
    (Part::Factor, "factorization"),
    (Part::Iteration, "rest of iteration"),
    (Part::Stage, "stage linear algebra"),
    (Part::Step, "per-step linear algebra"),
];

#[cfg(feature = "timing")]
mod imp {
    use super::Part;
    use std::cell::Cell;

    thread_local! {
        static CYCLES: [Cell<u64>; 5] = const { [const { Cell::new(0) }; 5] };
    }

    #[inline(always)]
    pub fn now() -> u64 {
        // SAFETY: rdtsc has no preconditions on x86_64.
        unsafe { std::arch::x86_64::_rdtsc() }
    }

    pub fn add(part: Part, since: u64) {
        let dt = now().wrapping_sub(since);
        CYCLES.with(|c| c[part as usize].set(c[part as usize].get() + dt));
    }

    pub fn take() -> [u64; 5] {
        CYCLES.with(|c| std::array::from_fn(|i| c[i].replace(0)))
    }
}

#[cfg(not(feature = "timing"))]
mod imp {
    use super::Part;

    #[inline(always)]
    pub fn now() -> u64 {
        0
    }

    #[inline(always)]
    pub fn add(_part: Part, _since: u64) {}

    pub fn take() -> [u64; 5] {
        [0; 5]
    }
}

pub use imp::{add, now, take};
