//! Port of `core/internal/leet/consolelogspane.go` — a collapsible,
//! scrollable panel that displays console log output at the bottom of the
//! main content area.
//!
//! Rendering goes through the [`crate::layout`] lipgloss subset; block
//! values are `ratatui::text::Text` instead of ANSI strings (see the
//! layout module doc). Go's `""` return ports as an empty `Text` (no
//! lines) — `text_to_string` of it is `""`, matching Go callers' checks.
//!
//! PARITY: Go mixes two width metrics in this file. The wrap/count
//! helpers (`wrappedLineCount`, `wrapSingleLine`, `WithEllipsis`) measure
//! with go-runewidth (`runewidth.StringWidth` is a per-rune `RuneWidth`
//! sum — NO grapheme clustering), while the header/truncation paths
//! (`consoleLogKeyForWidth`, `renderHeader`, `truncateValue`) use
//! `lipgloss.Width` (grapheme-aware). The port mirrors that split:
//! [`rune_width`]/[`rune_string_width`] for the former, `text_width` for
//! the latter — both routed through the `leet_data::width` shim per
//! PORTING.md (the shim's per-char widths may differ from go-runewidth's
//! tables for a handful of code points; the shim is the port's single
//! width authority). Keeping the wrap COUNT per-rune like Go guarantees
//! `wrapped_line_count` agrees with `wrap_text(..).len()` for values
//! containing multi-rune clusters (VS16/ZWJ emoji), so the viewport math
//! (`visible_end`, `scroll_to_end_inner`, `page_up`) and the "[X-Y of N]"
//! indicator match what `render_entry` actually renders.

use std::time::Instant;

use leet_charts::styles::SIDEBAR_WIDTH_RATIO;
use leet_data::run_overview::KeyValuePair;
use leet_data::width::{grapheme_width, text_width};
use ratatui::text::{Line, Text};

use crate::animation::AnimatedValue;
use crate::layout::{
    GoStyle, LEFT, TOP, block_width, console_logs_pane_header_style,
    console_logs_pane_highlighted_timestamp_style, console_logs_pane_highlighted_value_style,
    console_logs_pane_timestamp_style, console_logs_pane_value_style, join_horizontal,
    join_vertical, nav_info_style, place, text_from_str,
};

// PARITY: ContentPadding lives in styles.go in Go; the Rust styles module
// hosts it as i64 — cast once so the pane math stays isize (panel_grid.rs
// does the same).
const CONTENT_PADDING: isize = leet_charts::styles::CONTENT_PADDING as isize;

// ConsoleLogsPane layout constants.

/// ConsoleLogsPaneHeightRatio controls the fraction of total terminal height
/// allocated to the bottom bar when expanded. Uses the same golden-ratio
/// derived value as the sidebar width.
pub const CONSOLE_LOGS_PANE_HEIGHT_RATIO: f64 = SIDEBAR_WIDTH_RATIO;

/// ConsoleLogsPaneMinHeight is the minimum total height for the bottom bar.
pub const CONSOLE_LOGS_PANE_MIN_HEIGHT: isize =
    CONSOLE_LOGS_PADDING_LINES + CONSOLE_LOGS_HEADER_LINES + 1;

const CONSOLE_LOGS_PANE_HEADER: &str = "Console Logs";
const CONSOLE_LOGS_PADDING_LINES: isize = 1;
const CONSOLE_LOGS_HEADER_LINES: isize = 1;

/// consoleLogsKeyWidthRatio is the fraction of the bar's width reserved
/// for the timestamp key column.
const CONSOLE_LOGS_KEY_WIDTH_RATIO: f64 = 0.12;

const CONSOLE_LOG_TIMESTAMP_FULL_WIDTH: isize = "00:00:00".len() as isize; // HH:MM:SS
const CONSOLE_LOG_TIMESTAMP_SHORT_WIDTH: isize = "00:00".len() as isize; // HH:MM

/// consoleLogKeyForWidth returns the key text to render within the timestamp column.
///
/// It adapts to narrow columns to avoid showing partial timestamps:
///   - "HH:MM:SS" when there is room
///   - "HH:MM" when there is room for minutes but not seconds
///   - "" when there isn't room for "HH:MM"
fn console_log_key_for_width(key: &str, max_key_width: isize, key_style: &GoStyle) -> String {
    // The timestamp styles include padding. Subtract the style's "empty render" width
    // so we only consider the columns available for the timestamp text itself.
    let available = max_key_width - block_width(&key_style.render("")) as isize;
    if available < CONSOLE_LOG_TIMESTAMP_SHORT_WIDTH {
        return String::new();
    }
    if available < CONSOLE_LOG_TIMESTAMP_FULL_WIDTH {
        // PARITY: Go byte-slices `key[:5]`; timestamp keys are ASCII so
        // byte and column boundaries agree (and it panics on shorter keys
        // exactly like Go).
        return key[..CONSOLE_LOG_TIMESTAMP_SHORT_WIDTH as usize].to_string();
    }
    key.to_string()
}

