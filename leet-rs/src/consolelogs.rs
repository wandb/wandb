//! Console log assembly and the collapsible console logs pane.

use std::time::Instant;

use chrono::{Local, TimeZone};
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Modifier, Style};
use unicode_width::UnicodeWidthStr;

use crate::animation::AnimatedValue;
use crate::pagedlist::KeyValuePair;
use crate::textwrap::{truncate_value, with_ellipsis, wrap_text, wrapped_line_count};
use crate::theme::{
    COLOR_DARK, COLOR_ITEM_VALUE, COLOR_SELECTED, COLOR_SUBHEADING, COLOR_SUBTLE, CONTENT_PADDING,
    SIDEBAR_WIDTH_RATIO,
};

// ---- Console log assembly ----

/// The terminal emulator window size.
///
/// This bounds memory for cursor-addressable output. Lines that scroll out
/// of the terminal window are preserved in the assembled list.
const MAX_CONSOLE_TERM_LINES: usize = 64;

/// Maximum rune length per assembled line.
const MAX_CONSOLE_LINE_LENGTH: usize = 4096;

/// An assembled, display-ready line of console output.
struct ConsoleLogLine {
    content: Vec<char>,
}

/// Backing store shared by both terminal emulators.
#[derive(Default)]
struct LineStore {
    /// The assembled, ordered log output; lines from both streams are
    /// interleaved in arrival order.
    lines: Vec<ConsoleLogLine>,
    /// Mirrors `lines` in the KeyValuePair shape expected by the pane;
    /// updated incrementally.
    items: Vec<KeyValuePair>,
    /// Bumped on every content change, so consumers can skip re-syncing.
    revision: u64,
}

impl LineStore {
    fn append_line(&mut self, timestamp: i64) -> usize {
        let idx = self.lines.len();
        self.lines.push(ConsoleLogLine {
            content: Vec::new(),
        });
        self.items.push(KeyValuePair {
            key: format_console_timestamp(timestamp),
            value: String::new(),
            path: Vec::new(),
        });
        self.revision += 1;
        idx
    }

    fn put_char(&mut self, idx: usize, c: char, offset: usize) {
        if offset >= MAX_CONSOLE_LINE_LENGTH || idx >= self.lines.len() {
            return;
        }
        let line = &mut self.lines[idx];
        while offset >= line.content.len() {
            line.content.push(' ');
        }
        if line.content[offset] == c {
            return;
        }
        line.content[offset] = c;
        self.revision += 1;

        let value: String = line.content.iter().collect();
        let value = value.trim_end_matches([' ', '\t']).to_string();
        if idx < self.items.len() {
            self.items[idx].value = value;
        }
    }
}

fn format_console_timestamp(unix_secs: i64) -> String {
    match Local.timestamp_opt(unix_secs, 0).single() {
        Some(dt) => dt.format("%H:%M:%S").to_string(),
        None => "00:00:00".to_string(),
    }
}

/// A minimal virtual terminal supporting `\r`, `\n` and cursor up/down
/// escape sequences (as used by tqdm-style progress bars).
struct Terminal {
    height: usize,
    /// Indices into the shared line store; index 0 is the top of the view.
    view: Vec<usize>,
    view_y: usize,
    view_x: usize,
    /// The accumulated escape sequence (empty if not parsing one).
    escape: String,
}

impl Terminal {
    fn new(height: usize) -> Self {
        Self {
            height,
            view: Vec::new(),
            view_y: 0,
            view_x: 0,
            escape: String::new(),
        }
    }

    fn write(&mut self, input: &str, store: &mut LineStore, timestamp: i64) {
        for c in input.chars() {
            match self.escape.as_str() {
                "" => match c {
                    '\r' => self.view_x = 0,
                    '\n' => self.line_feed(),
                    '\x1b' => self.escape.push(c),
                    _ => self.put_char(c, store, timestamp),
                },
                "\x1b" => match c {
                    '[' => self.escape.push('['),
                    _ => {
                        self.print_escape_sequence(store, timestamp);
                        self.put_char(c, store, timestamp);
                    }
                },
                _ => match c {
                    'A' => {
                        self.view_y = self.view_y.saturating_sub(1);
                        self.escape.clear();
                    }
                    'B' => {
                        self.cursor_down();
                        self.escape.clear();
                    }
                    _ => {
                        self.print_escape_sequence(store, timestamp);
                        self.put_char(c, store, timestamp);
                    }
                },
            }
        }
    }

