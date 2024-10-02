use std::collections::HashMap;
use std::time::Duration;
// use std::{cmp::min, fmt::Write};

// use indicatif::{ProgressBar, ProgressState, ProgressStyle};
use indicatif::{ProgressBar, ProgressStyle};

pub mod styled_string {
    use colored::*;

    #[derive(Debug)]
    pub struct StyledString {
        pub text: String,
        pub color: Color,
        pub is_bold: bool,
    }

    impl StyledString {
        pub fn new(text: &str) -> Self {
            Self {
                text: text.to_string(),
                color: Color::White,
                is_bold: false,
            }
        }

        pub fn with_prefix(&mut self, prefix: &str) {
            self.text = format!("{} {}", prefix, self.text);
        }

        pub fn with_color(&mut self, new_color: Color) {
            self.color = new_color;
        }

        pub fn with_bold(&mut self) {
            self.is_bold = true;
        }
    }

    impl std::fmt::Display for StyledString {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            let mut formatted_text = self.text.color(self.color);

            if self.is_bold {
                formatted_text = formatted_text.bold();
            }

            write!(f, "{}", formatted_text)
        }
    }

    mod custom_colors {
        use colored::*;
        pub const DEFAULT_GREEN: Color = Color::TrueColor { r: 0, g: 128, b: 0 };
        #[allow(dead_code)]
        pub const DEFAUTL_RED: Color = Color::TrueColor { r: 255, g: 0, b: 0 };
        pub const DEFAULT_WHITE: Color = Color::TrueColor {
            r: 255,
            g: 255,
            b: 255,
        };
        #[allow(dead_code)]
        pub const DEFAULT_BLACK: Color = Color::TrueColor { r: 0, g: 0, b: 0 };
        #[allow(dead_code)]
        pub const BASE_PINK: Color = Color::TrueColor {
            r: 226,
            g: 192,
            b: 254,
        };
        pub const MOON_500: Color = Color::TrueColor {
            r: 121,
            g: 128,
            b: 138,
        };
        pub const GOLD_450: Color = Color::TrueColor {
            r: 250,
            g: 193,
            b: 60,
        };
    }

    pub mod custom_chars {
        pub const SUCCESS_ICON: &str = "✓";
        pub const FAIL_ICON: &str = "✗";
        pub const ROCKET_ICON: &str = "🚀";
        pub const PREFIX_1_8: &str = "▏";
        pub const PREFIX_1_4: &str = "▎";
        pub const PREFIX_3_8: &str = "▍";
        pub const PREFIX_1_2: &str = "▌";
    }

    pub mod sparklines {
        const BARS: [&str; 7] = ["▁", "▂", "▃", "▄", "▅", "▆", "▇"];

        pub fn sparkline<T: Into<f64> + Copy>(values: Vec<T>) -> String {
            let max_val = values
                .iter()
                .map(|&x| Into::<f64>::into(x))
                .fold(f64::NEG_INFINITY, f64::max);
            let min_val = values
                .iter()
                .map(|&x| Into::<f64>::into(x))
                .fold(f64::INFINITY, f64::min);
            let range = max_val - min_val;

            values
                .iter()
                .map(|&x| {
                    let normalized = if range == 0.0 {
                        0
                    } else {
                        ((Into::<f64>::into(x) - min_val) / range * (BARS.len() - 1) as f64).round()
                            as usize
                    };
                    BARS[normalized]
                })
                .collect()
        }
    }

    pub fn new(text: &str) -> StyledString {
        let mut text = StyledString::new(text);
        text.with_color(custom_colors::DEFAULT_WHITE);
        text
    }

    pub fn new_dim(text: &str) -> StyledString {
        let mut text = StyledString::new(text);
        text.with_color(custom_colors::MOON_500);
        text
    }

    pub fn add_prefix(styled_str: &mut StyledString) {
        let mut prefix = StyledString::new(custom_chars::PREFIX_3_8);
        prefix.with_color(custom_colors::GOLD_450);

        styled_str.with_prefix(&prefix.to_string());
    }

    pub fn add_success(styled_str: &mut StyledString) {
        let mut prefix = StyledString::new(custom_chars::SUCCESS_ICON);
        prefix.with_color(custom_colors::DEFAULT_GREEN);

        styled_str.with_prefix(&prefix.to_string());
    }

    pub fn add_header(styled_str: &mut StyledString) {
        let mut text = StyledString::new("wandb");
        text.with_color(custom_colors::DEFAULT_WHITE);
        text.with_bold();

        styled_str.with_prefix(&text.to_string());
    }

    pub fn create_hyperlink(link_text: &str, url: &str) -> String {
        let hyper = format!("\x1B]8;;{}\x07{}\x1B]8;;\x07", url, link_text);
        let mut text = StyledString::new(&hyper);
        text.with_color(custom_colors::GOLD_450);
        text.with_bold();
        text.to_string()
    }
}

