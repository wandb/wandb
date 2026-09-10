//! Wall-clock time formatting for system metrics chart axes.

use chrono::{Local, TimeZone};
use unicode_width::UnicodeWidthStr;

use super::epoch::truncate_title;

/// Formats a unix timestamp (seconds) in local time with a strftime layout.
pub fn format_unix(ts: i64, layout: &str) -> String {
    match Local.timestamp_opt(ts, 0) {
        chrono::LocalResult::Single(dt) | chrono::LocalResult::Ambiguous(dt, _) => {
            dt.format(layout).to_string()
        }
        chrono::LocalResult::None => String::new(),
    }
}

/// Candidate layouts from widest to narrowest for a view span in seconds.
pub fn system_time_layouts(span_secs: f64) -> &'static [&'static str] {
    if span_secs >= 48.0 * 3600.0 {
        &["%b %-d %H:%M", "%b %-d", "%m/%d", "%m%d"]
    } else if span_secs >= 3600.0 {
        &["%H:%M", "%H%M"]
    } else {
        &["%H:%M:%S", "%H:%M", "%H%M"]
    }
}

/// Formats `ts` with the first layout that fits within `max_width` columns.
pub fn fit_time_layouts(ts: i64, max_width: usize, layouts: &[&str]) -> String {
    for layout in layouts {
        let formatted = format_unix(ts, layout);
        if formatted.width() <= max_width {
            return formatted;
        }
    }

    let formatted = format_unix(ts, layouts[layouts.len() - 1]);
    if formatted.width() <= max_width {
        return formatted;
    }
    truncate_title(&formatted, max_width)
}

/// Renders a duration in seconds compactly, e.g. "10m", "1h30m", "45s".
pub fn compact_duration(secs: i64) -> String {
    if secs <= 0 {
        return "0s".to_string();
    }

    if secs % 3600 == 0 {
        return format!("{}h", secs / 3600);
    }
    if secs >= 3600 {
        let hours = secs / 3600;
        let minutes = (secs % 3600) / 60;
        if minutes == 0 {
            return format!("{hours}h");
        }
        return format!("{hours}h{minutes}m");
    }
    if secs % 60 == 0 {
        return format!("{}m", secs / 60);
    }
    if secs >= 60 {
        let minutes = secs / 60;
        let seconds = secs % 60;
        if seconds == 0 {
            return format!("{minutes}m");
        }
        return format!("{minutes}m{seconds}s");
    }
    format!("{secs}s")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compact_durations() {
        assert_eq!(compact_duration(0), "0s");
        assert_eq!(compact_duration(45), "45s");
        assert_eq!(compact_duration(60), "1m");
        assert_eq!(compact_duration(90), "1m30s");
        assert_eq!(compact_duration(600), "10m");
        assert_eq!(compact_duration(3600), "1h");
        assert_eq!(compact_duration(5400), "1h30m");
        assert_eq!(compact_duration(7200), "2h");
    }

    #[test]
    fn layouts_by_span() {
        assert_eq!(system_time_layouts(60.0)[0], "%H:%M:%S");
        assert_eq!(system_time_layouts(7200.0)[0], "%H:%M");
        assert_eq!(system_time_layouts(50.0 * 3600.0)[0], "%b %-d %H:%M");
    }
}