/// ConsoleLogsPane is a collapsible, scrollable panel that displays console log
/// output at the bottom of the main content area.
///
/// It supports animated expand/collapse via [`AnimatedValue`], virtual
/// scrolling over wrapped log entries, auto-scroll to follow new output,
/// and manual navigation (up/down/page-up/page-down) that freezes
/// auto-scroll when the user moves away from the tail.
#[derive(Debug, Clone)]
pub struct ConsoleLogsPane {
    // PARITY: Go holds a `*AnimatedValue` built by the caller; run.go and
    // runfocus.go reach through it (`consoleLogsPane.animState`), so the
    // single-threaded port owns it as a pub(crate) field
    // (CONCURRENCY.md §2.6 — the pointer sharing is main-thread-only).
    pub(crate) anim_state: AnimatedValue,

    logs: Vec<KeyValuePair>,

    /// cursor is the selected log index (logical row).
    cursor: isize,
    /// top is the first visible log index.
    top: isize,

    active: bool,
    auto_scroll: bool,

    /// Cached layout params from the most recent [`Self::view`] call, used by
    /// navigation methods (PageUp/PageDown) to compute page boundaries
    /// without re-deriving the layout.
    last_value_width: isize,
    last_content_lines: isize,
}

impl ConsoleLogsPane {
    /// NewConsoleLogsPane returns a collapsed ConsoleLogsPane with auto-scroll enabled.
    pub fn new(anim_state: AnimatedValue) -> Self {
        ConsoleLogsPane {
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

    /// Height returns the current rendered height (may be mid-animation).
    pub fn height(&self) -> isize {
        self.anim_state.value()
    }

    /// IsVisible reports whether the bar occupies any screen space.
    pub fn is_visible(&self) -> bool {
        self.anim_state.is_visible()
    }

    /// IsAnimating reports whether an expand/collapse animation is in progress.
    pub fn is_animating(&self) -> bool {
        self.anim_state.is_animating()
    }

    /// IsExpanded reports whether the bar is stably at its expanded height.
    pub fn is_expanded(&self) -> bool {
        self.anim_state.is_expanded()
    }

    /// Toggle initiates an expand or collapse animation.
    pub fn toggle(&mut self) {
        self.anim_state.toggle();
    }

    /// Update advances the animation by one frame. Returns true when complete.
    pub fn update(&mut self, now: Instant) -> bool {
        self.anim_state.update(now)
    }

    /// Active reports whether the bottom bar currently holds keyboard focus.
    pub fn active(&self) -> bool {
        self.active
    }

    /// SetActive sets whether the bottom bar holds keyboard focus.
    pub fn set_active(&mut self, active: bool) {
        self.active = active;
    }

    /// SetExpandedHeight sets the expanded height, clamped to
    /// [`CONSOLE_LOGS_PANE_MIN_HEIGHT`].
    pub fn set_expanded_height(&mut self, h: isize) {
        self.anim_state
            .set_expanded(h.max(CONSOLE_LOGS_PANE_MIN_HEIGHT));
    }

    /// UpdateExpandedHeight recalculates the expanded height from the terminal
    /// height using [`CONSOLE_LOGS_PANE_HEIGHT_RATIO`].
    pub fn update_expanded_height(&mut self, max_terminal_height: isize) {
        let max_height = (max_terminal_height as f64 * CONSOLE_LOGS_PANE_HEIGHT_RATIO) as isize;
        self.set_expanded_height(max_height);
    }

    /// SetConsoleLogs replaces the displayed log entries and adjusts the
    /// viewport. If auto-scroll is enabled, the view snaps to the tail.
    // PARITY: Go takes a slice alias; the port takes ownership — callers
    // clone at the boundary (PORTING.md append-aliasing rule).
    pub fn set_console_logs(&mut self, items: Vec<KeyValuePair>) {
        self.logs = items;

        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            self.auto_scroll = true;
            return;
        }

        self.cursor = clamp(self.cursor, 0, self.logs.len() as isize - 1);
        self.top = clamp(self.top, 0, self.logs.len() as isize - 1);

        if self.auto_scroll {
            self.scroll_to_end_inner();
        } else {
            self.ensure_cursor_visible();
        }
    }

    /// View renders the console logs pane at the given width.
    ///
    /// Returns an empty block when the pane is collapsed or the width is
    /// insufficient. The rendered output includes the border, header with
    /// range indicator, and wrapped/truncated log content.
    ///
    /// `dark` resolves adaptive colors (Go reads the `darkBackground`
    /// global; the port passes it explicitly, see the layout module doc).
    pub fn view(&mut self, width: isize, run_label: &str, hint: &str, dark: bool) -> Text<'static> {
        let h = self.height();
        if width <= 0 || h < CONSOLE_LOGS_PANE_MIN_HEIGHT {
            // PARITY: Go returns ""; the port's empty marker is a Text with
            // no lines.
            return Text::default();
        }

        let inner_h = h - CONSOLE_LOGS_PADDING_LINES;
        let content_lines = (inner_h - CONSOLE_LOGS_HEADER_LINES).max(1);

        // Reserve ContentPadding on each side: PaddingLeft on line styles
        // handles the left inset; we leave the right column free.
        let content_w = (width - CONTENT_PADDING).max(0);
        let mut max_key_width = ((content_w as f64 * CONSOLE_LOGS_KEY_WIDTH_RATIO) as isize).max(1);
        max_key_width = max_key_width.min((content_w - 2).max(1));
        let max_value_width = (content_w - max_key_width - 1).max(1);

        self.last_value_width = max_value_width;
        self.last_content_lines = content_lines;

        if self.auto_scroll {
            self.scroll_to_end_inner();
        } else {
            self.ensure_cursor_visible();
        }

        let end = self.visible_end(self.top, max_value_width, content_lines);

        let header = self.render_header(
            content_w,
            run_label,
            self.top,
            end,
            self.logs.len() as isize,
            dark,
        );
        let content = self.render_content(
            max_key_width,
            max_value_width,
            content_lines,
            self.top,
            end,
            hint,
            dark,
        );

        let body = join_vertical(LEFT, vec![header, content]);
        place(width as i64, inner_h as i64, LEFT, TOP, body)
    }

