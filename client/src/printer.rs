use std::collections::HashMap;
use std::thread;
use std::time::Duration;
use std::{cmp::min, fmt::Write};

use colored::*;
use indicatif::{ProgressBar, ProgressState, ProgressStyle};

// const BARS: &'static str = "▁▂▃▄▅▆▇█";
const BARS: &'static str = "▁▂▃▄▅▆▇";

pub fn generate_sparkline(values: Vec<f64>) -> String {
    let max_val = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let min_val = values.iter().cloned().fold(f64::INFINITY, f64::min);
    let range = max_val - min_val;

    let v = BARS.chars().collect::<Vec<char>>();

    values
        .iter()
        .map(|&x| {
            let normalized = if range == 0.0 {
                0
            } else {
                ((x - min_val) / range * (v.len() - 1) as f64).round() as usize
            };
            v[normalized]
        })
        .collect()
}

fn hyperlink(text: &str, url: &str) -> String {
    // format!("\x1B]8;;{}\x07{}\x1B]8;;\x07", url, text).white()
    format!("\x1B]8;;{}\x07{}\x1B]8;;\x07", url, text)
        .bold()
        .truecolor(250, 193, 60)
        .to_string()

    // format!("\x1B]8;;{}\x07{}\x1B]8;;\x07", url, text).truecolor(226, 129, 254)
    // let text = format!("{}", text).white().bold();
    // let url = format!("{}", url).truecolor(250, 193, 60);
    // format!("{}({})", text, url)
}

fn get_prefix() -> ColoredString {
    // String::from("│ ").truecolor(250, 193, 60)
    // String::from("▏").truecolor(250, 193, 60)
    // String::from("▎").truecolor(250, 193, 60)
    // String::from("▌ ").truecolor(250, 193, 60)
    // String::from("▍ ").truecolor(226, 129, 254)  // magenta variant
    String::from("▍ ").truecolor(250, 193, 60) // this one is the best
}

fn get_checkmark() -> ColoredString {
    String::from("✓").truecolor(122, 166, 56)
}

// fn get_crossmark() -> ColoredString {
//     String::from("✗").truecolor(227, 50, 79)
// }

fn get_header() -> String {
    let header = String::from("wandb").white().bold();
    let header = format!("{} {}", get_prefix(), header);
    return header;
}

fn spinner(msg: String, fin_msg: String) {
    let prefix = get_prefix();

    let pb = ProgressBar::new_spinner();
    pb.enable_steady_tick(Duration::from_millis(120));
    pb.set_prefix(prefix.to_string());
    pb.set_style(
        ProgressStyle::with_template("{prefix}{spinner:.magenta} {msg}")
            .unwrap()
            // For more spinners check out the cli-spinners project:
            // https://github.com/sindresorhus/cli-spinners/blob/master/spinners.json
            .tick_strings(&["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"]),
    );
    pb.set_message(msg);

    // TODO: this is for the demo LOL LOL LOL
    thread::sleep(Duration::from_millis(800));

    // pb.finish_with_message("Done");
    pb.finish_and_clear();
    // TODO: handle errors

    println!("{}", fin_msg);
}

pub fn print_header(name: &str, url: &str) {
    println!("{}", get_header());

    // spinner
    let msg = format!("Creating run...");
    let prefix = get_prefix();

    let fin_msg = format!(
        "{} {} Run created - {}",
        prefix,
        get_checkmark(),
        hyperlink(name, url)
    );
    spinner(msg, fin_msg);
}

pub fn print_footer(
    name: &str,
    url: &str,
    run_dir: &str,
    sparklines: HashMap<String, (Vec<f32>, Option<String>)>,
) {
    let link = hyperlink(name, url);

    let mut downloaded = 0;
    let total_size = 23123123;

    let prefix = get_prefix();
    let checkmark = get_checkmark();
    let header = get_header();

    println!("{}", header);

    // run stats
    // TODO: fix me
    // fake loss that exponentially decreases
    // iterate over history and print out the last value
    let mut sorted_keys: Vec<_> = sparklines.keys().cloned().collect();
    sorted_keys.sort();

    for key in sorted_keys {
        if let Some(value) = sparklines.get(&key) {
            let sparkline = generate_sparkline(value.0.iter().map(|&x| x as f64).collect());
            match &value.1 {
                Some(summary) => {
                    let formatted_loss = format!(
                        "{} {:<20} {}",
                        prefix,
                        format!("{} ({})", key, summary),
                        sparkline,
                    );
                    println!("{}", formatted_loss);
                }
                None => {
                    let formatted_loss = format!("{}{:<20} {}", prefix, key, sparkline);
                    println!("{}", formatted_loss);
                }
            }
        }
    }

    // sync progress bar
    let pb = ProgressBar::new(total_size);
    pb.set_prefix(prefix.to_string());
    pb.set_style(
        ProgressStyle::with_template(
            "{prefix}Syncing run {wide_bar:.magenta/white.dim} {bytes}/{total_bytes} ({eta})",
        )
        .unwrap()
        .with_key("eta", |state: &ProgressState, w: &mut dyn Write| {
            write!(w, "{:.1}s", state.eta().as_secs_f64()).unwrap()
        })
        // .progress_chars("⠿⠇"),
        .progress_chars("⣿⡇"),
    );

    while downloaded < total_size {
        let new = min(downloaded + 223211, total_size);
        downloaded = new;
        pb.set_position(new);
        thread::sleep(Duration::from_millis(12));
    }

    pb.finish_and_clear();

    println!("{}{} Run synced - {}", prefix, checkmark, link);

    let local_dir = String::from(format!("Run dir - {}", run_dir))
        .white()
        .dimmed();
    println!("{}{}", prefix, local_dir);
}
