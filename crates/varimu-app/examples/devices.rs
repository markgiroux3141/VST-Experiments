//! The audio devices cpal sees on this machine and their default formats.
//!
//!     cargo run -p varimu-app --example devices

use cpal::traits::{DeviceTrait, HostTrait};

fn main() {
    let host = cpal::default_host();
    println!("host: {:?}", host.id());
    let name = |d: &cpal::Device| {
        d.description()
            .map_or("?".to_string(), |x| x.name().to_string())
    };
    if let Some(d) = host.default_output_device() {
        println!(
            "default output: {} {:?}",
            name(&d),
            d.default_output_config()
        );
    }
    if let Some(d) = host.default_input_device() {
        println!("default input: {} {:?}", name(&d), d.default_input_config());
    }
    for d in host.devices().into_iter().flatten() {
        println!(
            "- {} (out {}, in {})",
            name(&d),
            d.supports_output(),
            d.supports_input()
        );
        if d.supports_output() {
            println!("    out {:?}", d.default_output_config());
        }
        // Inputs: the default format only. cpal 0.18 overflows (a panic in debug
        // builds) listing every format of interfaces with many channels (the UA Twin).
        if d.supports_input() {
            println!("    in  {:?}", d.default_input_config());
        }
    }
}