    /// Prints out and resets the accumulated (unknown) escape sequence.
    fn print_escape_sequence(&mut self, store: &mut LineStore, timestamp: i64) {
        let pending = std::mem::take(&mut self.escape);
        for c in pending.chars() {
            self.put_char(c, store, timestamp);
        }
    }

    fn put_char(&mut self, c: char, store: &mut LineStore, timestamp: i64) {
        while self.view_y >= self.view.len() {
            let idx = store.append_line(timestamp);
            self.view.push(idx);
        }
        store.put_char(self.view[self.view_y], c, self.view_x);
        self.view_x += 1;
    }

    /// Moves the cursor down one line, with an implicit `\r`.
    fn line_feed(&mut self) {
        self.view_x = 0;
        self.view_y += 1;
        if self.view_y >= self.height {
            self.scroll_down();
        }
    }

    fn cursor_down(&mut self) {
        self.view_y += 1;
        if self.view_y >= self.height {
            self.scroll_down();
        }
    }

    fn scroll_down(&mut self) {
        if !self.view.is_empty() {
            self.view.remove(0);
        }
        self.view_y = self.view_y.saturating_sub(1);
    }
}

/// Assembles raw output records into display-ready lines.
///
/// Raw terminal output may contain ANSI escape codes, partial lines, and
/// carriage returns. Each stream (stdout/stderr) gets its own terminal
/// emulator that correctly handles cursor movements, overwrites, and newline
/// assembly.
pub struct RunConsoleLogs {
    stdout_term: Terminal,
    stderr_term: Terminal,
    store: LineStore,
}

impl Default for RunConsoleLogs {
    fn default() -> Self {
        Self::new()
    }
}

impl RunConsoleLogs {
    pub fn new() -> Self {
        Self {
            stdout_term: Terminal::new(MAX_CONSOLE_TERM_LINES),
            stderr_term: Terminal::new(MAX_CONSOLE_TERM_LINES),
            store: LineStore::default(),
        }
    }

    /// Feeds a raw output record through the terminal emulator.
    pub fn process_raw(&mut self, text: &str, is_stderr: bool, timestamp: i64) {
        if is_stderr {
            self.stderr_term.write(text, &mut self.store, timestamp);
        } else {
            self.stdout_term.write(text, &mut self.store, timestamp);
        }
    }

    /// The assembled lines in [`KeyValuePair`] form.
    pub fn items(&self) -> &[KeyValuePair] {
        &self.store.items
    }

    /// A counter that changes whenever the assembled content changes.
    pub fn revision(&self) -> u64 {
        self.store.revision
    }
}

// ---- Console logs pane ----

/// Fraction of total terminal height allocated to the bottom bar when
/// expanded (same golden-ratio derived value as the sidebar width).
pub const CONSOLE_LOGS_PANE_HEIGHT_RATIO: f64 = SIDEBAR_WIDTH_RATIO;

const CONSOLE_LOGS_PADDING_LINES: i32 = 1;
const CONSOLE_LOGS_HEADER_LINES: i32 = 1;

/// Minimum total height for the bottom bar.
pub const CONSOLE_LOGS_PANE_MIN_HEIGHT: i32 =
    CONSOLE_LOGS_PADDING_LINES + CONSOLE_LOGS_HEADER_LINES + 1;

const CONSOLE_LOGS_PANE_HEADER: &str = "Console Logs";

/// Fraction of the bar's width reserved for the timestamp key column.
const CONSOLE_LOGS_KEY_WIDTH_RATIO: f64 = 0.12;

const TIMESTAMP_FULL_WIDTH: usize = 8; // HH:MM:SS
const TIMESTAMP_SHORT_WIDTH: usize = 5; // HH:MM

fn header_style() -> Style {
    Style::new()
        .add_modifier(Modifier::BOLD)
        .fg(COLOR_SUBHEADING.color())
}

fn timestamp_style(highlighted: bool) -> Style {
    if highlighted {
        Style::new().bg(COLOR_SELECTED.color()).fg(COLOR_DARK)
    } else {
        Style::new().fg(COLOR_SUBTLE.color())
    }
}

