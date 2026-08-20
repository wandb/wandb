//! The lipgloss layout subset leet uses, over ratatui text types.
//!
//! Port of exactly the `charm.land/lipgloss/v2` surface called by
//! `core/internal/leet` (all cites below are relative to
//! `core/vendor/charm.land/lipgloss/v2/`):
//!
//! - `join.go`: [`join_horizontal`] / [`join_vertical`] with lipgloss's
//!   exact padding arithmetic (shorter blocks padded with UNSTYLED spaces
//!   at position-dependent offsets, `math.Round` on fractional positions).
//! - `position.go`: [`Position`] + [`place`] / [`place_horizontal`] /
//!   [`place_vertical`]. leet never passes `WhitespaceOption`s, so the
//!   whitespace fill is always unstyled `' '` runs (whitespace.go:25-58).
//! - `style.go` render path: [`GoStyle`] — a builder mirroring exactly the
//!   `lipgloss.Style` methods leet calls (grepped over
//!   `core/internal/leet/*.go`): `Bold`, `Foreground`, `Background`,
//!   `Width`, `Height`, `Padding`, `PaddingLeft`, `PaddingBottom`,
//!   `MarginLeft`, `MarginTop`, `MarginBottom`, `MaxWidth`, `MaxHeight`,
//!   `Border`, `BorderStyle`, `BorderForeground` (1-arg form),
//!   `BorderTop/Right/Bottom/Left`, `Render`. NOT ported (unused by leet):
//!   `Italic`, `Faint`, `Underline`, `Reverse`, `Blink`, `Align*`
//!   (alignment stays at the lipgloss default Left/Top), `Inline`,
//!   `MarginRight`, `MarginBackground`, `PaddingChar`/`MarginChar`,
//!   `TabWidth` (default 4 applies), `Transform`, `SetString`/`Inherit`,
//!   hyperlinks, `UnderlineSpaces`/`StrikethroughSpaces`,
//!   `BorderBackground`, `BorderForegroundBlend`, and the `Middle*` border
//!   pieces (no leet call site reaches them).
//! - `borders.go`: [`BorderChars`] with the exact rune sets of
//!   `NormalBorder`/`RoundedBorder`/`ThickBorder`, plus `applyBorder`'s
//!   corner-defaulting/suppression rules.
//! - `align.go` / `wrap.go` (+ `x/ansi` `Wrap`/`Truncate`): the internal
//!   helpers `Style.Render` goes through.
//!
//! Also hosts the `styles.go` STYLE OBJECTS (the named `*Style` vars,
//! styles.go:530-817) as [`GoStyle`] constructor fns — colors come from
//! `leet_charts::styles`; adaptive colors are resolved eagerly via the
//! `dark` parameter (the port has no `darkBackground` global, see
//! CONCURRENCY.md S13 / leet-charts styles.rs) — and the string helpers
//! `renderHorizontalSeparator`/`joinWithSeparators` (styles.go:757-776).
//!
//! Tier-2 parity contract: padding/fill cells are UNSTYLED spaces exactly
//! where lipgloss leaves them unstyled. lipgloss styles whitespace with
//! `teWhitespace`, which carries ONLY the style's background color
//! (style.go:379-385; foreground would require `Reverse`, unused) — so
//! fill spans here are `Style::default()` unless a background is set.
//!
//! PARITY: Go lipgloss operates on ANSI strings; this port operates on
//! `ratatui::text` spans. Styling "already styled" content maps to
//! `Style::patch` (outer style fills only fields the span leaves unset);
//! leet only ever applies colored styles to plain text and colorless
//! container styles to pre-styled content, where the two models agree.
//! `Line`/`Text`-level styles on inputs are ignored (Go strings have no
//! equivalent); build inputs span-styled. Inputs must not embed `\n` /
//! `\r\n` inside spans: `Text` carries line structure in `lines`, so the
//! `\r\n` → `\n` fold of Go `getLines` (get.go:631) has no span-model
//! equivalent — [`text_from_str`] applies it for string inputs. The
//! tab → 4-space half of `getLines` (get.go:630) IS re-applied at every
//! join/place boundary, exactly where Go re-applies it (see
//! [`get_lines`](self) / `convert_tabs`).
//
// Derived from charmbracelet/lipgloss (https://github.com/charmbracelet/lipgloss),
// vendored at core/vendor/charm.land/lipgloss/v2.
// lipgloss - Copyright (c) 2021-2026 Charmbracelet, Inc.
// Used under the MIT License (see LICENSE in the vendored tree).

use leet_charts::styles::{
    AdaptiveColor, COLOR_ACCENT, COLOR_DARK, COLOR_HEADING, COLOR_ITEM_KEY, COLOR_ITEM_VALUE,
    COLOR_LAYOUT, COLOR_LAYOUT_HIGHLIGHT, COLOR_SELECTED, COLOR_SELECTED_RUN_INACTIVE_STYLE,
    COLOR_SUBHEADING, COLOR_SUBTLE, COLOR_TEXT, CONTENT_PADDING, INSPECTION_LEGEND_BG,
    INSPECTION_LEGEND_FG, MOON900, Rgb, STATUS_BAR_PADDING, UNICODE_EM_DASH,
    get_odd_run_style_color, run_overview_tag_background_color, run_overview_tag_foreground_color,
};
use leet_data::width::{grapheme_width, text_width};
use ratatui::style::{Color, Modifier, Style};
use ratatui::text::{Line, Span, Text};

// ---------------------------------------------------------------------------
// Position (position.go:10-32).
// ---------------------------------------------------------------------------

/// A position along a horizontal or vertical axis: 0 is the start (left or
/// top), 1 the end (right or bottom). Go `lipgloss.Position` (float64).
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Position(pub f64);

/// position.go:26-32. `TOP`/`LEFT` and `BOTTOM`/`RIGHT` alias the same
/// values, as in Go.
pub const TOP: Position = Position(0.0);
/// See [`TOP`].
pub const BOTTOM: Position = Position(1.0);
/// See [`TOP`].
pub const CENTER: Position = Position(0.5);
/// See [`TOP`].
pub const LEFT: Position = Position(0.0);
/// See [`TOP`].
pub const RIGHT: Position = Position(1.0);

impl Position {
    /// position.go:21-23: clamp to [0, 1].
    fn value(self) -> f64 {
        // PARITY: Go `math.Min(1, math.Max(0, p))` propagates NaN, and so
        // does `f64::clamp`; leet only ever passes the constants anyway.
        self.0.clamp(0.0, 1.0)
    }
}

// ---------------------------------------------------------------------------
// Color plumbing.
// ---------------------------------------------------------------------------

/// A `leet_charts` [`Rgb`] as a ratatui [`Color`].
pub fn rgb_to_color(c: Rgb) -> Color {
    Color::Rgb(c.0, c.1, c.2)
}

/// An [`AdaptiveColor`] resolved for the given background and converted
/// (Go resolves lazily through the `darkBackground` global; the port
/// resolves eagerly at style construction).
pub fn adaptive_to_color(c: AdaptiveColor, dark: bool) -> Color {
    rgb_to_color(c.resolve(dark))
}

// ---------------------------------------------------------------------------
// Block/text helpers (get.go:628-643 getLines, size.go:15-31 Width/Height).
// ---------------------------------------------------------------------------

/// Converts a (possibly multi-line) Go-style string into a text block with
/// `getLines` normalization (get.go:630-633): tabs → 4 spaces, `\r\n` →
/// `\n`, then split on `\n`. Unlike `Text::raw`, a trailing `\n` yields a
/// trailing empty line, matching Go `strings.Split`.
pub fn text_from_str(s: &str) -> Text<'static> {
    let s = s.replace('\t', "    ").replace("\r\n", "\n");
    let lines: Vec<Line<'static>> = s
        .split('\n')
        .map(|l| {
            if l.is_empty() {
                Line::default()
            } else {
                Line::from(l.to_string())
            }
        })
        .collect();
    Text::from(lines)
}

/// The plain-text contents of a block: lines joined with `\n`. The inverse
/// of [`text_from_str`] for style-free content (used heavily by tests).
pub fn text_to_string(t: &Text<'_>) -> String {
    t.lines
        .iter()
        .map(|l| {
            l.spans
                .iter()
                .map(|s| s.content.as_ref())
                .collect::<String>()
        })
        .collect::<Vec<_>>()
        .join("\n")
}

/// Display width of one line: the sum of its spans' widths through the
/// `leet_data::width` shim (`ansi.StringWidth` in Go).
///
/// PARITY: a grapheme cluster split across span boundaries measures as its
/// parts; leet never splits clusters across spans.
pub fn line_width(line: &Line<'_>) -> usize {
    line.spans.iter().map(|s| text_width(&s.content)).sum()
}

/// `lipgloss.Width` (size.go:15-24): the widest line of the block.
pub fn block_width(t: &Text<'_>) -> usize {
    t.lines.iter().map(line_width).max().unwrap_or(0)
}

/// `lipgloss.Height` (size.go:26-31): the number of lines. A Go string
/// always has ≥ 1 line; pass blocks from [`text_from_str`] or the helpers
/// here, which maintain that invariant.
pub fn block_height(t: &Text<'_>) -> usize {
    t.lines.len()
}

/// Unstyled spaces (whitespace.go:25-58 with the default `" "` chars — the
/// only form leet reaches, as it never passes `WhitespaceOption`s).
fn sp(n: i64) -> String {
    if n <= 0 {
        String::new()
    } else {
        " ".repeat(n as usize)
    }
}

/// Appends a span, skipping empties (Go appends `""` freely; spans don't).
fn push_span(spans: &mut Vec<Span<'static>>, content: String, style: Style) {
    if content.is_empty() {
        return;
    }
    spans.push(Span::styled(content, style));
}

