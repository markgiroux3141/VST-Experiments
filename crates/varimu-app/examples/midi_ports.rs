//! The MIDI inputs midir sees, and what the first one (or one named like the argument)
//! sends for ten seconds: `cargo run -p varimu-app --example midi_ports [-- NAME]`.

use std::time::{Duration, Instant};

use varimu_app::midi::{self, Keyboard, MOD_WHEEL};

fn main() -> Result<(), String> {
    for (i, p) in midi::ports()?.iter().enumerate() {
        println!("{i}: {p}");
    }
    let name = std::env::args().nth(1);
    let kb = Keyboard::open(name.as_deref())?;
    println!(
        "listening to {} for 10 s: play some keys, move the mod wheel",
        kb.name
    );
    let (mut last, start) = ((None, (0, 0)), Instant::now());
    while start.elapsed() < Duration::from_secs(10) {
        let now = (kb.keys.sounding(), kb.keys.cc(MOD_WHEEL));
        if now != last {
            println!("  key {:?}  mod wheel {:?}", now.0, now.1);
            last = now;
        }
        std::thread::sleep(Duration::from_millis(5));
    }
    Ok(())
}
