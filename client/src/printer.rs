use std::collections::HashMap;
use std::thread;
use std::time::Duration;
use std::{cmp::min, fmt::Write};

use colored::*;
use indicatif::{ProgressBar, ProgressState, ProgressStyle};

fn truncate(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        None => s,
        Some((idx, _)) => &s[..idx],
    }
}

struct Printer;
impl Printer {
    const SUCCESS_ICON: &'static str = "✓";
    #[allow(dead_code)]
    const FAIL_ICON: &'static str = "✗";
    const RUN_ICON: &'static str = "🚀";
    #[allow(dead_code)]
    const PREFIX_1_8: &'static str = "▏";
    #[allow(dead_code)]
    const PREFIX_1_4: &'static str = "▎";
    const PREFIX_3_8: &'static str = "▍";
    #[allow(dead_code)]
    const PREFIX_1_2: &'static str = "▌";
    const BARS: [&'static str; 8] = ["▁", "▂", "▃", "▄", "▅", "▆", "▇", "█"];
    const SUCCESS_COLOR: [&'static u8; 3] = [&122, &166, &56];
    #[allow(dead_code)]
    const FAIL_COLOR: [&'static u8; 3] = [&227, &50, &79];
    const MOON_500: [&'static u8; 3] = [&121, &128, &138];
    const GOLD_COLOR: [&'static u8; 3] = [&250, &193, &60];
    const HEADER_COLOR: [&'static u8; 3] = [&255, &255, &255];
    const PROGRESS_COLOR: &'static str = "magenta";
    const PROGRESS_BLANK_COLOR: &'static str = "white.dim";
    // For more spinners check out the cli-spinners project:
    // https://github.com/sindresorhus/cli-spinners/blob/master/spinners.json
    const SPINNERS: [&'static str; 10] = ["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"];
    const PROGRESS: &'static str = "⣿⡇";

    fn sparkline(values: Vec<f64>) -> String {
        let max_val = values.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
        let min_val = values.iter().cloned().fold(f64::INFINITY, f64::min);
        let range = max_val - min_val;

        values
            .iter()
            .map(|&x| {
                let normalized = if range == 0.0 {
                    0
                } else {
                    ((x - min_val) / range * (Printer::BARS.len() - 1) as f64).round() as usize
                };
                Printer::BARS[normalized]
            })
            .collect()
    }

    fn hyperlink(text: &str, url: &str) -> String {
        format!("\x1B]8;;{}\x07{}\x1B]8;;\x07", url, text)
            .truecolor(
                *Printer::GOLD_COLOR[0],
                *Printer::GOLD_COLOR[1],
                *Printer::GOLD_COLOR[2],
            )
            .to_string()
    }

    fn start_spinner(active_msg: String) -> ProgressBar {
        let pb = ProgressBar::new_spinner();
        pb.enable_steady_tick(Duration::from_millis(120));
        pb.set_prefix(Printer::with_prefix(""));
        pb.set_style(
            ProgressStyle::with_template("{prefix}{spinner:.magenta} {msg}")
                .unwrap()
                .tick_strings(&Printer::SPINNERS),
        );
        pb.set_message(active_msg);

        pb
    }

    fn finish_spinner(pb: &ProgressBar, final_msg: String) {
        pb.finish_and_clear();
        // TODO: handle errors
        println!("{}", final_msg);
    }

    fn start_progress_bar(total_size: u64, progress_msg: String) -> ProgressBar {
        let pb = ProgressBar::new(total_size);
        pb.set_prefix(Printer::with_prefix(""));
        let template = format!(
            "{{prefix}}{}{{wide_bar:.{success_color}/{fail_color}.dim}} {{bytes}}/{{total_bytes}} ({{eta}})",
            progress_msg,
            success_color = Printer::PROGRESS_COLOR,
            fail_color = Printer::PROGRESS_BLANK_COLOR,
        );
        pb.set_style(
            ProgressStyle::with_template(&template)
                .unwrap()
                .with_key("eta", |state: &ProgressState, w: &mut dyn Write| {
                    write!(w, "{:.1}s", state.eta().as_secs_f64()).unwrap()
                })
                .progress_chars(Printer::PROGRESS),
        );
        pb
    }

    fn finish_progress_bar(pb: &ProgressBar, final_msg: String) {
        pb.finish_and_clear();
        println!("{}", final_msg)
    }

    fn with_prefix(text: &str) -> String {
        format!(
            "{} {}",
            Printer::PREFIX_3_8.truecolor(
                *Printer::GOLD_COLOR[0],
                *Printer::GOLD_COLOR[1],
                *Printer::GOLD_COLOR[2]
            ),
            text
        )
    }

    fn with_success(text: &str) -> String {
        format!(
            "{} {}",
            Printer::SUCCESS_ICON.truecolor(
                *Printer::SUCCESS_COLOR[0],
                *Printer::SUCCESS_COLOR[1],
                *Printer::SUCCESS_COLOR[2]
            ),
            text
        )
    }

    fn header() -> String {
        let header = format!("wandb");
        let colored_header = header
            .truecolor(
                *Printer::HEADER_COLOR[0],
                *Printer::HEADER_COLOR[1],
                *Printer::HEADER_COLOR[2],
            )
            .bold();
        Printer::with_prefix(&colored_header.to_string())
    }
}

pub fn print_header(name: &str, url: &str) {
    println!("{}", &Printer::header());

    let active_msg = format!("Creating run...");
    let pb = Printer::start_spinner(active_msg);

    thread::sleep(Duration::from_millis(800));

    let final_msg = Printer::with_prefix(&Printer::with_success(&format!(
        "Run created - {} {}",
        Printer::RUN_ICON,
        Printer::hyperlink(name, url).as_str()
    )))
    .white()
    .to_string();
    Printer::finish_spinner(&pb, final_msg);
}

pub fn print_footer(
    name: &str,
    url: &str,
    run_dir: &str,
    sparklines: HashMap<String, (Vec<f32>, Option<String>)>,
) {
    println!("{}", &Printer::header());

    // run stats
    let mut sorted_keys: Vec<_> = sparklines.keys().cloned().collect();
    sorted_keys.sort();

    for key in sorted_keys {
        // continue if starts with an underscore
        if key.starts_with("_") {
            continue;
        }
        if let Some(value) = sparklines.get(&key) {
            let sparkline = Printer::sparkline(value.0.iter().map(|&x| x as f64).collect());
            match &value.1 {
                Some(summary) => {
                    let formatted = format!(
                        "{} {:<20} {}",
                        Printer::with_prefix(""),
                        // todo: fix printing, don't need more than 5 decimal places
                        format!("{} ({})", key, truncate(summary, 7)),
                        sparkline.truecolor(
                            *Printer::MOON_500[0],
                            *Printer::MOON_500[1],
                            *Printer::MOON_500[2],
                        ),
                    );
                    println!("{}", formatted);
                }
                None => {
                    let formatted_loss =
                        format!("{}{:<20} {}", Printer::with_prefix(""), key, sparkline);
                    println!("{}", formatted_loss);
                }
            }
        }
    }
    println!("{}", Printer::with_prefix(""));

    let total_size = 23123123;

    let pb = Printer::start_progress_bar(total_size, "Syncing run".to_string());
    let mut downloaded = 0;
    while downloaded < total_size {
        let new = min(downloaded + 223211, total_size);
        downloaded = new;
        pb.set_position(new);
        thread::sleep(Duration::from_millis(12));
    }
    let final_msg = Printer::with_prefix(&Printer::with_success(&format!(
        "Run synced - {} {}",
        Printer::RUN_ICON,
        Printer::hyperlink(name, url).as_str()
    )));
    Printer::finish_progress_bar(&pb, final_msg.to_string());
    let local_dir = format!("Run dir - {}", run_dir);
    let colored_local_dir = local_dir.truecolor(
        *Printer::MOON_500[0],
        *Printer::MOON_500[1],
        *Printer::MOON_500[2],
    );
    println!("{}", Printer::with_prefix(&colored_local_dir.to_string()));
}