/// The `strings.Split` shape of Go `getLines` on an incoming block:
/// guarantee ≥ 1 line (Go `""` is one empty line). The `\r\n` → `\n` fold
/// (get.go:631) has no span-model equivalent — see the module-doc PARITY
/// note.
fn normalize_lines(t: Text<'static>) -> Vec<Line<'static>> {
    let mut lines = t.lines;
    if lines.is_empty() {
        lines.push(Line::default());
    }
    lines
}

/// The tab expansion of Go `getLines` (get.go:630): `\t` → 4 spaces in
/// every span. Go re-applies this to EVERY block at every JoinHorizontal /
/// JoinVertical / Place boundary, so blocks built outside
/// [`text_from_str`] get it here too.
fn convert_tabs(lines: &mut [Line<'static>]) {
    for line in lines {
        for span in &mut line.spans {
            if span.content.contains('\t') {
                span.content = span.content.replace('\t', "    ").into();
            }
        }
    }
}

/// Go `getLines` (get.go:628-643) on an incoming block: tabs → 4 spaces
/// and ≥ 1 line. Used where Go both measures AND emits the `getLines`
/// output (JoinHorizontal join.go:48-52, JoinVertical join.go:129-134,
/// PlaceHorizontal position.go:44).
fn get_lines(t: Text<'static>) -> Vec<Line<'static>> {
    let mut lines = normalize_lines(t);
    convert_tabs(&mut lines);
    lines
}

/// Display width of one line as `getLines` measures it: tabs expanded to
/// 4 spaces BEFORE measuring (get.go:630-638). Needed where Go measures
/// via `getLines` but emits the ORIGINAL string (PlaceVertical
/// position.go:100-105, PlaceHorizontal's no-op path position.go:47-49).
/// Identical to [`line_width`] on tab-free lines (a raw `\t` is a C0
/// control and measures 0).
fn line_width_tabs_expanded(line: &Line<'_>) -> usize {
    line.spans
        .iter()
        .map(|s| {
            if s.content.contains('\t') {
                text_width(&s.content.replace('\t', "    "))
            } else {
                text_width(&s.content)
            }
        })
        .sum()
}

// ---------------------------------------------------------------------------
// JoinHorizontal / JoinVertical (join.go).
// ---------------------------------------------------------------------------

/// `lipgloss.JoinHorizontal` (join.go:29-100): horizontally join blocks
/// along a vertical axis. `pos` 0 = top, 1 = bottom.
pub fn join_horizontal(pos: Position, blocks: Vec<Text<'static>>) -> Text<'static> {
    // join.go:30-35.
    if blocks.is_empty() {
        return text_from_str("");
    }
    if blocks.len() == 1 {
        return blocks.into_iter().next().expect("len checked");
    }

    // Break text blocks into lines and get max widths for each text block
    // (join.go:48-54, via getLines: tabs expand here).
    let mut blocks: Vec<Vec<Line<'static>>> = blocks.into_iter().map(get_lines).collect();
    let max_widths: Vec<i64> = blocks
        .iter()
        .map(|b| b.iter().map(line_width).max().unwrap_or(0) as i64)
        .collect();
    let max_height = blocks.iter().map(Vec::len).max().unwrap_or(0);

    // Add extra lines to make each side the same height (join.go:57-78).
    for block in &mut blocks {
        if block.len() >= max_height {
            continue;
        }
        let n = block.len().abs_diff(max_height);
        if pos.0 == TOP.0 {
            // join.go:63-64.
            block.extend(std::iter::repeat_with(Line::default).take(n));
        } else if pos.0 == BOTTOM.0 {
            // join.go:66-67.
            for _ in 0..n {
                block.insert(0, Line::default());
            }
        } else {
            // Somewhere in the middle (join.go:69-77): prepend
            // `split = round(n·pos)` empty lines, append the rest.
            let split = (n as f64 * pos.value()).round() as usize;
            let top = n - split;
            let bottom = n - top; // == split
            for _ in 0..(n - top) {
                block.insert(0, Line::default());
            }
            block.extend(std::iter::repeat_with(Line::default).take(n - bottom));
        }
    }

    // Merge lines (join.go:81-97). Every block's lines are padded to that
    // block's own max width — including the last block — with UNSTYLED
    // spaces (join.go:88: bare `strings.Repeat(" ", ...)`).
    let mut out: Vec<Line<'static>> = Vec::with_capacity(max_height);
    for i in 0..max_height {
        let mut spans: Vec<Span<'static>> = Vec::new();
        for (j, block) in blocks.iter_mut().enumerate() {
            let line = std::mem::take(&mut block[i]);
            let w = line_width(&line) as i64;
            spans.extend(line.spans);
            push_span(&mut spans, sp(max_widths[j] - w), Style::default());
        }
        out.push(Line::from(spans));
    }
    Text::from(out)
}

/// `lipgloss.JoinVertical` (join.go:115-171): vertically join blocks along
/// a horizontal axis. `pos` 0 = left, 1 = right.
pub fn join_vertical(pos: Position, blocks: Vec<Text<'static>>) -> Text<'static> {
    // join.go:116-121.
    if blocks.is_empty() {
        return text_from_str("");
    }
    if blocks.len() == 1 {
        return blocks.into_iter().next().expect("len checked");
    }

    // join.go:129-134, via getLines: tabs expand here.
    let blocks: Vec<Vec<Line<'static>>> = blocks.into_iter().map(get_lines).collect();
    let max_width = blocks
        .iter()
        .flat_map(|b| b.iter().map(line_width))
        .max()
        .unwrap_or(0) as i64;

    let mut out: Vec<Line<'static>> = Vec::new();
    for block in blocks {
        for line in block {
            let w = max_width - line_width(&line) as i64;
            let mut spans: Vec<Span<'static>> = Vec::new();
            if pos.0 == LEFT.0 {
                // join.go:143-145: every line right-padded to the block
                // width with unstyled spaces (trailing spaces included).
                spans.extend(line.spans);
                push_span(&mut spans, sp(w), Style::default());
            } else if pos.0 == RIGHT.0 {
                // join.go:147-149.
                push_span(&mut spans, sp(w), Style::default());
                spans.extend(line.spans);
            } else {
                // join.go:151-163. PARITY: for `w < 1` the line is emitted
                // unpadded, and the rounding remainder lands on the LEFT
                // (`left = w - (w - round(w·pos))`), unlike
                // `alignTextHorizontal` which puts it on the right.
                if w < 1 {
                    spans.extend(line.spans);
                } else {
                    let split = (w as f64 * pos.value()).round() as i64;
                    let right = w - split;
                    let left = w - right;
                    push_span(&mut spans, sp(left), Style::default());
                    spans.extend(line.spans);
                    push_span(&mut spans, sp(right), Style::default());
                }
            }
            out.push(Line::from(spans));
        }
    }
    Text::from(out)
}

// ---------------------------------------------------------------------------
// Place / PlaceHorizontal / PlaceVertical (position.go:34-136).
// ---------------------------------------------------------------------------

/// `lipgloss.Place` (position.go:36-38): place a block in an unstyled
/// `width`×`height` box.
pub fn place(
    width: i64,
    height: i64,
    h_pos: Position,
    v_pos: Position,
    text: Text<'static>,
) -> Text<'static> {
    place_vertical(height, v_pos, place_horizontal(width, h_pos, text))
}

/// `lipgloss.PlaceHorizontal` (position.go:43-83): place a block in an
/// unstyled box of the given width. No-op if the block is at least as wide
/// (position.go:47-49) — in that case shorter lines stay UNPADDED (and
/// tabs stay UNEXPANDED: Go returns `str`, not the getLines output).
pub fn place_horizontal(width: i64, pos: Position, text: Text<'static>) -> Text<'static> {
    let mut lines = normalize_lines(text);
    // position.go:44 measures via getLines, i.e. with tabs expanded.
    let content_width = lines
        .iter()
        .map(line_width_tabs_expanded)
        .max()
        .unwrap_or(0) as i64;
    let gap = width - content_width;
    if gap <= 0 {
        return Text::from(lines);
    }
    // When placing, the emitted lines ARE the getLines output — tabs
    // expand (position.go:54-77 writes `l`, not the original string).
    convert_tabs(&mut lines);

    let mut out: Vec<Line<'static>> = Vec::with_capacity(lines.len());
    for line in lines {
        // Is this line shorter than the longest line? (position.go:56.)
        let short = (content_width - line_width(&line) as i64).max(0);
        let mut spans: Vec<Span<'static>> = Vec::new();
        if pos.0 == LEFT.0 {
            // position.go:58-60.
            spans.extend(line.spans);
            push_span(&mut spans, sp(gap + short), Style::default());
        } else if pos.0 == RIGHT.0 {
            // position.go:62-64.
            push_span(&mut spans, sp(gap + short), Style::default());
            spans.extend(line.spans);
        } else {
            // position.go:66-75: remainder goes right
            // (`left = totalGap - round(totalGap·pos)`).
            let total_gap = gap + short;
            let split = (total_gap as f64 * pos.value()).round() as i64;
            let left = total_gap - split;
            let right = total_gap - left;
            push_span(&mut spans, sp(left), Style::default());
            spans.extend(line.spans);
            push_span(&mut spans, sp(right), Style::default());
        }
        out.push(Line::from(spans));
    }
    Text::from(out)
}

/// `lipgloss.PlaceVertical` (position.go:87-136): place a block in an
/// unstyled box of the given height. Fill rows are unstyled spaces as wide
/// as the block's widest line (position.go:100-101).
pub fn place_vertical(height: i64, pos: Position, text: Text<'static>) -> Text<'static> {
    let lines = normalize_lines(text);
    let content_height = lines.len() as i64;
    let gap = height - content_height;
    if gap <= 0 {
        return Text::from(lines);
    }

    // PARITY: the fill width comes from getLines (tabs expanded,
    // position.go:100-101) but the content block is written back VERBATIM
    // (`b.WriteString(str)`, position.go:105) — tabs survive in content
    // rows while fill rows are sized as if they were 4 spaces.
    let width = lines
        .iter()
        .map(line_width_tabs_expanded)
        .max()
        .unwrap_or(0) as i64;
    let empty_line = || -> Line<'static> {
        let mut spans = Vec::new();
        push_span(&mut spans, sp(width), Style::default());
        Line::from(spans)
    };

    let mut out: Vec<Line<'static>> = Vec::new();
    if pos.0 == TOP.0 {
        // position.go:105-113.
        out.extend(lines);
        out.extend(std::iter::repeat_with(empty_line).take(gap as usize));
    } else if pos.0 == BOTTOM.0 {
        // position.go:115-117.
        out.extend(std::iter::repeat_with(empty_line).take(gap as usize));
        out.extend(lines);
    } else {
        // position.go:119-131: remainder goes to the bottom
        // (`top = gap - round(gap·pos)`).
        let split = (gap as f64 * pos.value()).round() as i64;
        let top = gap - split;
        let bottom = gap - top;
        out.extend(std::iter::repeat_with(empty_line).take(top as usize));
        out.extend(lines);
        out.extend(std::iter::repeat_with(empty_line).take(bottom as usize));
    }
    Text::from(out)
}

// ---------------------------------------------------------------------------
// Borders (borders.go).
// ---------------------------------------------------------------------------

/// `lipgloss.Border` (borders.go:16-30), minus the `Middle*` pieces leet
/// never touches. Sides may be multi-rune (cycled) like Go; leet's are
/// single-rune, `" "`, or `""`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct BorderChars {
    pub top: &'static str,
    pub bottom: &'static str,
    pub left: &'static str,
    pub right: &'static str,
    pub top_left: &'static str,
    pub top_right: &'static str,
    pub bottom_left: &'static str,
    pub bottom_right: &'static str,
}

/// borders.go:68 `noBorder`.
pub const NO_BORDER: BorderChars = BorderChars {
    top: "",
    bottom: "",
    left: "",
    right: "",
    top_left: "",
    top_right: "",
    bottom_left: "",
    bottom_right: "",
};

/// `lipgloss.NormalBorder` (borders.go:70-84).
pub const fn normal_border() -> BorderChars {
    BorderChars {
        top: "─",
        bottom: "─",
        left: "│",
        right: "│",
        top_left: "┌",
        top_right: "┐",
        bottom_left: "└",
        bottom_right: "┘",
    }
}

/// `lipgloss.RoundedBorder` (borders.go:86-100).
pub const fn rounded_border() -> BorderChars {
    BorderChars {
        top: "─",
        bottom: "─",
        left: "│",
        right: "│",
        top_left: "╭",
        top_right: "╮",
        bottom_left: "╰",
        bottom_right: "╯",
    }
}

/// `lipgloss.ThickBorder` (borders.go:140-154).
pub const fn thick_border() -> BorderChars {
    BorderChars {
        top: "━",
        bottom: "━",
        left: "┃",
        right: "┃",
        top_left: "┏",
        top_right: "┓",
        bottom_left: "┗",
        bottom_right: "┛",
    }
}

impl BorderChars {
    /// borders.go:33-37 `GetTopSize` etc. via borders.go:60-65
    /// `getBorderEdgeWidth`.
    fn top_size(&self) -> i64 {
        max_rune_width(self.top_left)
            .max(max_rune_width(self.top))
            .max(max_rune_width(self.top_right))
    }
    fn right_size(&self) -> i64 {
        max_rune_width(self.top_right)
            .max(max_rune_width(self.right))
            .max(max_rune_width(self.bottom_right))
    }
    fn bottom_size(&self) -> i64 {
        max_rune_width(self.bottom_left)
            .max(max_rune_width(self.bottom))
            .max(max_rune_width(self.bottom_right))
    }
    fn left_size(&self) -> i64 {
        max_rune_width(self.top_left)
            .max(max_rune_width(self.left))
            .max(max_rune_width(self.bottom_left))
    }
}

/// borders.go:571-586 `maxRuneWidth`: widest grapheme in the string.
/// Border strings are single runes / spaces in leet, so a per-char walk
/// through the width shim is exact.
fn max_rune_width(s: &str) -> i64 {
    let mut buf = [0u8; 4];
    s.chars()
        .map(|c| text_width(c.encode_utf8(&mut buf)) as i64)
        .max()
        .unwrap_or(0)
}

/// borders.go:588-594 `getFirstRuneAsString`.
fn first_rune_as_str(s: &'static str) -> &'static str {
    match s.char_indices().nth(1) {
        Some((i, _)) => &s[..i],
        None => s,
    }
}

// ---------------------------------------------------------------------------
// GoStyle (style.go / set.go — the leet subset).
// ---------------------------------------------------------------------------

/// The `lipgloss.Style` subset leet uses. Unset fields mirror Go's unset
/// props (`props == 0` short-circuits rendering, style.go:390-392).
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct GoStyle {
    bold: Option<bool>,
    foreground: Option<Color>,
    background: Option<Color>,
    width: Option<i64>,
    height: Option<i64>,
    padding_top: Option<i64>,
    padding_right: Option<i64>,
    padding_bottom: Option<i64>,
    padding_left: Option<i64>,
    margin_top: Option<i64>,
    margin_bottom: Option<i64>,
    margin_left: Option<i64>,
    max_width: Option<i64>,
    max_height: Option<i64>,
    border_style: Option<BorderChars>,
    border_top: Option<bool>,
    border_right: Option<bool>,
    border_bottom: Option<bool>,
    border_left: Option<bool>,
    border_top_fg: Option<Color>,
    border_right_fg: Option<Color>,
    border_bottom_fg: Option<Color>,
    border_left_fg: Option<Color>,
}

/// set.go:838-866 `whichSidesInt` (CSS shorthand): 0/5+ args do nothing.
fn which_sides_int(i: &[i64]) -> Option<(i64, i64, i64, i64)> {
    match *i {
        [all] => Some((all, all, all, all)),
        [tb, lr] => Some((tb, lr, tb, lr)),
        [t, lr, b] => Some((t, lr, b, lr)),
        [t, r, b, l] => Some((t, r, b, l)),
        _ => None,
    }
}

impl GoStyle {
    /// `lipgloss.NewStyle` (style.go:135-137).
    pub fn new() -> Self {
        Self::default()
    }

    /// set.go:195 `Bold`.
    #[must_use]
    pub fn bold(mut self, v: bool) -> Self {
        self.bold = Some(v);
        self
    }

    /// set.go:272 `Foreground`.
    #[must_use]
    pub fn foreground(mut self, c: Color) -> Self {
        self.foreground = Some(c);
        self
    }

    /// set.go:278 `Background`.
    #[must_use]
    pub fn background(mut self, c: Color) -> Self {
        self.background = Some(c);
        self
    }

    /// set.go:286 `Width`.
    #[must_use]
    pub fn width(mut self, i: i64) -> Self {
        self.width = Some(i);
        self
    }

    /// set.go:294 `Height`.
    #[must_use]
    pub fn height(mut self, i: i64) -> Self {
        self.height = Some(i);
        self
    }

    /// set.go:341 `Padding` (variadic, CSS shorthand order per
    /// `whichSidesInt`).
    #[must_use]
    pub fn padding(mut self, i: &[i64]) -> Self {
        let Some((top, right, bottom, left)) = which_sides_int(i) else {
            return self;
        };
        self.padding_top = Some(top);
        self.padding_right = Some(right);
        self.padding_bottom = Some(bottom);
        self.padding_left = Some(left);
        self
    }

    /// set.go:355 `PaddingLeft`.
    #[must_use]
    pub fn padding_left(mut self, i: i64) -> Self {
        self.padding_left = Some(i);
        self
    }

    /// set.go `PaddingBottom`.
    #[must_use]
    pub fn padding_bottom(mut self, i: i64) -> Self {
        self.padding_bottom = Some(i);
        self
    }

    /// set.go:429 `MarginLeft`.
    #[must_use]
    pub fn margin_left(mut self, i: i64) -> Self {
        self.margin_left = Some(i);
        self
    }

    /// set.go:441 `MarginTop`.
    #[must_use]
    pub fn margin_top(mut self, i: i64) -> Self {
        self.margin_top = Some(i);
        self
    }

    /// set.go:447 `MarginBottom`.
    #[must_use]
    pub fn margin_bottom(mut self, i: i64) -> Self {
        self.margin_bottom = Some(i);
        self
    }

    /// set.go:750 `MaxWidth`.
    #[must_use]
    pub fn max_width(mut self, n: i64) -> Self {
        self.max_width = Some(n);
        self
    }

    /// set.go `MaxHeight`.
    #[must_use]
    pub fn max_height(mut self, n: i64) -> Self {
        self.max_height = Some(n);
        self
    }

    /// set.go:490-507 `Border` with no side args: sets the border style
    /// AND turns all four sides on (leet only calls this form).
    #[must_use]
    pub fn border(mut self, b: BorderChars) -> Self {
        self.border_style = Some(b);
        self.border_top = Some(true);
        self.border_right = Some(true);
        self.border_bottom = Some(true);
        self.border_left = Some(true);
        self
    }

    /// set.go:523-526 `BorderStyle`: style only; with no side props set,
    /// all sides render (get.go:645-656).
    #[must_use]
    pub fn border_style(mut self, b: BorderChars) -> Self {
        self.border_style = Some(b);
        self
    }

    /// set.go:529 `BorderTop`.
    #[must_use]
    pub fn border_top(mut self, v: bool) -> Self {
        self.border_top = Some(v);
        self
    }

    /// set.go:535 `BorderRight`.
    #[must_use]
    pub fn border_right(mut self, v: bool) -> Self {
        self.border_right = Some(v);
        self
    }

    /// set.go:541 `BorderBottom`.
    #[must_use]
    pub fn border_bottom(mut self, v: bool) -> Self {
        self.border_bottom = Some(v);
        self
    }

    /// set.go:547 `BorderLeft`.
    #[must_use]
    pub fn border_left(mut self, v: bool) -> Self {
        self.border_left = Some(v);
        self
    }

    /// set.go:567-584 `BorderForeground` — leet only uses the 1-arg form
    /// (all four edges).
    #[must_use]
    pub fn border_foreground(mut self, c: Color) -> Self {
        self.border_top_fg = Some(c);
        self.border_right_fg = Some(c);
        self.border_bottom_fg = Some(c);
        self.border_left_fg = Some(c);
        self
    }

    /// get.go:645-656 `isBorderStyleSetWithoutSides`.
    fn is_border_style_set_without_sides(&self) -> bool {
        self.border_style.is_some_and(|b| b != NO_BORDER)
            && self.border_top.is_none()
            && self.border_right.is_none()
            && self.border_bottom.is_none()
            && self.border_left.is_none()
    }

    /// get.go:346-355 `GetBorderTopSize` (and siblings below).
    fn border_top_size(&self) -> i64 {
        if self.is_border_style_set_without_sides() {
            return 1;
        }
        if !self.border_top.unwrap_or(false) {
            return 0;
        }
        self.border_style.unwrap_or(NO_BORDER).top_size()
    }

    fn border_right_size(&self) -> i64 {
        if self.is_border_style_set_without_sides() {
            return 1;
        }
        if !self.border_right.unwrap_or(false) {
            return 0;
        }
        self.border_style.unwrap_or(NO_BORDER).right_size()
    }

    fn border_bottom_size(&self) -> i64 {
        if self.is_border_style_set_without_sides() {
            return 1;
        }
        if !self.border_bottom.unwrap_or(false) {
            return 0;
        }
        self.border_style.unwrap_or(NO_BORDER).bottom_size()
    }

    fn border_left_size(&self) -> i64 {
        if self.is_border_style_set_without_sides() {
            return 1;
        }
        if !self.border_left.unwrap_or(false) {
            return 0;
        }
        self.border_style.unwrap_or(NO_BORDER).left_size()
    }

    /// get.go:399-401 `GetHorizontalBorderSize`.
    fn horizontal_border_size(&self) -> i64 {
        self.border_left_size() + self.border_right_size()
    }

    /// get.go:406-408 `GetVerticalBorderSize`.
    fn vertical_border_size(&self) -> i64 {
        self.border_top_size() + self.border_bottom_size()
    }

    /// `Style.Render` (style.go:250-527) on a plain string.
    pub fn render(&self, s: &str) -> Text<'static> {
        self.render_text(text_from_str(s))
    }

    /// `Style.Render` on an already-built block (Go passes pre-rendered
    /// ANSI strings; here the block keeps its span styles and this style's
    /// colors/bold patch only the fields spans leave unset).
    pub fn render_text(&self, text: Text<'static>) -> Text<'static> {
        let mut lines = normalize_lines(text);

        // maybeConvertTabs (style.go:439, 543-556) — leet never sets
        // TabWidth, so the default 4 applies. Runs on the props==0 path
        // too (style.go:390-392).
        for line in &mut lines {
            for span in &mut line.spans {
                if span.content.contains('\t') {
                    span.content = span.content.replace('\t', "    ").into();
                }
            }
        }

        // style.go:390-392: unstyled style renders the string unchanged.
        if *self == Self::default() {
            return Text::from(lines);
        }

        let te = {
            let mut st = Style::default();
            if self.bold.unwrap_or(false) {
                st = st.add_modifier(Modifier::BOLD);
            }
            if let Some(fg) = self.foreground {
                st = st.fg(fg);
            }
            if let Some(bg) = self.background {
                st = st.bg(bg);
            }
            st
        };
        // teWhitespace (style.go:379-385): background only — this is what
        // keeps padding/fill spaces UNSTYLED when no background is set.
        let te_whitespace = match self.background {
            Some(bg) => Style::default().bg(bg),
            None => Style::default(),
        };

        // Include borders in block size (style.go:402-403).
        let width = self.width.unwrap_or(0) - self.horizontal_border_size();
        let height = self.height.unwrap_or(0) - self.vertical_border_size();

        let top_padding = self.padding_top.unwrap_or(0);
        let right_padding = self.padding_right.unwrap_or(0);
        let bottom_padding = self.padding_bottom.unwrap_or(0);
        let left_padding = self.padding_left.unwrap_or(0);

        // Word wrap (style.go:406-410).
        if width > 0 {
            let wrap_at = width - left_padding - right_padding;
            lines = wrap_lines(lines, wrap_at);
        }

        // Render core text (style.go:413-437): the whole line gets `te`
        // (no useSpaceStyler in the leet subset).
        for line in &mut lines {
            for span in &mut line.spans {
                span.style = te.patch(span.style);
            }
        }

        // Padding (style.go:452-480). Left/right pads every current line;
        // top/bottom rows are added EMPTY afterwards (they get sized by
        // the alignment pass below, exactly as in Go where they are bare
        // "\n"s).
        if left_padding > 0 {
            for line in &mut lines {
                line.spans
                    .insert(0, Span::styled(sp(left_padding), te_whitespace));
            }
        }
        if right_padding > 0 {
            for line in &mut lines {
                line.spans
                    .push(Span::styled(sp(right_padding), te_whitespace));
            }
        }
        if top_padding > 0 {
            for _ in 0..top_padding {
                lines.insert(0, Line::default());
            }
        }
        if bottom_padding > 0 {
            lines.extend(std::iter::repeat_with(Line::default).take(bottom_padding as usize));
        }

        // Height (style.go:483-485). Vertical alignment is always Top in
        // leet (Align* is never called; unset position is 0).
        if height > 0 {
            align_text_vertical(&mut lines, TOP, height);
        }

        // Set alignment (style.go:487-501). Also pads short lines so all
        // lines are the same length; Go's condition is
        // `numLines != 0 || width != 0` where numLines counts '\n's.
        {
            let num_newlines = lines.len() as i64 - 1;
            if num_newlines != 0 || width != 0 {
                // Horizontal alignment is always Left in leet (unset).
                align_text_horizontal(&mut lines, LEFT, width, te_whitespace);
            }
        }

        // style.go:503-506 (inline is never set in leet).
        lines = self.apply_border(lines);
        lines = self.apply_margins(lines);

        // Truncate according to MaxWidth (style.go:509-517).
        if let Some(mw) = self.max_width
            && mw > 0
        {
            lines = lines.into_iter().map(|l| truncate_line(l, mw)).collect();
        }

        // Truncate according to MaxHeight (style.go:520-526).
        if let Some(mh) = self.max_height
            && mh > 0
        {
            let keep = (mh as usize).min(lines.len());
            lines.truncate(keep);
        }

        Text::from(lines)
    }

    /// borders.go:327-491 `applyBorder` (minus blends/backgrounds, unused
    /// by leet).
    fn apply_border(&self, lines: Vec<Line<'static>>) -> Vec<Line<'static>> {
        let mut border = self.border_style.unwrap_or(NO_BORDER);
        let mut has_top = self.border_top.unwrap_or(false);
        let mut has_right = self.border_right.unwrap_or(false);
        let mut has_bottom = self.border_bottom.unwrap_or(false);
        let mut has_left = self.border_left.unwrap_or(false);

        // borders.go:338-343: style set with no explicit sides renders
        // all sides.
        if self.is_border_style_set_without_sides() {
            has_top = true;
            has_right = true;
            has_bottom = true;
            has_left = true;
        }

        // borders.go:346-348.
        if border == NO_BORDER || (!has_top && !has_right && !has_bottom && !has_left) {
            return lines;
        }

        let mut width = lines.iter().map(line_width).max().unwrap_or(0) as i64;

        // borders.go:352-364: default empty sides to a space and widen the
        // edge accordingly.
        if has_left {
            if border.left.is_empty() {
                border.left = " ";
            }
            width += max_rune_width(border.left);
        }
        if has_right {
            if border.right.is_empty() {
                border.right = " ";
            }
            width += max_rune_width(border.right);
        }

        // borders.go:366-378: corners rendered but empty become a space.
        if has_top && has_left && border.top_left.is_empty() {
            border.top_left = " ";
        }
        if has_top && has_right && border.top_right.is_empty() {
            border.top_right = " ";
        }
        if has_bottom && has_left && border.bottom_left.is_empty() {
            border.bottom_left = " ";
        }
        if has_bottom && has_right && border.bottom_right.is_empty() {
            border.bottom_right = " ";
        }

        // borders.go:380-404: suppress corners for missing sides.
        if has_top {
            if !has_left && !has_right {
                border.top_left = "";
                border.top_right = "";
            } else if !has_left {
                border.top_left = "";
            } else if !has_right {
                border.top_right = "";
            }
        }
        if has_bottom {
            if !has_left && !has_right {
                border.bottom_left = "";
                border.bottom_right = "";
            } else if !has_left {
                border.bottom_left = "";
            } else if !has_right {
                border.bottom_right = "";
            }
        }

        // borders.go:406-410: limit corners to one rune.
        border.top_left = first_rune_as_str(border.top_left);
        border.top_right = first_rune_as_str(border.top_right);
        border.bottom_right = first_rune_as_str(border.bottom_right);
        border.bottom_left = first_rune_as_str(border.bottom_left);

        // borders.go:527-539 `styleBorder` (fg only: leet never sets
        // border backgrounds).
        let style_border = |s: String, fg: Option<Color>| -> Span<'static> {
            match fg {
                Some(c) => Span::styled(s, Style::default().fg(c)),
                None => Span::raw(s),
            }
        };

        let mut out: Vec<Line<'static>> = Vec::with_capacity(lines.len() + 2);

        // Render top (borders.go:435-444).
        if has_top {
            let top = render_horizontal_edge(border.top_left, border.top, border.top_right, width);
            out.push(Line::from(vec![style_border(top, self.border_top_fg)]));
        }

        // Render sides (borders.go:446-478): side runes cycle per line.
        let left_runes: Vec<char> = border.left.chars().collect();
        let right_runes: Vec<char> = border.right.chars().collect();
        let mut left_index = 0usize;
        let mut right_index = 0usize;
        for line in lines {
            let mut spans: Vec<Span<'static>> = Vec::new();
            if has_left {
                let r = left_runes[left_index].to_string();
                left_index = (left_index + 1) % left_runes.len();
                spans.push(style_border(r, self.border_left_fg));
            }
            spans.extend(line.spans);
            if has_right {
                let r = right_runes[right_index].to_string();
                right_index = (right_index + 1) % right_runes.len();
                spans.push(style_border(r, self.border_right_fg));
            }
            out.push(Line::from(spans));
        }

        // Render bottom (borders.go:480-489).
        if has_bottom {
            let bottom = render_horizontal_edge(
                border.bottom_left,
                border.bottom,
                border.bottom_right,
                width,
            );
            out.push(Line::from(vec![style_border(
                bottom,
                self.border_bottom_fg,
            )]));
        }

        out
    }

    /// style.go:558-585 `applyMargins` — leet sets only MarginLeft/Top/
    /// Bottom, never MarginBackground/MarginChar, so margin cells are
    /// UNSTYLED spaces.
    fn apply_margins(&self, mut lines: Vec<Line<'static>>) -> Vec<Line<'static>> {
        let left_margin = self.margin_left.unwrap_or(0);
        let top_margin = self.margin_top.unwrap_or(0);
        let bottom_margin = self.margin_bottom.unwrap_or(0);

        if left_margin > 0 {
            for line in &mut lines {
                line.spans.insert(0, Span::raw(sp(left_margin)));
            }
        }

        if top_margin > 0 || bottom_margin > 0 {
            // style.go:567-568: width measured AFTER the left margin.
            let width = lines.iter().map(line_width).max().unwrap_or(0) as i64;
            let spaces_row = || -> Line<'static> {
                let mut spans = Vec::new();
                push_span(&mut spans, sp(width), Style::default());
                Line::from(spans)
            };
            for _ in 0..top_margin {
                lines.insert(0, spaces_row());
            }
            lines.extend(std::iter::repeat_with(spaces_row).take(bottom_margin.max(0) as usize));
        }

        lines
    }
}

// ---------------------------------------------------------------------------
// Alignment (align.go).
// ---------------------------------------------------------------------------

/// align.go:12-58 `alignTextHorizontal`: pad every line to
/// `max(widest, width)` with `st`-styled spaces per the position.
fn align_text_horizontal(lines: &mut Vec<Line<'static>>, pos: Position, width: i64, st: Style) {
    let widest = lines.iter().map(line_width).max().unwrap_or(0) as i64;
    for line in lines {
        let lw = line_width(line) as i64;
        // difference from the widest line, then from the total width
        // (align.go:19-20).
        let mut short = widest - lw;
        short += (width - (short + lw)).max(0);
        if short <= 0 {
            continue;
        }
        if pos.0 == RIGHT.0 {
            // align.go:24-29.
            line.spans.insert(0, Span::styled(sp(short), st));
        } else if pos.0 == CENTER.0 {
            // align.go:30-43. Note: remainder goes on the right.
            let left = short / 2;
            let right = left + short % 2;
            if left > 0 {
                line.spans.insert(0, Span::styled(sp(left), st));
            }
            line.spans.push(Span::styled(sp(right), st));
        } else {
            // Left (align.go:44-49).
            line.spans.push(Span::styled(sp(short), st));
        }
    }
}

/// align.go:61-79 `alignTextVertical`. Added rows are EMPTY lines (bare
/// `"\n"`s in Go); the horizontal alignment pass sizes them afterwards.
/// PARITY: positions other than exactly Top/Center/Bottom fall through
/// unchanged, as in Go's switch.
fn align_text_vertical(lines: &mut Vec<Line<'static>>, pos: Position, height: i64) {
    let str_height = lines.len() as i64;
    if height < str_height {
        return;
    }
    if pos.0 == TOP.0 {
        lines.extend(std::iter::repeat_with(Line::default).take((height - str_height) as usize));
    } else if pos.0 == CENTER.0 {
        let mut top_padding = (height - str_height) / 2;
        let mut bottom_padding = (height - str_height) / 2;
        if str_height + top_padding + bottom_padding > height {
            top_padding -= 1;
        } else if str_height + top_padding + bottom_padding < height {
            bottom_padding += 1;
        }
        for _ in 0..top_padding {
            lines.insert(0, Line::default());
        }
        lines.extend(std::iter::repeat_with(Line::default).take(bottom_padding.max(0) as usize));
    } else if pos.0 == BOTTOM.0 {
        for _ in 0..(height - str_height) {
            lines.insert(0, Line::default());
        }
    }
}

/// borders.go:494-524 `renderHorizontalEdge`: corner + cycled middle runes
/// up to `width` + corner.
fn render_horizontal_edge(left: &str, middle: &str, right: &str, width: i64) -> String {
    let middle = if middle.is_empty() { " " } else { middle };
    let left_width = text_width(left) as i64;
    let right_width = text_width(right) as i64;

    let runes: Vec<char> = middle.chars().collect();
    let mut j = 0usize;
    let mut out = String::new();
    out.push_str(left);
    let mut i: i64 = 0;
    let mut buf = [0u8; 4];
    while i < width - left_width - right_width {
        let r = runes[j];
        out.push(r);
        i += text_width(r.encode_utf8(&mut buf)) as i64;
        j = (j + 1) % runes.len();
    }
    out.push_str(right);
    out
}

// ---------------------------------------------------------------------------
// Word wrap (x/ansi wrap.go:293-464 `wrap`, reached via lipgloss `Wrap`,
// style.go:409, always with breakpoints "" — so '-' is the only breakpoint).
// ---------------------------------------------------------------------------

struct WrapState {
    limit: i64,
    buf: Vec<Line<'static>>,
    cur: Vec<Span<'static>>,
    word: Vec<Span<'static>>,
    space: Vec<Span<'static>>,
    space_width: i64,
    cur_width: i64,
    word_len: i64,
}

/// Appends a grapheme to a styled segment buffer, merging runs of the same
/// style (the span-model equivalent of Go's byte buffers, which interleave
/// SGR sequences in the stream).
fn push_seg(segs: &mut Vec<Span<'static>>, sym: &str, style: Style) {
    if let Some(last) = segs.last_mut()
        && last.style == style
    {
        last.content.to_mut().push_str(sym);
        return;
    }
    segs.push(Span::styled(sym.to_string(), style));
}

impl WrapState {
    /// wrap.go:309-316 `addSpace`.
    fn add_space(&mut self) {
        if self.space_width == 0 && self.space.is_empty() {
            return;
        }
        self.cur_width += self.space_width;
        let mut spaces = std::mem::take(&mut self.space);
        self.cur.append(&mut spaces);
        self.space_width = 0;
    }

    /// wrap.go:319-329 `addWord`.
    fn add_word(&mut self) {
        if self.word.is_empty() {
            return;
        }
        self.add_space();
        self.cur_width += self.word_len;
        let mut word = std::mem::take(&mut self.word);
        self.cur.append(&mut word);
        self.word_len = 0;
    }

    /// wrap.go:331-336 `addNewline`.
    fn add_newline(&mut self) {
        self.buf.push(Line::from(std::mem::take(&mut self.cur)));
        self.cur_width = 0;
        self.space.clear();
        self.space_width = 0;
    }

    /// wrap.go:387-401 (the `'\n'` case) and wrap.go:448-458 (end of
    /// input): flush pending spaces if they fit, else drop them.
    fn flush_spaces_at_break(&mut self) {
        if self.word_len == 0 {
            if self.cur_width + self.space_width > self.limit {
                self.cur_width = 0;
            } else {
                // preserve whitespaces
                let mut spaces = std::mem::take(&mut self.space);
                self.cur.append(&mut spaces);
            }
            self.space.clear();
            self.space_width = 0;
        }
    }

    /// The single-byte branch (wrap.go:384-436, PrintAction). `sym` is a
    /// one-byte ASCII grapheme.
    fn step_byte(&mut self, sym: &str, style: Style) {
        let r = sym.as_bytes()[0] as char;
        if r.is_whitespace() {
            // wrap.go:404-406.
            self.add_word();
            push_seg(&mut self.space, sym, style);
            self.space_width += 1;
        } else if r == '-' {
            // wrap.go:407-419 (breakpoint).
            self.add_space();
            if self.cur_width + self.word_len >= self.limit {
                // We can't fit the breakpoint in the current line, treat
                // it as part of the word.
                push_seg(&mut self.word, sym, style);
                self.word_len += 1;
            } else {
                self.add_word();
                push_seg(&mut self.cur, sym, style);
                self.cur_width += 1;
            }
        } else {
            // wrap.go:420-436.
            if self.cur_width == self.limit {
                self.add_newline();
            }
            push_seg(&mut self.word, sym, style);
            self.word_len += 1;
            if self.word_len == self.limit {
                // Hardwrap the word if it's too long.
                self.add_word();
            }
            if self.cur_width + self.word_len + self.space_width > self.limit {
                self.add_newline();
            }
        }
    }

    /// The grapheme-cluster branch (wrap.go:341-382, Utf8State).
    fn step_cluster(&mut self, sym: &str, style: Style) {
        let w = grapheme_width(sym) as i64;
        let first = sym.chars().next().unwrap_or('\u{0}');
        if first.is_whitespace() && first != '\u{00A0}' {
            // wrap.go:347-350 (nbsp is a non-breaking space).
            self.add_word();
            push_seg(&mut self.space, sym, style);
            self.space_width += w;
        } else {
            // wrap.go:361-376. (The breakpoints branch at
            // wrap.go:351-360 is unreachable: breakpoints is always "".)
            if self.word_len + w > self.limit {
                // Hardwrap the word if it's too long.
                self.add_word();
            }
            push_seg(&mut self.word, sym, style);
            self.word_len += w;
            if self.cur_width + self.word_len + self.space_width > self.limit {
                self.add_newline();
            }
            if self.word_len == self.limit {
                self.add_word();
            }
        }
    }
}

/// The wrap loop. Graphemes come from ratatui's segmentation
/// (`Span::styled_graphemes`); widths from the `leet_data::width` shim.
///
/// PARITY: ratatui's grapheme iterator silently drops control characters;
/// Go passes them through at width 0. leet content reaching a wrap never
/// contains control bytes (tabs are converted before this point).
fn wrap_lines(lines: Vec<Line<'static>>, limit: i64) -> Vec<Line<'static>> {
    // wrap.go:294-296.
    if limit < 1 {
        return lines;
    }
    let mut st = WrapState {
        limit,
        buf: Vec::new(),
        cur: Vec::new(),
        word: Vec::new(),
        space: Vec::new(),
        space_width: 0,
        cur_width: 0,
        word_len: 0,
    };

    let line_count = lines.len();
    for (k, line) in lines.iter().enumerate() {
        for span in &line.spans {
            for g in span.styled_graphemes(Style::default()) {
                let sym = g.symbol;
                let style = g.style;
                let bytes = sym.as_bytes();
                // PARITY: Go's wrap parses BYTES — printable ASCII runs
                // through the byte parser one rune at a time, and a
                // grapheme cluster is only consumed when a UTF-8 lead
                // byte is reached (wrap.go:339-345). A decomposed cluster
                // like "e\u{301}" is therefore an ASCII base plus a
                // SEPARATE zero-width mark cluster, so a wrap boundary
                // can land between them and the mark starts the next
                // word detached from its base (Go wraps
                // "ee\u{301}x" at limit 2 to "ee\n\u{301}x"). Split
                // ASCII-led ratatui clusters the same way; the tail
                // re-segments as a single cluster because with an ASCII
                // base (never Extended_Pictographic or a regional
                // indicator) every continuation joins via UAX #29
                // GB9/GB9a, which hold regardless of what precedes.
                match bytes.first() {
                    None => {}
                    Some(&b) if b < 0x80 => {
                        // Single-byte path (wrap.go:384-436, PrintAction).
                        st.step_byte(&sym[..1], style);
                        if bytes.len() > 1 {
                            // Trailing marks: zero-width Utf8State
                            // cluster of their own (wrap.go:341-345).
                            st.step_cluster(&sym[1..], style);
                        }
                    }
                    // Grapheme-cluster path (wrap.go:341-382, Utf8State).
                    Some(_) => st.step_cluster(sym, style),
                }
            }
        }
        // '\n' between input lines (wrap.go:387-401).
        if k + 1 < line_count {
            st.flush_spaces_at_break();
            st.add_word();
            st.add_newline();
        }
    }

    // End of input (wrap.go:448-460).
    st.flush_spaces_at_break();
    st.add_word();
    st.buf.push(Line::from(st.cur));
    st.buf
}

// ---------------------------------------------------------------------------
// Truncation (x/ansi truncate.go:66-160 `truncate`, reached via
// `ansi.Truncate(line, maxWidth, "")`, style.go:513).
// ---------------------------------------------------------------------------

/// Keep the longest grapheme prefix whose width fits in `length`; drop the
/// rest (empty tail). Zero-width clusters right at the boundary are kept,
/// as in Go (`curWidth += width; if curWidth > length` — a +0 does not
/// overflow).
fn truncate_line(line: Line<'static>, length: i64) -> Line<'static> {
    // truncate.go:67-69 early out.
    if line_width(&line) as i64 <= length {
        return line;
    }
    let mut out: Vec<Span<'static>> = Vec::new();
    let mut cur_width: i64 = 0;
    let mut ignoring = false;
    for span in &line.spans {
        if ignoring {
            break;
        }
        let mut kept = String::new();
        for g in span.styled_graphemes(Style::default()) {
            let w = grapheme_width(g.symbol) as i64;
            if cur_width + w > length {
                // truncate.go:107-110: once over, ignore all remaining
                // printable content.
                ignoring = true;
                break;
            }
            cur_width += w;
            kept.push_str(g.symbol);
        }
        push_span(&mut out, kept, span.style);
    }
    Line::from(out)
}

// ---------------------------------------------------------------------------
// styles.go STYLE OBJECTS (styles.go:530-817) as GoStyle constructors.
// Adaptive colors resolve via `dark`; constructors without a `dark`
// parameter use only non-adaptive colors or no colors at all.
// ---------------------------------------------------------------------------

/// styles.go:531 `headerStyle`.
pub fn header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
}

/// styles.go:533 `navInfoStyle`.
pub fn nav_info_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

/// styles.go:535 `headerContainerStyle`.
pub fn header_container_style() -> GoStyle {
    GoStyle::new()
}

/// styles.go:537 `gridContainerStyle`.
pub fn grid_container_style() -> GoStyle {
    GoStyle::new()
}

/// styles.go:542-544 `borderStyle`.
pub fn border_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .border_style(rounded_border())
        .border_foreground(adaptive_to_color(COLOR_LAYOUT, dark))
}

/// styles.go:546 `titleStyle`.
pub fn title_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_ACCENT, dark))
        .bold(true)
}

/// styles.go:548 `seriesCountStyle`.
pub fn series_count_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

/// styles.go:550 `focusedBorderStyle` (borderStyle with the highlight
/// border foreground).
pub fn focused_border_style(dark: bool) -> GoStyle {
    border_style(dark).border_foreground(adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark))
}

/// styles.go:552 `axisStyle`.
pub fn axis_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

/// styles.go:554 `labelStyle`.
pub fn label_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_TEXT, dark))
}