fn value_style(highlighted: bool) -> Style {
    if highlighted {
        Style::new().bg(COLOR_SELECTED.color()).fg(COLOR_DARK)
    } else {
        Style::new().fg(COLOR_ITEM_VALUE.color())
    }
}

/// The key text to render within the timestamp column.
///
/// Adapts to narrow columns to avoid showing partial timestamps:
/// "HH:MM:SS" when there is room, "HH:MM" when there is room for minutes but
/// not seconds, "" otherwise. `max_key_width` includes the 1-column left pad.
fn console_log_key_for_width(key: &str, max_key_width: usize) -> &str {
    let available = max_key_width.saturating_sub(1);
    if available < TIMESTAMP_SHORT_WIDTH {
        return "";
    }
    if available < TIMESTAMP_FULL_WIDTH && key.len() >= TIMESTAMP_SHORT_WIDTH {
        return &key[..TIMESTAMP_SHORT_WIDTH];
    }
    key
}

/// A collapsible, scrollable panel that displays console log output at the
/// bottom of the main content area.
///
/// Supports animated expand/collapse via [`AnimatedValue`], virtual
/// scrolling over wrapped log entries, auto-scroll to follow new output, and
/// manual navigation that freezes auto-scroll when the user moves away from
/// the tail.
pub struct ConsoleLogsPane {
    anim_state: AnimatedValue,

    logs: Vec<KeyValuePair>,

    /// The selected log index (logical row).
    cursor: usize,
    /// The first visible log index.
    top: usize,

    active: bool,
    auto_scroll: bool,

    /// Cached layout params from the most recent render, used by navigation
    /// methods to compute page boundaries without re-deriving the layout.
    last_value_width: usize,
    last_content_lines: usize,
}

impl ConsoleLogsPane {
    /// Returns a collapsed pane with auto-scroll enabled.
    pub fn new(anim_state: AnimatedValue) -> Self {
        Self {
            anim_state,
            logs: Vec::new(),
            cursor: 0,
            top: 0,
            active: false,
            auto_scroll: true,
            last_value_width: 0,
            last_content_lines: 0,
        }
    }

    /// The current rendered height (may be mid-animation).
    pub fn height(&self) -> i32 {
        self.anim_state.value()
    }