    /// HasData reports whether the pane has any log entries to display.
    pub fn has_data(&self) -> bool {
        !self.logs.is_empty()
    }

    /// renderHeader returns the "Console Logs • <runLabel>     [X-Y of N]" line,
    fn render_header(
        &self,
        width: isize,
        run_label: &str,
        start_idx: isize,
        end_idx: isize,
        total: isize,
        dark: bool,
    ) -> Text<'static> {
        let title = console_logs_pane_header_style(dark).render(CONSOLE_LOGS_PANE_HEADER);
        let nav_info =
            nav_info_style(dark).render(&self.build_navigation_info(start_idx, end_idx, total));

        let mut left = title.clone();
        if !run_label.is_empty() {
            let sep = " • ";
            let max_run_width = width
                - block_width(&title) as isize
                - block_width(&nav_info) as isize
                - text_width(sep) as isize;
            if max_run_width > 0 {
                left = join_horizontal(
                    LEFT,
                    vec![
                        title,
                        nav_info_style(dark).render(&format!(
                            "{sep}{}",
                            truncate_value(run_label, max_run_width)
                        )),
                    ],
                );
            }
        }

        let filler_width = width - block_width(&left) as isize - block_width(&nav_info) as isize;
        let filler = " ".repeat(filler_width.max(0) as usize);
        join_horizontal(LEFT, vec![left, text_from_str(&filler), nav_info])
    }

    /// buildNavigationInfo formats the "[X-Y of N]" range indicator.
    fn build_navigation_info(&self, start_idx: isize, end_idx: isize, total: isize) -> String {
        if total == 0 {
            return String::new();
        }
        format!(" [{}-{} of {}]", start_idx + 1, end_idx, total)
    }

    /// renderContent builds the visible log lines, padding with blank lines
    /// if the content doesn't fill the available space.
    #[allow(clippy::too_many_arguments)] // PARITY: mirrors the Go signature (+dark).
    fn render_content(
        &self,
        max_key_width: isize,
        max_value_width: isize,
        content_lines: isize,
        start_idx: isize,
        end_idx: isize,
        hint: &str,
        dark: bool,
    ) -> Text<'static> {
        if content_lines <= 0 {
            // PARITY: Go returns "" (empty Text marker).
            return Text::default();
        }
        if self.logs.is_empty() {
            let hint = if hint.is_empty() { "No data." } else { hint };
            if content_lines <= 1 {
                return console_logs_pane_timestamp_style(dark).render(hint);
            }
            return console_logs_pane_timestamp_style(dark).render(&format!(
                "{hint}{}",
                "\n".repeat(content_lines as usize - 1)
            ));
        }

        let start_idx = clamp(start_idx, 0, self.logs.len() as isize - 1);
        let end_idx = clamp(end_idx, start_idx, self.logs.len() as isize);

        let mut out: Vec<Text<'static>> = Vec::new();
        let mut used: isize = 0;

        let mut i = start_idx;
        while i < end_idx && used < content_lines {
            let remaining = content_lines - used;
            let (entry, lines) = self.render_entry(
                &self.logs[i as usize],
                i == self.cursor && self.active,
                max_key_width,
                max_value_width,
                remaining,
                dark,
            );
            out.push(entry);
            used += lines;
            i += 1;
        }

        while used < content_lines {
            out.push(text_from_str(""));
            used += 1;
        }

        join_vertical(LEFT, out)
    }

    /// renderEntry renders a single log entry, wrapping the value and showing
    /// the timestamp key only on the first line. If the entry exceeds maxLines,
    /// it is truncated with an ellipsis.
    fn render_entry(
        &self,
        item: &KeyValuePair,
        highlighted: bool,
        max_key_width: isize,
        max_value_width: isize,
        max_lines: isize,
        dark: bool,
    ) -> (Text<'static>, isize) {
        let mut key_style = console_logs_pane_timestamp_style(dark);
        let mut value_style = console_logs_pane_value_style(dark);
        if highlighted {
            key_style = console_logs_pane_highlighted_timestamp_style(dark);
            value_style = console_logs_pane_highlighted_value_style(dark);
        }

        let key = console_log_key_for_width(&item.key, max_key_width, &key_style);
        let mut lines = wrap_text(&item.value, max_value_width);

        let mut truncated = false;
        if lines.len() as isize > max_lines {
            lines.truncate(max_lines.max(0) as usize);
            truncated = true;
        }
        if truncated && !lines.is_empty() {
            let last = lines.len() - 1;
            lines[last] = with_ellipsis(&lines[last], max_value_width);
        }

        let mut rendered: Vec<Text<'static>> = Vec::new();
        for (i, v) in lines.iter().enumerate() {
            let k = if i == 0 {
                key_style.width(max_key_width as i64).render(&key)
            } else {
                key_style.width(max_key_width as i64).render("")
            };

            if highlighted {
                let gap = console_logs_pane_highlighted_value_style(dark).render(" ");
                rendered.push(concat_blocks(vec![
                    k,
                    gap,
                    value_style.width(max_value_width as i64).render(v),
                ]));
            } else {
                rendered.push(concat_blocks(vec![
                    k,
                    text_from_str(" "),
                    value_style.render(v),
                ]));
            }
        }

        if rendered.is_empty() {
            let k = key_style.width(max_key_width as i64).render(&key);
            rendered = vec![concat_blocks(vec![
                k,
                text_from_str(" "),
                value_style.width(max_value_width as i64).render(""),
            ])];
        }

        let count = rendered.len() as isize;
        (join_blocks_with_newlines(rendered), count)
    }

    // ---- Navigation ----

    /// Up moves the cursor one entry toward the top, wrapping to the last
    /// entry when at the beginning.
    pub fn up(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.cursor == 0 {
            self.cursor = self.logs.len() as isize - 1;
            self.scroll_to_end_inner();
        } else {
            self.cursor -= 1;
            self.ensure_cursor_visible();
        }
        self.update_auto_scroll();
    }

    /// Down moves the cursor one entry toward the bottom, wrapping to the
    /// first entry when at the end.
    pub fn down(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.cursor == self.logs.len() as isize - 1 {
            self.cursor = 0;
            self.top = 0;
        } else {
            self.cursor += 1;
            self.ensure_cursor_visible();
        }
        self.update_auto_scroll();
    }

    /// PageDown advances the viewport by one screenful, wrapping to the top
    /// when past the end.
    pub fn page_down(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.last_content_lines <= 0 || self.last_value_width <= 0 {
            self.down();
            return;
        }

        let end = self.visible_end(self.top, self.last_value_width, self.last_content_lines);
        if end >= self.logs.len() as isize {
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

    /// PageUp moves the viewport back by one screenful, wrapping to the end
    /// when before the start.
    pub fn page_up(&mut self) {
        if self.logs.is_empty() {
            return;
        }
        if self.last_content_lines <= 0 || self.last_value_width <= 0 {
            self.up();
            return;
        }

        if self.top == 0 {
            self.cursor = self.logs.len() as isize - 1;
            self.scroll_to_end_inner();
            self.update_auto_scroll();
            return;
        }

        let mut new_top = self.top;
        let mut used: isize = 0;
        while new_top > 0 && used < self.last_content_lines {
            let prev = new_top - 1;
            let h = wrapped_line_count(&self.logs[prev as usize].value, self.last_value_width);
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

    /// ScrollToEnd snaps the viewport to show the last log entry and
    /// re-enables auto-scroll.
    pub fn scroll_to_end(&mut self) {
        self.auto_scroll = true;
        self.scroll_to_end_inner();
    }

    /// ScrollToStart snaps the viewport to the first log entry and
    /// disables auto-scroll.
    pub fn scroll_to_start(&mut self) {
        self.cursor = 0;
        self.top = 0;
        self.auto_scroll = self.logs.is_empty();
    }

    // ---- Internal scrolling ----

    /// updateAutoScroll enables auto-scroll when the cursor is on the last
    /// entry, and disables it otherwise.
    fn update_auto_scroll(&mut self) {
        if self.logs.is_empty() {
            self.auto_scroll = true;
            return;
        }
        if self.cursor == self.logs.len() as isize - 1 {
            self.auto_scroll = true;
            self.scroll_to_end_inner();
            return;
        }
        self.auto_scroll = false;
    }

    /// ensureCursorVisible adjusts top so that the cursor entry is within the
    /// visible window.
    fn ensure_cursor_visible(&mut self) {
        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            return;
        }

        self.cursor = clamp(self.cursor, 0, self.logs.len() as isize - 1);
        self.top = clamp(self.top, 0, self.logs.len() as isize - 1);

        if self.cursor < self.top {
            self.top = self.cursor;
            return;
        }

        while self.cursor
            >= self.visible_end(self.top, self.last_value_width, self.last_content_lines)
            && self.top < self.logs.len() as isize - 1
        {
            self.top += 1;
        }
    }

    /// scrollToEnd positions the viewport so the last entry is at the bottom.
    // Go: `scrollToEnd` (unexported; `_inner` avoids colliding with the
    // exported ScrollToEnd → scroll_to_end above).
    fn scroll_to_end_inner(&mut self) {
        if self.logs.is_empty() {
            self.cursor = 0;
            self.top = 0;
            return;
        }
        self.cursor = self.logs.len() as isize - 1;

        if self.last_content_lines <= 0 || self.last_value_width <= 0 {
            self.top = self.cursor;
            return;
        }

        let mut top = self.cursor;
        let mut used = wrapped_line_count(&self.logs[top as usize].value, self.last_value_width)
            .min(self.last_content_lines);

        while top > 0 && used < self.last_content_lines {
            let prev = top - 1;
            let h = wrapped_line_count(&self.logs[prev as usize].value, self.last_value_width);
            if used + h > self.last_content_lines {
                break;
            }
            used += h;
            top = prev;
        }

        self.top = top;
    }

    /// visibleEnd returns the exclusive end index of log entries that fit
    /// within contentLines screen rows starting from startIdx, accounting
    /// for line wrapping.
    fn visible_end(&self, start_idx: isize, max_value_width: isize, content_lines: isize) -> isize {
        if self.logs.is_empty() {
            return 0;
        }
        let start_idx = clamp(start_idx, 0, self.logs.len() as isize - 1);

        let mut used: isize = 0;
        let mut i = start_idx;
        while i < self.logs.len() as isize && used < content_lines {
            let remaining = content_lines - used;
            let h = wrapped_line_count(&self.logs[i as usize].value, max_value_width);
            used += h.min(remaining);
            i += 1;
        }
        i
    }
}

// ---- Text utilities ----

/// WithEllipsis truncates line so that the visible width including a
/// trailing "..." marker fits within maxWidth.
pub fn with_ellipsis(line: &str, max_width: isize) -> String {
    const MARKER: &str = "...";
    // PARITY: Go measures with runewidth.StringWidth (per-rune sum);
    // identical to lipgloss.Width for this ASCII constant.
    let mw = rune_string_width(MARKER) as isize;
    if max_width <= mw {
        return MARKER[..max_width.max(0) as usize].to_string();
    }

    let target = max_width - mw;
    let mut b = String::new();
    let mut w: isize = 0;
    for r in line.chars() {
        let rw = rune_width(r) as isize;
        if w + rw > target {
            break;
        }
        b.push(r);
        w += rw;
    }
    b.push_str(MARKER);
    b
}

/// wrappedLineCount counts how many screen lines text occupies when
/// soft-wrapped at maxWidth. Embedded newlines are respected.
fn wrapped_line_count(text: &str, max_width: isize) -> isize {
    if max_width <= 0 {
        return 1;
    }
    let mut total: isize = 0;
    for p in text.split('\n') {
        // PARITY: Go measures with runewidth.StringWidth (per-rune sum),
        // matching wrap_single_line's chunking loop — NOT lipgloss.Width.
        let w = rune_string_width(p) as isize;
        if w == 0 {
            total += 1;
            continue;
        }
        total += (w + max_width - 1) / max_width;
    }
    total.max(1)
}

/// WrapText soft-wraps text into multiple lines at maxWidth, preserving
/// embedded newlines.
pub fn wrap_text(text: &str, max_width: isize) -> Vec<String> {
    if max_width <= 0 {
        return vec![text.to_string()];
    }

    let mut out: Vec<String> = Vec::new();
    for part in text.split('\n') {
        out.extend(wrap_single_line(part, max_width));
    }
    // PARITY: dead in practice (split yields ≥ 1 part and wrapSingleLine
    // returns ≥ 1 line), ported from Go anyway.
    if out.is_empty() {
        return vec![String::new()];
    }
    out
}

/// wrapSingleLine breaks a single line (no embedded newlines) into
/// chunks that each fit within maxWidth display columns.
fn wrap_single_line(s: &str, max_width: isize) -> Vec<String> {
    // PARITY: Go measures with runewidth.StringWidth (per-rune sum),
    // matching the chunking loop below — NOT lipgloss.Width.
    if rune_string_width(s) as isize <= max_width {
        return vec![s.to_string()];
    }

    let runes: Vec<char> = s.chars().collect();
    let mut lines: Vec<String> = Vec::new();

    let mut start = 0usize;
    while start < runes.len() {
        let mut w: isize = 0;
        let mut end = start;
        while end < runes.len() {
            let rw = rune_width(runes[end]) as isize;
            if w + rw > max_width && end > start {
                break;
            }
            w += rw;
            end += 1;
            if w >= max_width {
                break;
            }
        }
        lines.push(runes[start..end].iter().collect());
        start = end;
    }

    lines
}

// ---- Port-local helpers ----

/// `runewidth.RuneWidth` through the width shim (PORTING.md: only the shim
/// measures; a lone char is a single-cluster string).
fn rune_width(r: char) -> usize {
    let mut buf = [0u8; 4];
    grapheme_width(r.encode_utf8(&mut buf))
}

/// `runewidth.StringWidth`: the per-rune width sum, with no grapheme
/// clustering (go-runewidth condition.StringWidth sums `RuneWidth` over
/// runes). Used where Go's wrap helpers do, keeping the line COUNT
/// consistent with the per-rune chunking in [`wrap_single_line`].
fn rune_string_width(s: &str) -> usize {
    s.chars().map(rune_width).sum()
}

// PARITY: Go's clamp lives in config.go:322-330; it has no shared Rust
// home yet, so it is duplicated privately (flex_layout.rs and
// leet-data::config do the same).
fn clamp(val: isize, minimum: isize, maximum: isize) -> isize {
    if val < minimum {
        return minimum;
    }
    if val > maximum {
        return maximum;
    }
    val
}

// PARITY: Go's truncateValue lives in runoverviewsidebar.go:295-312; that
// module is not yet ported, so the helper is duplicated privately here.
// The run_overview_sidebar port owns the canonical copy — keep in sync.
/// truncateValue truncates string values that do not fit into available width.
fn truncate_value(value: &str, max_width: isize) -> String {
    if text_width(value) as isize <= max_width {
        return value.to_string();
    }
    if max_width <= 3 {
        return "...".to_string();
    }

    let available = max_width - 4;
    let mut w: isize = 0;
    for (i, r) in value.char_indices() {
        let rw = rune_width(r) as isize;
        if w + rw > available {
            return format!("{}...", &value[..i]);
        }
        w += rw;
    }
    format!("{value}...")
}

/// Go string concatenation (`k + " " + value`) on rendered blocks: the last
/// line of the accumulator merges with the first line of the next block
/// (all blocks here are single-line in practice).
fn concat_blocks(blocks: Vec<Text<'static>>) -> Text<'static> {
    let mut lines: Vec<Line<'static>> = vec![Line::default()];
    for block in blocks {
        let mut block_lines = block.lines;
        if block_lines.is_empty() {
            // Go "" contributes nothing.
            continue;
        }
        let first = block_lines.remove(0);
        lines
            .last_mut()
            .expect("seeded with one line")
            .spans
            .extend(first.spans);
        lines.append(&mut block_lines);
    }
    Text::from(lines)
}

/// Go `strings.Join(rendered, "\n")` on rendered blocks.
fn join_blocks_with_newlines(blocks: Vec<Text<'static>>) -> Text<'static> {
    let mut lines: Vec<Line<'static>> = Vec::new();
    for block in blocks {
        if block.lines.is_empty() {
            // Go "" is one empty line.
            lines.push(Line::default());
        } else {
            lines.extend(block.lines);
        }
    }
    Text::from(lines)
}

// Transliteration of `consolelogspane_test.go` (PORTING.md testing
// conventions; `stripANSI(...)` maps to `text_to_string` — the port's
// spans carry styles out-of-band, so plain content IS the stripped text).
#[cfg(test)]
mod tests {
    use std::time::Duration;

    use leet_charts::styles::ANIMATION_DURATION;

    use super::*;
    use crate::layout::text_to_string;

    fn expand_console_logs_pane(clp: &mut ConsoleLogsPane, height: isize) {
        clp.set_expanded_height(height);
        clp.toggle();

        // Complete the animation deterministically (no sleep).
        clp.update(Instant::now() + ANIMATION_DURATION + Duration::from_millis(1));

        assert!(clp.is_expanded(), "bottom bar should be expanded");
        assert!(
            !clp.is_animating(),
            "bottom bar animation should be complete"
        );
        assert_eq!(
            clp.height(),
            height,
            "expanded bottom bar height should match"
        );
    }

    fn make_logs(n: usize) -> Vec<KeyValuePair> {
        (0..n)
            .map(|i| KeyValuePair {
                key: format!("t{:02}", i + 1),
                value: format!("log {:02}", i + 1),
                ..Default::default()
            })
            .collect()
    }

    /// stripANSI(clp.View(w, runLabel, hint)) — `dark` is arbitrary for
    /// plain-text assertions.
    fn view_plain(clp: &mut ConsoleLogsPane, width: isize, run_label: &str, hint: &str) -> String {
        text_to_string(&clp.view(width, run_label, hint, true))
    }

    #[test]
    fn auto_scroll_freezes_when_user_scrolls_up() {
        let mut clp = ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
        expand_console_logs_pane(&mut clp, 5); // header + padding + 3 content lines

        clp.set_console_logs(make_logs(10));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[8-10 of 10]"),
            "should auto-scroll to the end initially"
        );

        // User scrolls off the last line -> autoScroll should turn off.
        clp.up();

        // New logs arrive: view should NOT jump to show the new end.
        clp.set_console_logs(make_logs(11));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[8-10 of 11]"),
            "should not jump to end when autoScroll is disabled"
        );

        // Explicit scroll-to-end should re-enable auto-scroll.
        clp.scroll_to_end();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[9-11 of 11]"),
            "ScrollToEnd should jump back to the end"
        );
    }

    #[test]
    fn scroll_to_start_jumps_to_first_and_freezes_autoscroll() {
        let mut clp = ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
        expand_console_logs_pane(&mut clp, 4); // header + padding + 2 content lines

        clp.set_console_logs(make_logs(5));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[4-5 of 5]"),
            "auto-scroll lands at the end initially"
        );

        clp.scroll_to_start();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[1-2 of 5]"),
            "ScrollToStart should show first logs"
        );

        // New logs arriving must not jump to the end — autoscroll is off.
        clp.set_console_logs(make_logs(8));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[1-2 of 8]"),
            "autoscroll stays disabled after ScrollToStart"
        );
    }

    #[test]
    fn page_up_down_wraps_around() {
        let mut clp = ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
        expand_console_logs_pane(&mut clp, 4); // header + padding + 2 content lines

        clp.set_console_logs(make_logs(5));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[4-5 of 5]"),
            "should start at end when auto-scroll is on"
        );

        // PageDown from the end should wrap to the top.
        clp.page_down();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[1-2 of 5]"),
            "PageDown at end should wrap to start"
        );

        // PageUp from the top should wrap back to the end.
        clp.page_up();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[4-5 of 5]"),
            "PageUp at start should wrap to end"
        );
    }

    #[test]
    fn wrap_text_preserves_newlines_and_wraps() {
        struct Case {
            name: &'static str,
            text: &'static str,
            max_width: isize,
            want: &'static [&'static str],
        }
        let tests = [
            Case {
                name: "short single line",
                text: "hello",
                max_width: 10,
                want: &["hello"],
            },
            Case {
                name: "wrap at boundary",
                text: "abcdefghij",
                max_width: 5,
                want: &["abcde", "fghij"],
            },
            Case {
                name: "embedded newline",
                text: "abc\ndef",
                max_width: 10,
                want: &["abc", "def"],
            },
            Case {
                name: "wrap plus newline",
                text: "abcdefghij\nxy",
                max_width: 5,
                want: &["abcde", "fghij", "xy"],
            },
            Case {
                name: "empty string",
                text: "",
                max_width: 10,
                want: &[""],
            },
            Case {
                name: "zero width returns original",
                text: "abc",
                max_width: 0,
                want: &["abc"],
            },
        ];

        for tt in tests {
            let got = wrap_text(tt.text, tt.max_width);
            assert_eq!(got, tt.want, "{}", tt.name);
        }
    }

    /// Port-local regression (no Go counterpart): wrappedLineCount and
    /// WrapText must share the per-rune runewidth metric. "⚠️" (U+26A0
    /// U+FE0F) sums to 1 per rune (⚠=1, VS16=0) but measures 2 under the
    /// grapheme-aware lipgloss metric; mixing metrics made the viewport
    /// line count disagree with what render_entry actually wraps.
    #[test]
    fn wrapped_line_count_matches_wrap_text_for_vs16_clusters() {
        let text = "\u{26A0}\u{FE0F} hot"; // per-rune width 5, grapheme width 6

        // Fits on one line at width 5 (Go: runewidth.StringWidth == 5).
        assert_eq!(wrap_text(text, 5), vec![text.to_string()]);
        assert_eq!(wrapped_line_count(text, 5), 1);

        // Wraps into two chunks at width 3, and the count agrees.
        assert_eq!(
            wrap_text(text, 3),
            vec!["\u{26A0}\u{FE0F} h".to_string(), "ot".to_string()]
        );
        assert_eq!(wrapped_line_count(text, 3), 2);
    }

    #[test]
    fn with_ellipsis_truncates_to_width() {
        struct Case {
            name: &'static str,
            line: &'static str,
            max_width: isize,
            want: &'static str,
        }
        let tests = [
            Case {
                name: "fits without truncation marker",
                line: "hello world! this is long",
                max_width: 10,
                want: "hello w...",
            },
            Case {
                name: "exactly marker width",
                line: "hello",
                max_width: 3,
                want: "...",
            },
            Case {
                name: "below marker width",
                line: "hello",
                max_width: 2,
                want: "..",
            },
            Case {
                name: "empty line",
                line: "",
                max_width: 10,
                want: "...",
            },
        ];

        for tt in tests {
            let got = with_ellipsis(tt.line, tt.max_width);
            assert_eq!(got, tt.want, "{}", tt.name);
        }
    }

    #[test]
    fn down_cycles_and_wraps() {
        let mut clp = ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
        expand_console_logs_pane(&mut clp, 5); // border + header + 3 content lines

        clp.set_console_logs(make_logs(5));
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[3-5 of 5]"),
            "initial view should auto-scroll to end"
        );

        // Move Down from last entry should wrap to first.
        clp.down();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[1-3 of 5]"),
            "Down from last should wrap to first entry"
        );

        // Continue Down through entries.
        clp.down();
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[1-3 of 5]"),
            "second Down should stay on page"
        );

        // Down until we reach the last entry again (auto-scroll re-enables).
        for _ in 0..3 {
            clp.down();
        }
        let out = view_plain(&mut clp, 80, "", "");
        assert!(
            out.contains("[3-5 of 5]"),
            "reaching last entry should re-enable auto-scroll"
        );
    }

    #[test]
    fn down_empty_logs() {
        let mut clp = ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
        expand_console_logs_pane(&mut clp, 5);

        // Down on empty logs should be a no-op.
        clp.down();
        let out = clp.view(80, "", "", true);
        assert!(
            !text_to_string(&out).is_empty(),
            "view should render (empty content area)"
        );
    }

    #[test]
    fn timestamp_adapts_to_available_width() {
        struct Case {
            name: &'static str,
            width: isize,
            want_full: bool,
            want_minutes: bool,
        }
        let tests = [
            Case {
                name: "enough_space_shows_hhmmss",
                width: 80, // int(80*0.12)=9 -> enough room after padding for 8 chars
                want_full: true,
                want_minutes: false,
            },
            Case {
                name: "narrow_truncates_to_hhmm",
                width: 70, // int(70*0.12)=8 -> NOT enough after padding for 8 chars
                want_full: false,
                want_minutes: true,
            },
            Case {
                name: "very_narrow_hides_timestamp",
                width: 30, // int(30*0.12)=3 -> too small even for HH:MM
                want_full: false,
                want_minutes: false,
            },
        ];

        for tt in tests {
            let mut clp =
                ConsoleLogsPane::new(AnimatedValue::new(false, CONSOLE_LOGS_PANE_MIN_HEIGHT));
            expand_console_logs_pane(&mut clp, 4); // minimum height: border + header + 1 content line

            clp.set_console_logs(vec![KeyValuePair {
                key: "10:11:12".to_string(),
                value: "hello".to_string(),
                ..Default::default()
            }]);

            let out = view_plain(&mut clp, tt.width, "", "");
            assert!(
                out.contains("hello"),
                "{}: log content should still render",
                tt.name
            );

            if tt.want_full {
                assert!(out.contains("10:11:12"), "{}", tt.name);
            } else if tt.want_minutes {
                assert!(out.contains("10:11"), "{}", tt.name);
                assert!(!out.contains("10:11:12"), "{}", tt.name);
                assert!(
                    !out.contains("..."),
                    "{}: timestamps should not use ellipsis truncation",
                    tt.name
                );
                assert!(
                    !out.contains("10:11:"),
                    "{}: should not show partial seconds",
                    tt.name
                );
            } else {
                assert!(!out.contains("10:11:12"), "{}", tt.name);
                assert!(!out.contains("10:11"), "{}", tt.name);
                assert!(
                    !out.contains("..."),
                    "{}: hidden timestamps should not use ellipsis",
                    tt.name
                );
            }
        }
    }
}