/// styles.go:556 `inspectionLineStyle`.
pub fn inspection_line_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_SUBTLE, dark))
}

/// styles.go:558-566 `inspectionLegendStyle` (colors exported from
/// leet-charts, see its module doc).
pub fn inspection_legend_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(INSPECTION_LEGEND_FG, dark))
        .background(adaptive_to_color(INSPECTION_LEGEND_BG, dark))
}

/// styles.go:571-574 `statusBarStyle`.
pub fn status_bar_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(rgb_to_color(MOON900))
        .background(adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark))
        .padding(&[0, STATUS_BAR_PADDING])
}

/// styles.go:577 `errorStyle`.
pub fn error_style() -> GoStyle {
    GoStyle::new()
}

/// styles.go:659-667 `runOverviewTagStyle`: complete badge style for a
/// tag; background from the scheme, foreground picked for WCAG contrast
/// (both computed in leet-charts).
pub fn run_overview_tag_style(scheme: &str, tag: &str, dark: bool) -> GoStyle {
    let bg = run_overview_tag_background_color(scheme, tag);
    let fg = run_overview_tag_foreground_color(bg);
    GoStyle::new()
        .foreground(adaptive_to_color(fg, dark))
        .background(adaptive_to_color(bg, dark))
        .padding(&[0, 1])
        .bold(true)
}