    /// Whether the bar occupies any screen space.
    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    /// Whether an expand/collapse animation is in progress.
    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    /// Whether the bar is stably at its expanded height.
    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }

    /// Whether the pane will be visible after any running animation.
    pub fn target_visible(&self) -> bool {
        self.anim_state.target_visible()
    }

    /// Initiates an expand or collapse animation.
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    pub fn force_collapse(&mut self) {
        self.anim_state.force_collapse();
    }

    pub fn force_expand(&mut self) {
        self.anim_state.force_expand();
    }

    /// Advances the animation by one frame. Returns true when complete.
    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    /// Whether the bottom bar currently holds keyboard focus.
    pub fn active(&self) -> bool {
        self.active
    }

    pub fn set_active(&mut self, active: bool) {
        self.active = active;
    }

    /// Sets the expanded height, clamped to the pane minimum.
    pub fn set_expanded_height(&mut self, h: i32) {
        self.anim_state
            .set_expanded(h.max(CONSOLE_LOGS_PANE_MIN_HEIGHT));
    }

    /// Recalculates the expanded height from the terminal height.
    pub fn update_expanded_height(&mut self, max_terminal_height: i32) {
        let max_height = (max_terminal_height as f64 * CONSOLE_LOGS_PANE_HEIGHT_RATIO) as i32;
        self.set_expanded_height(max_height);
    }

    /// Whether the pane has any log entries to display.
    pub fn has_data(&self) -> bool {
        !self.logs.is_empty()
    }

    /// Replaces the displayed log entries and adjusts the viewport. If
    /// auto-scroll is enabled, the view snaps to the tail.
    pub fn set_console_logs(&mut self, items: Vec<KeyValuePair>) {
        self.logs = items;

        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            self.auto_scroll = true;
            return;
        }

        self.cursor = self.cursor.min(self.logs.len() - 1);
        self.top = self.top.min(self.logs.len() - 1);

        if self.auto_scroll {
            self.scroll_to_end();
        } else {
            self.ensure_cursor_visible();
        }
    }

    /// Renders the console logs pane into `area` (whose height should be the
    /// current animated height minus the top padding line).
    ///
    /// Renders nothing when collapsed or the width is insufficient.
    pub fn render(&mut self, area: Rect, buf: &mut Buffer, run_label: &str, hint: &str) {
        let h = self.height();
        if area.width == 0 || h < CONSOLE_LOGS_PANE_MIN_HEIGHT {
            return;
        }

        let inner_h = h - CONSOLE_LOGS_PADDING_LINES;
        let content_lines = (inner_h - CONSOLE_LOGS_HEADER_LINES).max(1) as usize;

        // Reserve ContentPadding on each side: a 1-column left inset is
        // built into the key column; the right column is left free.
        let content_w = (area.width as i32 - CONTENT_PADDING as i32).max(0) as usize;
        let mut max_key_width = ((content_w as f64 * CONSOLE_LOGS_KEY_WIDTH_RATIO) as usize).max(1);
        max_key_width = max_key_width.min((content_w.saturating_sub(2)).max(1));
        let max_value_width = (content_w as i32 - max_key_width as i32 - 1).max(1) as usize;

        self.last_value_width = max_value_width;
        self.last_content_lines = content_lines;

        if self.auto_scroll {
            self.scroll_to_end();
        } else {
            self.ensure_cursor_visible();
        }

        let end = self.visible_end(self.top, max_value_width, content_lines);

        self.render_header(area, buf, content_w, run_label, self.top, end);
        self.render_content(
            area,
            buf,
            max_key_width,
            max_value_width,
            content_lines,
            self.top,
            end,
            hint,
        );
    }

    /// Renders the "Console Logs • <runLabel>     [X-Y of N]" line.
    fn render_header(
        &self,
        area: Rect,
        buf: &mut Buffer,
        width: usize,
        run_label: &str,
        start_idx: usize,
        end_idx: usize,
    ) {
        let title = CONSOLE_LOGS_PANE_HEADER;
        let nav_info = if self.logs.is_empty() {
            String::new()
        } else {
            format!(" [{}-{} of {}]", start_idx + 1, end_idx, self.logs.len())
        };

        // Title (with 1-column left pad, mirroring lipgloss PaddingLeft).
        let mut x = area.x + 1;
        buf.set_stringn(x, area.y, title, width, header_style());
        x += title.len() as u16;

        if !run_label.is_empty() {
            let sep = " • ";
            let max_run_width =
                width as i32 - 1 - title.len() as i32 - nav_info.len() as i32 - sep.width() as i32;
            if max_run_width > 0 {
                let label = format!("{sep}{}", truncate_value(run_label, max_run_width as usize));
                buf.set_stringn(
                    x,
                    area.y,
                    &label,
                    (area.right().saturating_sub(x)) as usize,
                    crate::theme::nav_info_style(),
                );
            }
        }

        // Range indicator, right-aligned within the content width.
        if !nav_info.is_empty() {
            let nav_x = (area.x as usize + 1 + width).saturating_sub(nav_info.len()) as u16;
            buf.set_stringn(
                nav_x,
                area.y,
                &nav_info,
                nav_info.len(),
                crate::theme::nav_info_style(),
            );
        }
    }

    /// Renders the visible log lines.
    #[allow(clippy::too_many_arguments)]
    fn render_content(
        &self,
        area: Rect,
        buf: &mut Buffer,
        max_key_width: usize,
        max_value_width: usize,
        content_lines: usize,
        start_idx: usize,
        end_idx: usize,
        hint: &str,
    ) {
        if content_lines == 0 || area.height <= 1 {
            return;
        }
        let y0 = area.y + 1;

        if self.logs.is_empty() {
            let hint = if hint.is_empty() { "No data." } else { hint };
            buf.set_stringn(
                area.x + 1,
                y0,
                hint,
                area.width.saturating_sub(1) as usize,
                timestamp_style(false),
            );
            return;
        }

        let start_idx = start_idx.min(self.logs.len() - 1);
        let end_idx = end_idx.clamp(start_idx, self.logs.len());

        let mut used = 0usize;
        for i in start_idx..end_idx {
            if used >= content_lines || y0 + used as u16 >= area.bottom() {
                break;
            }
            let remaining = content_lines - used;
            used += self.render_entry(
                area,
                buf,
                y0 + used as u16,
                &self.logs[i],
                i == self.cursor && self.active,
                max_key_width,
                max_value_width,
                remaining,
            );
        }
    }

    /// Renders a single log entry, wrapping the value and showing the
    /// timestamp key only on the first line. If the entry exceeds
    /// `max_lines`, it is truncated with an ellipsis. Returns the number of
    /// lines used.
    #[allow(clippy::too_many_arguments)]
    fn render_entry(
        &self,
        area: Rect,
        buf: &mut Buffer,
        y: u16,
        item: &KeyValuePair,
        highlighted: bool,
        max_key_width: usize,
        max_value_width: usize,
        max_lines: usize,
    ) -> usize {
        let key = console_log_key_for_width(&item.key, max_key_width);
        let mut lines = wrap_text(&item.value, max_value_width);

        let truncated = lines.len() > max_lines;
        if truncated {
            lines.truncate(max_lines);
            if let Some(last) = lines.last_mut() {
                *last = with_ellipsis(last, max_value_width);
            }
        }
        if lines.is_empty() {
            lines.push(String::new());
        }

        let key_style = timestamp_style(highlighted);
        let val_style = value_style(highlighted);

        for (i, v) in lines.iter().enumerate() {
            let row = y + i as u16;
            if row >= area.bottom() {
                return i;
            }
            // Key column: [pad(1)][key][fill to max_key_width].
            let key_text = if i == 0 { key } else { "" };
            let mut col = format!(" {key_text}");
            while col.width() < max_key_width {
                col.push(' ');
            }
            buf.set_stringn(area.x, row, &col, max_key_width, key_style);

            // Gap column (carries highlight background).
            buf.set_stringn(area.x + max_key_width as u16, row, " ", 1, val_style);

            // Value.
            let vx = area.x + max_key_width as u16 + 1;
            if highlighted {
                // Fill the full value width so the highlight bar extends.
                let mut padded = v.clone();
                while padded.width() < max_value_width {
                    padded.push(' ');
                }
                buf.set_stringn(vx, row, &padded, max_value_width, val_style);
            } else {
                buf.set_stringn(vx, row, v, max_value_width, val_style);
            }
        }

        lines.len()
    }

    // ---- Navigation ----

    /// Moves the cursor one entry toward the top, wrapping to the last entry
    /// when at the beginning.
    pub fn up(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.cursor == 0 {
            self.cursor = self.logs.len() - 1;
            self.scroll_to_end();
        } else {
            self.cursor -= 1;
            self.ensure_cursor_visible();
        }
        self.update_auto_scroll();
    }

    /// Moves the cursor one entry toward the bottom, wrapping to the first
    /// entry when at the end.
    pub fn down(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.cursor == self.logs.len() - 1 {
            self.cursor = 0;
            self.top = 0;
        } else {
            self.cursor += 1;
            self.ensure_cursor_visible();
        }
        self.update_auto_scroll();
    }

    /// Advances the viewport by one screenful, wrapping to the top when past
    /// the end.
    pub fn page_down(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.last_content_lines == 0 || self.last_value_width == 0 {
            self.down();
            return;
        }

        let end = self.visible_end(self.top, self.last_value_width, self.last_content_lines);
        if end >= self.logs.len() {
            self.cursor = 0;
            self.top = 0;
            self.update_auto_scroll();
            return;
        }

        self.top = end;
        self.cursor = end;
        self.ensure_cursor_visible();
        self.update_auto_scroll();
    }

    /// Moves the viewport back by one screenful, wrapping to the end when
    /// before the start.
    pub fn page_up(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.last_content_lines == 0 || self.last_value_width == 0 {
            self.up();
            return;
        }

        if self.top == 0 {
            self.cursor = self.logs.len() - 1;
            self.scroll_to_end();
            self.update_auto_scroll();
            return;
        }

        let mut new_top = self.top;
        let mut used = 0usize;
        while new_top > 0 && used < self.last_content_lines {
            let prev = new_top - 1;
            let h = wrapped_line_count(&self.logs[prev].value, self.last_value_width);
            if used + h > self.last_content_lines && used > 0 {
                break;
            }
            used += h.min(self.last_content_lines - used);
            new_top = prev;
        }

        self.top = new_top;
        self.cursor = new_top;
        self.ensure_cursor_visible();
        self.update_auto_scroll();
    }

    /// Snaps the viewport to show the last log entry and re-enables
    /// auto-scroll.
    pub fn scroll_to_end_and_follow(&mut self) {
        self.auto_scroll = true;
        self.scroll_to_end();
    }

    /// Snaps the viewport to the first log entry and disables auto-scroll.
    pub fn scroll_to_start(&mut self) {
        self.cursor = 0;
        self.top = 0;
        self.auto_scroll = self.logs.is_empty();
    }

    // ---- Internal scrolling ----

    /// Enables auto-scroll when the cursor is on the last entry, and
    /// disables it otherwise.
    fn update_auto_scroll(&mut self) {
        if self.logs.is_empty() {
            self.auto_scroll = true;
            return;
        }
        if self.cursor == self.logs.len() - 1 {
            self.auto_scroll = true;
            self.scroll_to_end();
            return;
        }
        self.auto_scroll = false;
    }

    /// Adjusts `top` so that the cursor entry is within the visible window.
    fn ensure_cursor_visible(&mut self) {
        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            return;
        }

        self.cursor = self.cursor.min(self.logs.len() - 1);
        self.top = self.top.min(self.logs.len() - 1);

        if self.cursor < self.top {
            self.top = self.cursor;
            return;
        }

        while self.cursor
            >= self.visible_end(self.top, self.last_value_width, self.last_content_lines)
            && self.top < self.logs.len() - 1
        {
            self.top += 1;
        }
    }

    /// Positions the viewport so the last entry is at the bottom.
    fn scroll_to_end(&mut self) {
        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            return;
        }
        self.cursor = self.logs.len() - 1;

        if self.last_content_lines == 0 || self.last_value_width == 0 {
            self.top = self.cursor;
            return;
        }

        let mut top = self.cursor;
        let mut used = wrapped_line_count(&self.logs[top].value, self.last_value_width)
            .min(self.last_content_lines);

        while top > 0 && used < self.last_content_lines {
            let prev = top - 1;
            let h = wrapped_line_count(&self.logs[prev].value, self.last_value_width);
            if used + h > self.last_content_lines {
                break;
            }
            used += h;
            top = prev;
        }

        self.top = top;
    }

    /// The exclusive end index of log entries that fit within
    /// `content_lines` screen rows starting from `start_idx`, accounting for
    /// line wrapping.
    fn visible_end(&self, start_idx: usize, max_value_width: usize, content_lines: usize) -> usize {
        if self.logs.is_empty() {
            return 0;
        }
        let start_idx = start_idx.min(self.logs.len() - 1);

        let mut used = 0usize;
        let mut i = start_idx;
        while i < self.logs.len() && used < content_lines {
            let remaining = content_lines - used;
            let h = wrapped_line_count(&self.logs[i].value, max_value_width);
            used += h.min(remaining);
            i += 1;
        }
        i
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn assembles_lines_with_carriage_return() {
        let mut logs = RunConsoleLogs::new();
        logs.process_raw("progress: 10%\rprogress: 20%\n", false, 0);
        logs.process_raw("done\n", false, 1);
        let items = logs.items();
        assert_eq!(items.len(), 2);
        assert_eq!(items[0].value, "progress: 20%");
        assert_eq!(items[1].value, "done");
    }

    #[test]
    fn cursor_up_overwrites_previous_line() {
        let mut logs = RunConsoleLogs::new();
        logs.process_raw("aaa\nbbb\n", false, 0);
        logs.process_raw("\x1b[A\x1b[Accc\n", false, 0);
        // Cursor up twice from line 2 goes to line 0.
        assert_eq!(logs.items()[0].value, "ccc");
    }

    #[test]
    fn interleaves_stdout_and_stderr() {
        let mut logs = RunConsoleLogs::new();
        logs.process_raw("out\n", false, 0);
        logs.process_raw("err\n", true, 0);
        assert_eq!(logs.items().len(), 2);
        assert_eq!(logs.items()[0].value, "out");
        assert_eq!(logs.items()[1].value, "err");
    }
}
