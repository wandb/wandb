//! Width-aware text wrapping and truncation utilities.

use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

/// Truncates `line` so that the visible width including a trailing "..."
/// marker fits within `max_width`.
pub fn with_ellipsis(line: &str, max_width: usize) -> String {
    const MARKER: &str = "...";
    if max_width <= MARKER.len() {
        return MARKER[..max_width.min(MARKER.len())].to_string();
    }

    let target = max_width - MARKER.len();
    let mut out = String::new();
    let mut w = 0;
    for r in line.chars() {
        let rw = r.width().unwrap_or(0);
        if w + rw > target {
            break;
        }
        out.push(r);
        w += rw;
    }
    out.push_str(MARKER);
    out
}

/// Truncates `value` with a trailing " ..." if it exceeds `max_width`.
pub fn truncate_value(value: &str, max_width: usize) -> String {
    if value.width() <= max_width {
        return value.to_string();
    }
    if max_width <= 3 {
        return "...".to_string();
    }

    let available = max_width - 4;
    let mut w = 0;
    let mut out = String::new();
    for r in value.chars() {
        let rw = r.width().unwrap_or(0);
        if w + rw > available {
            out.push_str("...");
            return out;
        }
        w += rw;
        out.push(r);
    }
    out.push_str("...");
    out
}

/// Counts how many screen lines `text` occupies when soft-wrapped at
/// `max_width`. Embedded newlines are respected.
pub fn wrapped_line_count(text: &str, max_width: usize) -> usize {
    if max_width == 0 {
        return 1;
    }
    let mut total = 0;
    for part in text.split('\n') {
        let w = part.width();
        if w == 0 {
            total += 1;
        } else {
            total += w.div_ceil(max_width);
        }
    }
    total.max(1)
}

/// Soft-wraps `text` into multiple lines at `max_width`, preserving embedded
/// newlines.
pub fn wrap_text(text: &str, max_width: usize) -> Vec<String> {
    if max_width == 0 {
        return vec![text.to_string()];
    }

    let mut out = Vec::new();
    for part in text.split('\n') {
        wrap_single_line(part, max_width, &mut out);
    }
    if out.is_empty() {
        return vec![String::new()];
    }
    out
}

/// Breaks a single line (no embedded newlines) into chunks that each fit
/// within `max_width` display columns.
fn wrap_single_line(s: &str, max_width: usize, out: &mut Vec<String>) {
    if s.width() <= max_width {
        out.push(s.to_string());
        return;
    }

    let runes: Vec<char> = s.chars().collect();
    let mut start = 0;
    while start < runes.len() {
        let mut w = 0;
        let mut end = start;
        while end < runes.len() {
            let rw = runes[end].width().unwrap_or(0);
            if w + rw > max_width && end > start {
                break;
            }
            w += rw;
            end += 1;
            if w >= max_width {
                break;
            }
        }
        out.push(runes[start..end].iter().collect());
        start = end;
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn wrap_preserves_newlines() {
        assert_eq!(wrap_text("ab\ncd", 10), vec!["ab", "cd"]);
        assert_eq!(wrap_text("abcdef", 3), vec!["abc", "def"]);
        assert_eq!(wrap_text("", 5), vec![""]);
    }

    #[test]
    fn line_counts() {
        assert_eq!(wrapped_line_count("abcdef", 3), 2);
        assert_eq!(wrapped_line_count("a\nb", 10), 2);
        assert_eq!(wrapped_line_count("", 10), 1);
    }

    #[test]
    fn ellipsis() {
        assert_eq!(with_ellipsis("abcdefgh", 6), "abc...");
        assert_eq!(with_ellipsis("ab", 2), "..");
        assert_eq!(truncate_value("hello world", 8), "hell...");
        assert_eq!(truncate_value("hi", 8), "hi");
    }
}