/// styles.go:671-672 `runOverviewSidebarSectionHeaderStyle`.
pub fn run_overview_sidebar_section_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
}

/// styles.go:673 `runOverviewSidebarSectionStyle`.
pub fn run_overview_sidebar_section_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_TEXT, dark))
        .bold(true)
}

/// styles.go:674 `runOverviewSidebarKeyStyle` (colorItemKey is uniform:
/// ANSI 243 = #767676).
pub fn run_overview_sidebar_key_style() -> GoStyle {
    GoStyle::new().foreground(rgb_to_color(COLOR_ITEM_KEY))
}

/// styles.go:675 `runOverviewSidebarValueStyle`.
pub fn run_overview_sidebar_value_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_ITEM_VALUE, dark))
}

/// styles.go:676-677 `runOverviewSidebarHighlightedItem`.
pub fn run_overview_sidebar_highlighted_item(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(rgb_to_color(COLOR_DARK))
        .background(adaptive_to_color(COLOR_SELECTED, dark))
}

/// styles.go:682 `leftSidebarStyle`.
pub fn left_sidebar_style() -> GoStyle {
    GoStyle::new().padding(&[0, CONTENT_PADDING])
}

/// styles.go:683-688 `leftSidebarBorderStyle`: only the right rule (│) of
/// [`RIGHT_BORDER`] renders.
pub fn left_sidebar_border_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .border(RIGHT_BORDER)
        .border_foreground(adaptive_to_color(COLOR_LAYOUT, dark))
        .border_top(false)
        .border_bottom(false)
        .border_left(false)
}