fn truncate(s: &str, max_chars: usize) -> &str {
    match s.char_indices().nth(max_chars) {
        None => s,
        Some((idx, _)) => &s[..idx],
    }
}

struct Printer;
impl Printer {
    // const PROGRESS_COLOR: &'static str = "magenta";
    // const PROGRESS_BLANK_COLOR: &'static str = "white.dim";
    // For more spinners check out the cli-spinners project:
    // https://github.com/sindresorhus/cli-spinners/blob/master/spinners.json
    const SPINNERS: [&'static str; 10] = ["⠋", "⠙", "⠚", "⠞", "⠖", "⠦", "⠴", "⠲", "⠳", "⠓"];
    // const PROGRESS: &'static str = "⣿⡇";

    fn start_spinner(active_msg: String) -> ProgressBar {
        let pb = ProgressBar::new_spinner();
        pb.enable_steady_tick(Duration::from_millis(120));
        let mut prefix = styled_string::new("");
        styled_string::add_prefix(&mut prefix);
        pb.set_prefix(prefix.to_string());
        pb.set_style(
            ProgressStyle::with_template("{prefix}{spinner:.magenta} {msg}")
                .unwrap()
                .tick_strings(&Printer::SPINNERS),
        );
        pb.set_message(active_msg);

        pb
    }

    // fn start_progress_bar(total_size: u64, progress_msg: String) -> ProgressBar {
    //     let pb: ProgressBar = ProgressBar::new(total_size);
    //     let mut prefix = styled_string::new("");
    //     styled_string::add_prefix(&mut prefix);
    //     pb.set_prefix(prefix.to_string());
    //     let template = format!(
    //         "{{prefix}}{}{{wide_bar:.{success_color}/{fail_color}.dim}} {{bytes}}/{{total_bytes}} ({{eta}})",
    //         progress_msg,
    //         success_color = Printer::PROGRESS_COLOR,
    //         fail_color = Printer::PROGRESS_BLANK_COLOR,
    //     );
    //     pb.set_style(
    //         ProgressStyle::with_template(&template)
    //             .unwrap()
    //             .with_key("eta", |state: &ProgressState, w: &mut dyn Write| {
    //                 write!(w, "{:.1}s", state.eta().as_secs_f64()).unwrap()
    //             })
    //             .progress_chars(Printer::PROGRESS),
    //     );
    //     pb
    // }
}

pub fn print_header(name: &str, url: &str) {
    let mut head = styled_string::new("");
    styled_string::add_header(&mut head);
    styled_string::add_prefix(&mut head);
    println!("{}", head);

    let active_msg = format!("Creating run...");
    let pb = Printer::start_spinner(active_msg);

    // TODO: this is for the demo and should be implemented properly
    // std::thread::sleep(Duration::from_millis(800));
    pb.finish_and_clear();

    let mut run = styled_string::new(&format!(
        "Run created - {} {}",
        styled_string::custom_chars::ROCKET_ICON,
        styled_string::create_hyperlink(name, url),
    ));
    styled_string::add_success(&mut run);
    styled_string::add_prefix(&mut run);
    println!("{}", run);
}

pub fn print_offline_header() {
    let mut head = styled_string::new("");
    styled_string::add_header(&mut head);
    styled_string::add_prefix(&mut head);
    println!("{}", head);

    let mut offline = styled_string::new("offline mode is enabled");
    styled_string::add_prefix(&mut offline);
    println!("{}", offline);

    let mut info = styled_string::new_dim("run `wandb online` to enable cloud syncing");
    styled_string::add_prefix(&mut info);
    println!("{}", info);
}

pub fn print_offline_footer(
    run_dir: &str,
    sparklines: HashMap<String, (Vec<f32>, Option<String>)>,
) {
    let mut head = styled_string::new("");
    styled_string::add_header(&mut head);
    styled_string::add_prefix(&mut head);
    println!("{}", head);

    for (key, (values, summary)) in sparklines {
        if key.starts_with("_") {
            continue;
        }
        let sparkline_str = styled_string::sparklines::sparkline(values);
        let formatted = match summary {
            Some(summary) => {
                format!(
                    " {:<20} {}",
                    format!("{} ({})", key, truncate(&summary, 7)),
                    sparkline_str
                )
            }
            None => format!(" {:<20} {}", key, sparkline_str),
        };

        let mut spark = styled_string::new_dim(&formatted);
        styled_string::add_prefix(&mut spark);
        println!("{}", spark);
    }

    let mut empty = styled_string::new("");
    styled_string::add_prefix(&mut empty);
    println!("{}", empty);

    let mut offline = styled_string::new("offline mode is enabled");
    styled_string::add_prefix(&mut offline);
    println!("{}", offline);

    let sync_info = format!("run `wandb sync {}` to sync offline run", run_dir);
    let mut info = styled_string::new_dim(&sync_info);
    styled_string::add_prefix(&mut info);
    println!("{}", info);
}

pub fn print_footer(
    name: &str,
    url: &str,
    run_dir: &str,
    sparklines: HashMap<String, (Vec<f32>, Option<String>)>,
) {
    let mut head = styled_string::new("");
    styled_string::add_header(&mut head);
    styled_string::add_prefix(&mut head);
    println!("{}", head);

    for (key, (values, summary)) in sparklines {
        if key.starts_with("_") {
            continue;
        }
        let sparkline_str = styled_string::sparklines::sparkline(values);
        let formatted = match summary {
            Some(summary) => {
                format!(
                    " {:<20} {}",
                    format!("{} ({})", key, truncate(&summary, 7)),
                    sparkline_str
                )
            }
            None => format!(" {:<20} {}", key, sparkline_str),
        };

        let mut spark = styled_string::new_dim(&formatted);
        styled_string::add_prefix(&mut spark);
        println!("{}", spark);
    }

    let mut empty = styled_string::new("");
    styled_string::add_prefix(&mut empty);
    println!("{}", empty);

    // TODO: this is for the demo and should be implemented properly
    // let total_size = 23123123;
    // let pb = Printer::start_progress_bar(total_size, "Syncing run".to_string());
    // let mut downloaded = 0;
    // while downloaded < total_size {
    //     let new = min(downloaded + 223211, total_size);
    //     downloaded = new;
    //     pb.set_position(new);
    //     std::thread::sleep(Duration::from_millis(12));
    // }
    // pb.finish_and_clear();

    let mut run = styled_string::new(&format!(
        "Run synced - {} {}",
        styled_string::custom_chars::ROCKET_ICON,
        styled_string::create_hyperlink(name, url),
    ));
    styled_string::add_success(&mut run);
    styled_string::add_prefix(&mut run);
    println!("{}", run);

    let sync_info = format!("Run dir - {}", run_dir);
    let mut info = styled_string::new_dim(&sync_info);
    styled_string::add_prefix(&mut info);
    println!("{}", info);
}