/// styles.go:689-692 `leftSidebarHeaderStyle`.
pub fn left_sidebar_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .margin_bottom(0)
}

/// styles.go:693-702 `RightBorder`: a border whose only visible edge is a
/// `│` on the right (top/bottom/corners are spaces, left is empty).
pub const RIGHT_BORDER: BorderChars = BorderChars {
    top: " ",
    bottom: " ",
    left: "",
    right: "\u{2502}", // boxLightVertical
    top_left: " ",
    top_right: " ",
    bottom_left: " ",
    bottom_right: " ",
};

/// styles.go:707 `rightSidebarStyle`.
pub fn right_sidebar_style() -> GoStyle {
    GoStyle::new().padding(&[0, CONTENT_PADDING])
}

/// styles.go:708-713 `rightSidebarBorderStyle`.
pub fn right_sidebar_border_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .border(LEFT_BORDER)
        .border_foreground(adaptive_to_color(COLOR_LAYOUT, dark))
        .border_top(false)
        .border_bottom(false)
        .border_right(false)
}

/// styles.go:714-717 `rightSidebarHeaderStyle`.
pub fn right_sidebar_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .margin_left(0)
}

/// styles.go:718-727 `LeftBorder`.
pub const LEFT_BORDER: BorderChars = BorderChars {
    top: " ",
    bottom: " ",
    left: "\u{2502}", // boxLightVertical
    right: "",
    top_left: " ",
    top_right: " ",
    bottom_left: " ",
    bottom_right: " ",
};

/// styles.go:732-735 `consoleLogsPaneHeaderStyle`.
pub fn console_logs_pane_header_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .padding_left(1)
}

/// styles.go:737-739 `consoleLogsPaneTimestampStyle`.
pub fn console_logs_pane_timestamp_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_SUBTLE, dark))
        .padding_left(1)
}

/// styles.go:741-742 `consoleLogsPaneValueStyle`.
pub fn console_logs_pane_value_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_ITEM_VALUE, dark))
}

/// styles.go:744-747 `consoleLogsPaneHighlightedTimestampStyle`.
pub fn console_logs_pane_highlighted_timestamp_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .background(adaptive_to_color(COLOR_SELECTED, dark))
        .foreground(rgb_to_color(COLOR_DARK))
        .padding_left(1)
}

/// styles.go:749-751 `consoleLogsPaneHighlightedValueStyle`.
pub fn console_logs_pane_highlighted_value_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .background(adaptive_to_color(COLOR_SELECTED, dark))
        .foreground(rgb_to_color(COLOR_DARK))
}

/// styles.go:789 `helpKeyStyle`.
pub fn help_key_style(dark: bool) -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(adaptive_to_color(COLOR_SUBHEADING, dark))
        .width(24)
}

/// styles.go:791 `helpDescStyle`.
pub fn help_desc_style(dark: bool) -> GoStyle {
    GoStyle::new().foreground(adaptive_to_color(COLOR_TEXT, dark))
}

/// styles.go:793 `helpSectionStyle` (colorHeading = wandbColor, uniform).
pub fn help_section_style() -> GoStyle {
    GoStyle::new()
        .bold(true)
        .foreground(rgb_to_color(COLOR_HEADING))
}

/// styles.go:795 `helpContentStyle`.
pub fn help_content_style() -> GoStyle {
    GoStyle::new().margin_left(2).margin_top(1)
}

/// styles.go:807 `evenRunStyle`.
pub fn even_run_style() -> GoStyle {
    GoStyle::new()
}

/// styles.go:808 `oddRunStyle`: zebra stripe 5% toward gray from the
/// terminal background (`term_bg` = the detected background, `None` when
/// detection failed — see leet-charts `get_odd_run_style_color`).
pub fn odd_run_style(term_bg: Option<Rgb>, dark: bool) -> GoStyle {
    GoStyle::new().background(adaptive_to_color(get_odd_run_style_color(term_bg), dark))
}

/// styles.go:809 `selectedRunStyle`.
pub fn selected_run_style(dark: bool) -> GoStyle {
    GoStyle::new().background(adaptive_to_color(COLOR_SELECTED, dark))
}

/// styles.go:810 `selectedRunInactiveStyle`.
pub fn selected_run_inactive_style(dark: bool) -> GoStyle {
    GoStyle::new().background(adaptive_to_color(COLOR_SELECTED_RUN_INACTIVE_STYLE, dark))
}

/// styles.go:815-816 `symonContainerStyle`.
pub fn symon_container_style() -> GoStyle {
    GoStyle::new().padding(&[0, CONTENT_PADDING])
}

// ---------------------------------------------------------------------------
// Separator helpers (styles.go:754-776).
// ---------------------------------------------------------------------------

/// styles.go:757-763 `renderHorizontalSeparator`: a full-width em-dash
/// separator line, colorLayout foreground.
pub fn render_horizontal_separator(width: i64, dark: bool) -> Text<'static> {
    if width <= 0 {
        return text_from_str("");
    }
    let line = UNICODE_EM_DASH.to_string().repeat(width as usize);
    GoStyle::new()
        .foreground(adaptive_to_color(COLOR_LAYOUT, dark))
        .render(&line)
}

/// styles.go:766-776 `joinWithSeparators`: joins rendered sections with
/// horizontal separator lines.
pub fn join_with_separators(sections: Vec<Text<'static>>, width: i64, dark: bool) -> Text<'static> {
    if sections.is_empty() {
        return text_from_str("");
    }
    let sep = render_horizontal_separator(width, dark);
    let mut it = sections.into_iter();
    let mut result = it.next().expect("non-empty checked");
    for s in it {
        result = join_vertical(LEFT, vec![result, sep.clone(), s]);
    }
    result
}

// ---------------------------------------------------------------------------
// Tests. No Go _test.go covers these helpers directly (they are
// lipgloss-internal); expectations below are hand-traced from the vendored
// lipgloss sources, with line cites.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use leet_charts::styles::blend_rgb;
    use pretty_assertions::assert_eq;

    fn t(s: &str) -> Text<'static> {
        text_from_str(s)
    }

    fn s(text: &Text<'_>) -> String {
        text_to_string(text)
    }

    // -- Position ------------------------------------------------------------

    #[test]
    fn position_value_clamps() {
        // position.go:21-23.
        assert_eq!(Position(-0.5).value(), 0.0);
        assert_eq!(Position(1.5).value(), 1.0);
        assert_eq!(Position(0.25).value(), 0.25);
    }

    // -- text helpers ----------------------------------------------------------

    #[test]
    fn text_from_str_go_split_semantics() {
        // Go strings.Split keeps the trailing empty line; str::lines()
        // would not.
        let text = t("a\n");
        assert_eq!(block_height(&text), 2);
        assert_eq!(s(&text), "a\n");
        // getLines tab conversion (get.go:630).
        assert_eq!(s(&t("x\ty")), "x    y");
        // Empty string is one empty line.
        assert_eq!(block_height(&t("")), 1);
    }

    #[test]
    fn block_width_is_widest_line() {
        // size.go:15-24.
        assert_eq!(block_width(&t("ab\nxyz\nq")), 3);
        // Wide chars count 2 columns through the shim.
        assert_eq!(block_width(&t("世界")), 4);
    }

    // -- join_horizontal (join.go:29-100) ---------------------------------------

    #[test]
    fn join_horizontal_empty_and_single() {
        // join.go:30-35.
        assert_eq!(s(&join_horizontal(TOP, vec![])), "");
        assert_eq!(s(&join_horizontal(TOP, vec![t("a\nb")])), "a\nb");
    }

    #[test]
    fn join_horizontal_top() {
        // join.go:62-64: Top pads short blocks at the BOTTOM; short lines
        // of each block pad to that block's width (join.go:84-93).
        let got = join_horizontal(TOP, vec![t("a"), t("b1\nb2\nb3")]);
        assert_eq!(s(&got), "ab1\n b2\n b3");
    }

    #[test]
    fn join_horizontal_bottom() {
        // join.go:66-67: Bottom pads short blocks at the TOP.
        let got = join_horizontal(BOTTOM, vec![t("a"), t("b1\nb2\nb3")]);
        assert_eq!(s(&got), " b1\n b2\nab3");
    }

    #[test]
    fn join_horizontal_center_rounds_half_away_from_zero() {
        // join.go:69-77: n = 3 extra lines, split = round(3·0.5) = 2 →
        // 2 blanks above, 1 below.
        let got = join_horizontal(CENTER, vec![t("a"), t("b1\nb2\nb3\nb4")]);
        assert_eq!(s(&got), " b1\n b2\nab3\n b4");
    }

    #[test]
    fn join_horizontal_fractional_position() {
        // join.go:69-77 with pos 0.2: n = 5, split = round(1.0) = 1 blank
        // above ("20% from the top", join.go:24).
        let got = join_horizontal(Position(0.2), vec![t("a"), t("1\n2\n3\n4\n5\n6")]);
        assert_eq!(s(&got), " 1\na2\n 3\n 4\n 5\n 6");
    }

    #[test]
    fn join_horizontal_pads_each_block_to_own_width_unstyled() {
        // join.go:84-93: every block's lines pad to that block's max
        // width — including the LAST block (trailing spaces) — with
        // UNSTYLED spaces (join.go:88).
        let got = join_horizontal(TOP, vec![t("ab"), t("c\ndd")]);
        assert_eq!(s(&got), "abc \n  dd");
        for line in &got.lines {
            for span in &line.spans {
                assert_eq!(span.style, Style::default());
            }
        }
    }

    // -- join_vertical (join.go:115-171) ------------------------------------------

    #[test]
    fn join_vertical_left_pads_all_lines_to_max_width() {
        // join.go:143-145: trailing unstyled spaces on the short line.
        let got = join_vertical(LEFT, vec![t("a"), t("bbb")]);
        assert_eq!(s(&got), "a  \nbbb");
        assert_eq!(got.lines[0].spans[1].style, Style::default());
    }

    #[test]
    fn join_vertical_right() {
        // join.go:147-149.
        let got = join_vertical(RIGHT, vec![t("a"), t("bbb")]);
        assert_eq!(s(&got), "  a\nbbb");
    }

    #[test]
    fn join_vertical_center_remainder_goes_left() {
        // join.go:151-161: w = 3, split = round(1.5) = 2 → left 2,
        // right 1 (remainder LEFT — unlike alignTextHorizontal).
        let got = join_vertical(CENTER, vec![t("a"), t("bbbb")]);
        assert_eq!(s(&got), "  a \nbbbb");
    }

    #[test]
    fn join_vertical_center_no_pad_when_w_lt_1() {
        // join.go:152-155: equal-width lines emitted unchanged.
        let got = join_vertical(CENTER, vec![t("aa"), t("bb")]);
        assert_eq!(s(&got), "aa\nbb");
    }

    // -- place_horizontal (position.go:43-83) --------------------------------------

    #[test]
    fn place_horizontal_left() {
        // position.go:58-60.
        assert_eq!(s(&place_horizontal(5, LEFT, t("ab"))), "ab   ");
    }

    #[test]
    fn place_horizontal_right() {
        // position.go:62-64.
        assert_eq!(s(&place_horizontal(5, RIGHT, t("ab"))), "   ab");
    }

    #[test]
    fn place_horizontal_center_remainder_goes_right() {
        // position.go:66-73: totalGap = 3, split = round(1.5) = 2,
        // left = 3-2 = 1, right = 3-1 = 2.
        assert_eq!(s(&place_horizontal(5, CENTER, t("ab"))), " ab  ");
    }

    #[test]
    fn place_horizontal_noop_leaves_short_lines_unpadded() {
        // position.go:47-49: gap <= 0 returns the block unchanged, short
        // lines included.
        assert_eq!(s(&place_horizontal(3, LEFT, t("abc\na"))), "abc\na");
        assert_eq!(s(&place_horizontal(0, RIGHT, t("abc"))), "abc");
    }

    #[test]
    fn place_horizontal_center_multiline_short_line_rounding() {
        // position.go:66-73 line 2: short = 2, totalGap = 5,
        // split = round(2.5) = 3 (half away from zero), left = 2,
        // right = 3.
        let got = place_horizontal(6, CENTER, t("abc\na"));
        assert_eq!(s(&got), " abc  \n  a   ");
    }

    #[test]
    fn place_horizontal_fill_is_unstyled() {
        let got = place_horizontal(4, LEFT, t("x"));
        assert_eq!(got.lines[0].spans[1], Span::raw("   "));
    }

    // -- place_vertical (position.go:87-136) ---------------------------------------

    #[test]
    fn place_vertical_top_fill_rows_are_block_width_spaces() {
        // position.go:100-113: fill rows are ws.render(width) — spaces as
        // wide as the widest line, unstyled.
        let got = place_vertical(3, TOP, t("ab"));
        assert_eq!(s(&got), "ab\n  \n  ");
        assert_eq!(got.lines[1].spans[0], Span::raw("  "));
    }

    #[test]
    fn place_vertical_bottom() {
        // position.go:115-117.
        assert_eq!(s(&place_vertical(3, BOTTOM, t("ab"))), "  \n  \nab");
    }

    #[test]
    fn place_vertical_center_remainder_goes_bottom() {
        // position.go:119-131: gap = 3, split = round(1.5) = 2, top = 1,
        // bottom = 2.
        assert_eq!(s(&place_vertical(4, CENTER, t("ab"))), "  \nab\n  \n  ");
    }

    #[test]
    fn place_vertical_noop() {
        // position.go:91-94.
        assert_eq!(s(&place_vertical(1, TOP, t("a\nb"))), "a\nb");
    }

    #[test]
    fn place_combined() {
        // position.go:36-38: Place = PlaceVertical ∘ PlaceHorizontal.
        let got = place(5, 3, CENTER, CENTER, t("ab"));
        assert_eq!(s(&got), "     \n ab  \n     ");
    }

    // -- getLines tab expansion at join/place boundaries (get.go:630) -----------------

    /// A block built OUTSIDE [`text_from_str`] (as pane ports do for
    /// span-assembled content), keeping a literal tab.
    fn raw_tab() -> Text<'static> {
        Text::from(Line::from(Span::raw("a\tb")))
    }

    #[test]
    fn join_expands_tabs_like_get_lines() {
        // join.go:48-52 / 129-134 run every block through getLines, so
        // tabs expand to 4 spaces before measuring AND in the output
        // (Go: JoinVertical(Left, "a\tb", "cc") == "a    b\ncc    ").
        let got = join_vertical(LEFT, vec![raw_tab(), t("cc")]);
        assert_eq!(s(&got), "a    b\ncc    ");
        // Go: JoinHorizontal(Top, "a\tb", "c\nd") == "a    bc\n      d".
        let got = join_horizontal(TOP, vec![raw_tab(), t("c\nd")]);
        assert_eq!(s(&got), "a    bc\n      d");
    }

    #[test]
    fn place_horizontal_expands_tabs_when_placing_only() {
        // position.go:44-77: getLines supplies both the measurement and
        // the emitted lines (Go: PlaceHorizontal(8, Left, "a\tb") ==
        // "a    b  ").
        let got = place_horizontal(8, LEFT, raw_tab());
        assert_eq!(s(&got), "a    b  ");
        // position.go:47-49: the no-op path returns `str` — the ORIGINAL
        // block, tab kept — while the gap check still measures the
        // expanded width 6 (Go: PlaceHorizontal(6, Left, "a\tb") ==
        // "a\tb").
        let got = place_horizontal(6, LEFT, raw_tab());
        assert_eq!(s(&got), "a\tb");
    }

    #[test]
    fn place_vertical_measures_tabs_but_keeps_content_verbatim() {
        // position.go:100-105: emptyLine is ws.render(width) with width
        // from getLines (tab → 4 spaces) but the content block is written
        // back VERBATIM (Go: PlaceVertical(2, Top, "a\tb") ==
        // "a\tb\n      ").
        let got = place_vertical(2, TOP, raw_tab());
        assert_eq!(s(&got), "a\tb\n      ");
    }

    // -- GoStyle: core render path (style.go) --------------------------------------

    #[test]
    fn empty_style_renders_unchanged_with_tab_conversion() {
        // style.go:390-392 (props == 0) + maybeConvertTabs default 4.
        let got = even_run_style().render("x\ty");
        assert_eq!(s(&got), "x    y");
        assert_eq!(got.lines[0].spans[0].style, Style::default());
        // errorStyle (styles.go:577) is empty too.
        assert_eq!(s(&error_style().render("plain")), "plain");
    }

    #[test]
    fn bold_and_foreground_apply_to_content() {
        // style.go:311-334 core styling; headerStyle (styles.go:531).
        let got = header_style(true).render("Hi");
        let want = Style::default()
            .add_modifier(Modifier::BOLD)
            .fg(adaptive_to_color(COLOR_SUBHEADING, true));
        assert_eq!(got.lines[0].spans[0].style, want);
        assert_eq!(s(&got), "Hi");
    }

    #[test]
    fn width_pads_with_unstyled_spaces() {
        // style.go:487-501 + align.go:44-49: fill spaces carry only the
        // background — none here, so they are UNSTYLED (Tier-2 parity).
        let got = GoStyle::new().width(4).render("ab");
        assert_eq!(s(&got), "ab  ");
        assert_eq!(got.lines[0].spans.last().unwrap().style, Style::default());
    }

    #[test]
    fn help_key_style_pads_to_24() {
        // styles.go:789.
        let got = help_key_style(true).render("q");
        assert_eq!(text_width(&s(&got)), 24);
    }

    #[test]
    fn width_wraps_hardwrap_with_padding() {
        // style.go:406-410: wrapAt = width - padding; x/ansi
        // wrap.go:420-436 hardwraps "abcdef" at 4; then padding and the
        // align pass pad to width 6.
        let got = GoStyle::new().width(6).padding(&[0, 1]).render("abcdef");
        assert_eq!(s(&got), " abcd \n ef   ");
    }

    #[test]
    fn width_wraps_at_word_boundaries() {
        // x/ansi wrap.go:404-406 (spaces) + 432-435 (newline on
        // overflow); break spaces are dropped (addNewline resets the
        // space buffer, wrap.go:331-336).
        let got = GoStyle::new().width(5).render("foo bar baz");
        assert_eq!(s(&got), "foo  \nbar  \nbaz  ");
    }

    #[test]
    fn width_wrap_breaks_after_hyphen() {
        // x/ansi wrap.go:407-419: '-' is always a breakpoint; "aa-" fits
        // (2 < 4), "bb" then overflows 3+2 > 4 → newline.
        let got = GoStyle::new().width(4).render("aa-bb");
        assert_eq!(s(&got), "aa- \nbb  ");
    }

    #[test]
    fn wrap_preserves_trailing_spaces_that_fit() {
        // x/ansi wrap.go:448-458: at end of input pending spaces are
        // flushed if curWidth+spaceWidth <= limit.
        let got = GoStyle::new().width(4).render("ab ");
        assert_eq!(s(&got), "ab  ");
    }

    #[test]
    fn wrap_detaches_decomposed_mark_at_exact_boundary() {
        // x/ansi wrap.go:339-345: printable ASCII goes through the BYTE
        // parser, a grapheme cluster is only consumed at a UTF-8 lead
        // byte, so the mark of decomposed "e\u{301}" is its own
        // zero-width cluster. At wordLen == limit the base is flushed
        // (wrap.go:428-431) and the mark starts the NEXT word, wrapping
        // detached from its base (Go: Width(2).Render("ee\u{301}x") ==
        // "ee\n\u{301}x " — trailing pad from the align pass).
        let got = GoStyle::new().width(2).render("ee\u{301}x");
        assert_eq!(s(&got), "ee\n\u{301}x ");
        // Away from the boundary the sequence stays attached.
        let got = GoStyle::new().width(3).render("ee\u{301}x");
        assert_eq!(s(&got), "ee\u{301}x");
        // A run of marks travels as ONE zero-width tail cluster
        // (UAX #29 GB9: no break before Extend).
        let got = GoStyle::new().width(2).render("ee\u{301}\u{308}x");
        assert_eq!(s(&got), "ee\n\u{301}\u{308}x ");
    }

    #[test]
    fn wrap_splits_space_led_cluster_into_space_and_mark() {
        // wrap.go:404-406 vs 341-345: a mark following a space goes to
        // the WORD buffer (the space to the space buffer), so dropping
        // break spaces (addNewline, wrap.go:331-336) keeps the mark:
        // ansi.Wrap("ab \u{301}cd", 3, "") == "ab\n\u{301}cd" in Go.
        let got = wrap_lines(vec![Line::from("ab \u{301}cd")], 3);
        assert_eq!(text_to_string(&Text::from(got)), "ab\n\u{301}cd");
    }

    #[test]
    fn wrap_counts_ascii_base_and_vs16_tail_separately() {
        // wrap.go:341-345: "a\u{FE0F}" reaches wrap as 'a' (byte path,
        // width 1) plus a lone VS16 cluster (width 0) — NOT as the
        // width-2 VS16-promoted cluster ansi.StringWidth sees; the align
        // pass then measures the promoted width 2
        // (Go: Width(3).Render("a\u{FE0F}bcd") == "a\u{FE0F}bc\nd   ").
        let got = GoStyle::new().width(3).render("a\u{FE0F}bcd");
        assert_eq!(s(&got), "a\u{FE0F}bc\nd   ");
    }

    #[test]
    fn height_fills_below_and_align_sizes_rows() {
        // style.go:483-485 + align.go:66-67 (Top) add EMPTY lines; the
        // align pass (style.go:487-501) then pads them to the widest
        // line.
        let got = GoStyle::new().height(3).render("a");
        assert_eq!(s(&got), "a\n \n ");
    }

    #[test]
    fn width_and_height_render_a_space_box() {
        // mediapane.go:958 pattern: Width(w).Height(h).Render("") is a
        // w×h box of unstyled spaces.
        let got = GoStyle::new().width(3).height(2).render("");
        assert_eq!(s(&got), "   \n   ");
        for line in &got.lines {
            assert_eq!(line.spans[0].style, Style::default());
        }
    }

    #[test]
    fn height_only_on_empty_content_stays_empty_lines() {
        // systemmetricsgrid.go:688 pattern: Height(n).Render("") — the
        // widest line is 0, so the align pass adds no spaces.
        let got = GoStyle::new().height(2).render("");
        assert_eq!(s(&got), "\n");
        assert_eq!(block_height(&got), 2);
    }

    #[test]
    fn padding_without_background_is_unstyled() {
        // style.go:452-467: teWhitespace has no attributes without a
        // background (style.go:379-385).
        let got = GoStyle::new().padding(&[0, 1]).render("x");
        assert_eq!(s(&got), " x ");
        assert_eq!(got.lines[0].spans[0], Span::raw(" "));
        assert_eq!(got.lines[0].spans[2], Span::raw(" "));
    }

    #[test]
    fn padding_with_background_colors_the_padding() {
        // style.go:340-346 + 452-467: with a background, padding (and
        // fill) spaces carry the background only. statusBarStyle
        // (styles.go:571-574).
        let dark = true;
        let got = status_bar_style(dark).render("ok");
        let bg = adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark);
        assert_eq!(s(&got), " ok ");
        assert_eq!(got.lines[0].spans[0].style, Style::default().bg(bg));
        assert_eq!(
            got.lines[0].spans[1].style,
            Style::default().fg(rgb_to_color(MOON900)).bg(bg)
        );
        assert_eq!(got.lines[0].spans[2].style, Style::default().bg(bg));
    }

    #[test]
    fn padding_top_bottom_rows_are_sized_by_align() {
        // style.go:469-479 add bare newlines; align (style.go:487-501)
        // pads them to the block width.
        let got = GoStyle::new().padding(&[1, 2]).render("x");
        assert_eq!(s(&got), "     \n  x  \n     ");
    }

    // -- GoStyle: borders (borders.go) ---------------------------------------------

    #[test]
    fn rounded_border_snapshot() {
        // borders.go:86-100 runes; applyBorder borders.go:327-491. Short
        // line "c" is padded by the align pass BEFORE the border wraps it
        // (style.go:487-505 ordering).
        let dark = true;
        let got = border_style(dark).render("ab\nc");
        assert_eq!(s(&got), "╭──╮\n│ab│\n│c │\n╰──╯");
        let edge = Style::default().fg(adaptive_to_color(COLOR_LAYOUT, dark));
        assert_eq!(got.lines[0].spans[0].style, edge);
        assert_eq!(got.lines[1].spans[0].style, edge); // │
        assert_eq!(got.lines[1].spans[1].style, Style::default()); // content
        assert_eq!(got.lines[3].spans[0].style, edge);
    }

    #[test]
    fn normal_and_thick_border_runes() {
        // borders.go:70-84, 140-154.
        let got = GoStyle::new().border(normal_border()).render("x");
        assert_eq!(s(&got), "┌─┐\n│x│\n└─┘");
        let got = GoStyle::new().border(thick_border()).render("x");
        assert_eq!(s(&got), "┏━┓\n┃x┃\n┗━┛");
    }

    #[test]
    fn left_sidebar_border_renders_only_right_rule() {
        // styles.go:683-702: Border(RightBorder) + top/bottom/left off →
        // each line gets a colorLayout │ appended; no top/bottom rows.
        let dark = true;
        let got = left_sidebar_border_style(dark).render("ab\ncd");
        assert_eq!(s(&got), "ab│\ncd│");
        let edge = Style::default().fg(adaptive_to_color(COLOR_LAYOUT, dark));
        assert_eq!(got.lines[0].spans.last().unwrap().style, edge);
    }

    #[test]
    fn right_sidebar_border_renders_only_left_rule() {
        // styles.go:708-727.
        let got = right_sidebar_border_style(false).render("ab");
        assert_eq!(s(&got), "│ab");
    }

    #[test]
    fn border_top_only_suppresses_corners() {
        // borders.go:383-391: with no left/right sides the top corners
        // are dropped, leaving a bare rule as wide as the content.
        let got = GoStyle::new()
            .border(normal_border())
            .border_right(false)
            .border_bottom(false)
            .border_left(false)
            .render("ab");
        assert_eq!(s(&got), "──\nab");
    }

    #[test]
    fn border_without_top_keeps_bottom_corners() {
        // borders.go:392-404: bottom corners survive when left+right are
        // present.
        let got = GoStyle::new()
            .border(normal_border())
            .border_top(false)
            .render("ab");
        assert_eq!(s(&got), "│ab│\n└──┘");
    }

    #[test]
    fn border_consumes_width_budget() {
        // style.go:402-403: Width includes the border columns.
        let got = GoStyle::new().width(6).border(normal_border()).render("x");
        assert_eq!(s(&got), "┌────┐\n│x   │\n└────┘");
    }

    // -- GoStyle: margins (style.go:558-585) ----------------------------------------

    #[test]
    fn margins_add_unstyled_spaces() {
        // helpContentStyle (styles.go:795): MarginLeft(2) + MarginTop(1);
        // the top margin row is spaces as wide as the left-padded block
        // (style.go:566-573).
        let got = help_content_style().render("hi");
        assert_eq!(s(&got), "    \n  hi");
        assert_eq!(got.lines[0].spans[0], Span::raw("    "));
        assert_eq!(got.lines[1].spans[0], Span::raw("  "));
    }

    // -- GoStyle: MaxWidth / MaxHeight (style.go:509-526) -----------------------------

    #[test]
    fn max_width_truncates_by_display_width() {
        // x/ansi truncate.go: grapheme-aware, empty tail.
        assert_eq!(s(&GoStyle::new().max_width(2).render("abcd")), "ab");
        // Wide char that would straddle the boundary is dropped whole.
        assert_eq!(s(&GoStyle::new().max_width(3).render("a世b")), "a世");
        assert_eq!(s(&GoStyle::new().max_width(1).render("世")), "");
        // Under the limit → untouched.
        assert_eq!(s(&GoStyle::new().max_width(10).render("ab")), "ab");
    }

    #[test]
    fn max_height_keeps_first_lines() {
        // style.go:520-526.
        assert_eq!(s(&GoStyle::new().max_height(2).render("a\nb\nc")), "a\nb");
        assert_eq!(s(&GoStyle::new().max_height(5).render("a\nb")), "a\nb");
    }

    // -- styles.go style objects -------------------------------------------------------

    #[test]
    fn inspection_legend_style_colors() {
        // styles.go:558-566, light variants.
        let got = inspection_legend_style(false).render("v");
        assert_eq!(
            got.lines[0].spans[0].style,
            Style::default()
                .fg(adaptive_to_color(INSPECTION_LEGEND_FG, false))
                .bg(adaptive_to_color(INSPECTION_LEGEND_BG, false))
        );
    }

    #[test]
    fn focused_border_style_uses_highlight() {
        // styles.go:550.
        let dark = true;
        let got = focused_border_style(dark).render("x");
        assert_eq!(
            got.lines[0].spans[0].style,
            Style::default().fg(adaptive_to_color(COLOR_LAYOUT_HIGHLIGHT, dark))
        );
    }

    #[test]
    fn run_overview_tag_style_badge() {
        // styles.go:659-667: Padding(0,1) + Bold; fg/bg from the
        // contrast math in leet-charts.
        let dark = true;
        let bg_ac = run_overview_tag_background_color("sunset-glow", "prod");
        let fg_ac = run_overview_tag_foreground_color(bg_ac);
        let got = run_overview_tag_style("sunset-glow", "prod", dark).render("prod");
        let bg = adaptive_to_color(bg_ac, dark);
        assert_eq!(s(&got), " prod ");
        // Padding carries the background only.
        assert_eq!(got.lines[0].spans[0].style, Style::default().bg(bg));
        assert_eq!(
            got.lines[0].spans[1].style,
            Style::default()
                .add_modifier(Modifier::BOLD)
                .fg(adaptive_to_color(fg_ac, dark))
                .bg(bg)
        );
    }

    #[test]
    fn odd_run_style_blends_terminal_background() {
        // styles.go:97-109 + 808: 5% toward gray from the detected
        // terminal background.
        let term_bg = Rgb(0x1e, 0x1e, 0x1e);
        let want = blend_rgb(0x1e, 0x1e, 0x1e, 128, 128, 128, 0.05);
        let got = odd_run_style(Some(term_bg), true).render("row");
        assert_eq!(
            got.lines[0].spans[0].style,
            Style::default().bg(rgb_to_color(want))
        );
        assert_eq!(want, Rgb(0x22, 0x22, 0x22));
    }

    #[test]
    fn console_logs_highlighted_timestamp_padding_gets_background() {
        // styles.go:744-747: PaddingLeft(1) with Background(colorSelected)
        // → the pad cell is background-colored (colorWhitespace).
        let dark = true;
        let got = console_logs_pane_highlighted_timestamp_style(dark).render("12:00");
        let bg = adaptive_to_color(COLOR_SELECTED, dark);
        assert_eq!(s(&got), " 12:00");
        assert_eq!(got.lines[0].spans[0].style, Style::default().bg(bg));
        assert_eq!(
            got.lines[0].spans[1].style,
            Style::default().fg(rgb_to_color(COLOR_DARK)).bg(bg)
        );
    }

    #[test]
    fn zero_valued_margin_props_do_not_disturb_render() {
        // styles.go:689-692 / 714-717 set MarginBottom(0)/MarginLeft(0);
        // props are set but values are no-ops.
        let got = left_sidebar_header_style(true).render("Runs");
        assert_eq!(s(&got), "Runs");
        let got = right_sidebar_header_style(true).render("Metrics");
        assert_eq!(s(&got), "Metrics");
    }

    // -- separators (styles.go:754-776) ---------------------------------------------

    #[test]
    fn render_horizontal_separator_em_dashes() {
        let dark = true;
        let got = render_horizontal_separator(3, dark);
        assert_eq!(s(&got), "———");
        assert_eq!(
            got.lines[0].spans[0].style,
            Style::default().fg(adaptive_to_color(COLOR_LAYOUT, dark))
        );
        // styles.go:758-760: non-positive width renders empty.
        assert_eq!(s(&render_horizontal_separator(0, dark)), "");
    }

    #[test]
    fn join_with_separators_stacks_sections() {
        // styles.go:766-776.
        let got = join_with_separators(vec![t("s1"), t("s2")], 2, true);
        assert_eq!(s(&got), "s1\n——\ns2");
        assert_eq!(s(&join_with_separators(vec![], 2, true)), "");
        assert_eq!(s(&join_with_separators(vec![t("only")], 2, true)), "only");
    }

    // -- render_text patch semantics --------------------------------------------------

    #[test]
    fn render_text_patches_only_unset_span_fields() {
        // PARITY note in the module doc: container styles leave
        // pre-styled spans' own colors intact.
        let styled = Text::from(Line::from(Span::styled(
            "x",
            Style::default().fg(Color::Red),
        )));
        let got = GoStyle::new().width(3).render_text(styled);
        assert_eq!(got.lines[0].spans[0].style, Style::default().fg(Color::Red));
        assert_eq!(s(&got), "x  ");
    }
}
