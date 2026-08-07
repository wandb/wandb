//! Port of `core/internal/leet/help.go` — the full-screen help overlay.
//!
//! Content flows from the [`crate::keybindings`] tables (category order,
//! key names and descriptions are rendered verbatim from
//! `run_key_bindings` / `workspace_key_bindings` / `symon_key_bindings`
//! via [`help_entries_from_categories`] — never re-typed here), preceded
//! by the W&B/LEET ASCII art and the version/view header lines.
//!
//! PARITY: Go scrolls with `charm.land/bubbles/v2/viewport`; PORTING.md
//! prescribes NOT porting bubbles. [`HelpViewport`] is a minimal
//! line-window scroller reproducing exactly the viewport surface help.go
//! reaches: the default key map (bubbles viewport keymap.go
//! `DefaultKeyMap`), wheel scrolling (`MouseWheelDelta` = 3 lines,
//! shift/horizontal wheel = `defaultHorizontalStep` = 6 columns), and the
//! scroll-offset clamps of viewport.go (`SetYOffset`/`SetXOffset`).

use leet_charts::styles::{
    COLOR_HEADING, LEET_ART, STATUS_BAR_HEIGHT, WANDB_ART, default_dark_background,
};
use leet_data::width::grapheme_width;
use ratatui::style::Style;
use ratatui::text::{Line, Span, Text};

use crate::event::Event;
use crate::key::{KeyEvent, MouseButton, MouseEvent, MouseKind};
use crate::keybindings::{
    BindingCategory, run_key_bindings, symon_key_bindings, workspace_key_bindings,
};
use crate::layout::{
    GoStyle, LEFT, TOP, help_content_style, help_desc_style, help_key_style, help_section_style,
    join_horizontal, line_width, place, rgb_to_color, text_from_str,
};

/// PARITY: Go renders `version.Version` from `core/internal/version`
/// (version.go:5). Same string format; keep in sync with the Go constant.
pub const VERSION: &str = "0.28.2.dev1";

/// viewMode represents which top-level view is active.
// PARITY: Go declares `viewMode` in model.go:15-23; hosted here until
// model.rs lands (Phase 5) so this unit is self-contained — model.rs
// should re-export `crate::help::ViewMode`, not re-declare it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum ViewMode {
    /// Go `viewModeUndefined` (the zero value).
    #[default]
    Undefined,
    Workspace,
    Run,
    Symon,
}

/// The only command help's `Update` emits (Go returns `tea.Quit` from the
/// "q"/"ctrl+c" branch, help.go:195, and nil otherwise).
// PHASE-5: the model maps this to `Command::Quit` (CONCURRENCY.md §2.7).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum HelpCmd {
    Quit,
}

/// HelpEntry represents a single entry in the help screen.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct HelpEntry {
    pub key: String,
    pub description: String,
}

/// Go `var blankLine = HelpEntry{}`.
fn blank_line() -> HelpEntry {
    HelpEntry::default()
}

/// HelpModel represents the help screen.
#[derive(Debug, Clone)]
pub struct HelpModel {
    viewport: HelpViewport,
    active: bool,
    width: i64,
    height: i64,

    mode: ViewMode,

    /// PARITY: Go resolves adaptive colors lazily through the
    /// `darkBackground` global (styles.go:21-31, CONCURRENCY.md S13); the
    /// port resolves eagerly at content generation, so the flag lives on
    /// the model.
    dark: bool,
}

impl HelpModel {
    /// Port of `NewHelp`.
    pub fn new() -> HelpModel {
        // Go: viewport.New(viewport.WithWidth(80), viewport.WithHeight(20)).
        HelpModel {
            viewport: HelpViewport::new(80, 20),
            active: false,
            width: 0,
            height: 0,
            mode: ViewMode::Workspace,
            dark: default_dark_background(),
        }
    }

    pub fn set_mode(&mut self, mode: ViewMode) {
        self.mode = mode;
        if self.active {
            let content = self.generate_help_content();
            self.viewport.set_content(content);
        }
    }

    /// Replaces Go's global `SetDarkBackground` for this widget. Stores the
    /// flag only — like Go, content already in the viewport keeps its baked
    /// colors until the next regeneration (SetMode/SetSize/Toggle).
    pub fn set_dark_background(&mut self, dark: bool) {
        self.dark = dark;
    }

    /// generateHelpContent generates the help screen content.
    fn generate_help_content(&self) -> Text<'static> {
        let art_style = GoStyle::new()
            .foreground(rgb_to_color(COLOR_HEADING))
            .bold(true);

        let art_section = art_style.render_text(join_horizontal(
            TOP,
            vec![
                text_from_str(WANDB_ART),
                text_from_str("    "),
                text_from_str(LEET_ART),
            ],
        ));

        let entries = self.entries_for_mode();

        // Go builds `artSection + "\n\n"` then one "\n"-terminated line per
        // entry; split on '\n' that is: the art lines, one blank line, one
        // line per entry, and a trailing blank line (from the final "\n").
        let mut lines: Vec<Line<'static>> = art_section.lines;
        lines.push(Line::default());
        for entry in &entries {
            if entry.key.is_empty() {
                lines.push(Line::default());
            } else if entry.description.is_empty() {
                lines.extend(help_section_style().render(&entry.key).lines);
            } else {
                let key = help_key_style(self.dark).render(&entry.key);
                let desc = help_desc_style(self.dark).render(&entry.description);
                lines.extend(join_horizontal(TOP, vec![key, desc]).lines);
            }
        }
        lines.push(Line::default());
        Text::from(lines)
    }

    fn entries_for_mode(&self) -> Vec<HelpEntry> {
        let mut entries = vec![
            HelpEntry {
                key: "── W&B LEET: Lightweight Experiment Exploration Tool ──".to_string(),
                description: String::new(),
            },
            HelpEntry {
                key: "version".to_string(),
                description: VERSION.to_string(),
            },
            HelpEntry {
                key: "view".to_string(),
                description: self.mode_label().to_string(),
            },
            blank_line(),
        ];

        match self.mode {
            ViewMode::Workspace => {
                entries.extend(help_entries_from_categories(&workspace_key_bindings()));
                entries.extend(tips_entries());
            }
            ViewMode::Run => {
                entries.extend(help_entries_from_categories(&run_key_bindings()));
                entries.extend(tips_entries());
            }
            ViewMode::Symon => {
                entries.extend(help_entries_from_categories(&symon_key_bindings()));
                entries.extend(symon_tips_entries());
            }
            // PARITY: Go `default:` falls back to the workspace tables.
            ViewMode::Undefined => {
                entries.extend(help_entries_from_categories(&workspace_key_bindings()));
                entries.extend(tips_entries());
            }
        }

        entries
    }

    fn mode_label(&self) -> &'static str {
        match self.mode {
            ViewMode::Workspace => "workspace",
            ViewMode::Run => "single run",
            ViewMode::Symon => "symon",
            // PARITY: Go `default:`.
            ViewMode::Undefined => "unknown",
        }
    }

    /// SetSize updates the size of the help screen.
    pub fn set_size(&mut self, width: i64, height: i64) {
        self.width = width;
        self.height = height - STATUS_BAR_HEIGHT;
        self.viewport.set_width(width);
        self.viewport.set_height(self.height);

        if self.active {
            let content = self.generate_help_content();
            self.viewport.set_content(content);
        }
    }

    /// Toggle toggles the help screen visibility.
    pub fn toggle(&mut self) {
        self.active = !self.active;
        if self.active {
            self.viewport.goto_top();
            let content = self.generate_help_content();
            self.viewport.set_content(content);
        }
    }

    /// IsActive returns whether the help screen is active.
    pub fn is_active(&self) -> bool {
        self.active
    }

    /// Update handles messages for the help screen.
    pub fn update(&mut self, msg: &Event) -> Option<HelpCmd> {
        if !self.active {
            return None;
        }

        match msg {
            Event::Key(key) => match key.key_string().as_str() {
                "h" | "?" | "esc" => {
                    self.toggle();
                    None
                }
                "q" | "ctrl+c" => {
                    // Allow quitting from help screen
                    Some(HelpCmd::Quit)
                }
                _ => {
                    // Let viewport handle other keys
                    self.viewport.handle_key(key);
                    None
                }
            },
            Event::Mouse(mouse) => {
                // Let viewport handle mouse events
                self.viewport.handle_mouse(mouse);
                None
            }
            _ => None,
        }
    }

    /// View renders the help screen.
    pub fn view(&self) -> Text<'static> {
        if !self.active {
            // Go: tea.NewView("").
            return Text::default();
        }

        let content = help_content_style().render_text(self.viewport.view());

        // PARITY: helpContentStyle's margins make `content` 2 columns wider
        // and 1 line taller than the width×height box, so lipgloss.Place is
        // a no-op on both axes and the help view overflows exactly as in Go
        // (the terminal/compositor clips it).
        place(self.width, self.height, LEFT, TOP, content)
    }
}

impl Default for HelpModel {
    /// Go zero value is unused (NewHelp is the only constructor), so
    /// `Default` mirrors the constructor.
    fn default() -> Self {
        HelpModel::new()
    }
}

fn help_entries_from_categories<A>(categories: &[BindingCategory<A>]) -> Vec<HelpEntry> {
    let mut entries = Vec::new();
    for category in categories {
        entries.push(HelpEntry {
            key: category.name.to_string(),
            description: String::new(),
        });
        for binding in &category.bindings {
            entries.push(HelpEntry {
                key: binding.keys.join(", "),
                description: binding.description.to_string(),
            });
        }
        entries.push(blank_line());
    }
    entries
}

/// tipsEntries returns informational entries shown after the key bindings.
fn tips_entries() -> Vec<HelpEntry> {
    vec![
        HelpEntry {
            key: "Tips".to_string(),
            description: String::new(),
        },
        HelpEntry {
            key: "wandb leet config".to_string(),
            description: "Open the interactive config editor".to_string(),
        },
        HelpEntry {
            key: "Runs filter".to_string(),
            description: "Bare terms search run key/name/id/project/tags/notes. \
                          Qualifiers: project:, name:, id:, tag:, note:, config:, \
                          cfg.<path>:, has:. Boolean: space/AND, OR or |, -/!/NOT."
                .to_string(),
        },
        HelpEntry {
            key: "Runs filter example".to_string(),
            description: "project:vision tag:baseline cfg.lr>=1e-3 -note:debug | project:nlp"
                .to_string(),
        },
        blank_line(),
    ]
}

fn symon_tips_entries() -> Vec<HelpEntry> {
    vec![
        HelpEntry {
            key: "Tips".to_string(),
            description: String::new(),
        },
        HelpEntry {
            key: "wandb leet config".to_string(),
            description: "Open the interactive config editor".to_string(),
        },
        HelpEntry {
            key: "SYMON".to_string(),
            description: "Live system monitor".to_string(),
        },
        blank_line(),
    ]
}

// ---------------------------------------------------------------------------
// Minimal viewport (bubbles/v2 viewport subset help.go reaches).
// ---------------------------------------------------------------------------

/// viewport.go:151 `MouseWheelDelta` default.
const MOUSE_WHEEL_DELTA: i64 = 3;

/// viewport.go:16 `defaultHorizontalStep`.
const DEFAULT_HORIZONTAL_STEP: i64 = 6;

/// The subset of `bubbles/v2/viewport.Model` help.go uses, as a plain
/// line-window scroller over ratatui [`Line`]s (PORTING.md: "bubbles
/// viewport (help only) → Paragraph + scroll offset; do not port bubbles").
///
/// help.go never sets `Style`, `SoftWrap`, `FillHeight` or a gutter, and
/// never disables `MouseWheelEnabled`, so those knobs are omitted; the
/// remaining behavior (offset clamps, page/half-page/line steps, wheel
/// deltas, horizontal cut) is ported verbatim from viewport.go.
#[derive(Debug, Clone, Default)]
struct HelpViewport {
    width: i64,
    height: i64,
    /// yOffset is the vertical scroll position.
    y_offset: i64,
    /// xOffset is the horizontal scroll position.
    x_offset: i64,
    lines: Vec<Line<'static>>,
    longest_line_width: i64,
}

impl HelpViewport {
    fn new(width: i64, height: i64) -> HelpViewport {
        HelpViewport {
            width,
            height,
            ..Default::default()
        }
    }

    fn set_width(&mut self, w: i64) {
        self.width = w;
    }

    fn set_height(&mut self, h: i64) {
        self.height = h;
    }

    /// viewport.go:226-262 `SetContent`/`SetContentLines`. The port takes a
    /// [`Text`] (content is built line-structured; spans cannot embed
    /// newlines per the layout.rs contract, so the re-split half of
    /// SetContentLines has no equivalent).
    fn set_content(&mut self, text: Text<'static>) {
        self.lines = text.lines;
        // PARITY: viewport.go:236-238 — a single empty line means no
        // content at all.
        if self.lines.len() == 1 && line_width(&self.lines[0]) == 0 {
            self.lines = Vec::new();
        }
        self.longest_line_width = max_line_width(&self.lines);

        if self.y_offset > self.max_y_offset() {
            self.goto_bottom();
        }
    }

    /// viewport.go:183-185.
    fn at_top(&self) -> bool {
        self.y_offset <= 0
    }

    /// viewport.go:188-191.
    fn at_bottom(&self) -> bool {
        self.y_offset >= self.max_y_offset()
    }

    /// viewport.go:301-306 (help sets no Style, so the frame size is 0).
    fn max_y_offset(&self) -> i64 {
        (self.lines.len() as i64 - self.height).max(0)
    }

    /// viewport.go:308-312.
    fn max_x_offset(&self) -> i64 {
        (self.longest_line_width - self.width).max(0)
    }

    /// viewport.go:463-466.
    fn set_y_offset(&mut self, n: i64) {
        self.y_offset = clamp(n, 0, self.max_y_offset());
    }

    /// viewport.go:550-557 (SoftWrap is never enabled by help).
    fn set_x_offset(&mut self, n: i64) {
        self.x_offset = clamp(n, 0, self.max_x_offset());
    }

    /// viewport.go:485-491.
    fn page_down(&mut self) {
        if self.at_bottom() {
            return;
        }
        self.scroll_down(self.height);
    }

    /// viewport.go:493-499.
    fn page_up(&mut self) {
        if self.at_top() {
            return;
        }
        self.scroll_up(self.height);
    }

    /// viewport.go:501-507.
    fn half_page_down(&mut self) {
        if self.at_bottom() {
            return;
        }
        self.scroll_down(self.height / 2);
    }

    /// viewport.go:509-515.
    fn half_page_up(&mut self) {
        if self.at_top() {
            return;
        }
        self.scroll_up(self.height / 2);
    }

    /// viewport.go:517-527 (the highlight bookkeeping is not ported; help
    /// never sets highlights).
    fn scroll_down(&mut self, n: i64) {
        if self.at_bottom() || n == 0 || self.lines.is_empty() {
            return;
        }
        self.set_y_offset(self.y_offset + n);
    }

    /// viewport.go:529-538.
    fn scroll_up(&mut self, n: i64) {
        if self.at_top() || n == 0 || self.lines.is_empty() {
            return;
        }
        self.set_y_offset(self.y_offset - n);
    }

    /// viewport.go:559-562.
    fn scroll_left(&mut self, n: i64) {
        self.set_x_offset(self.x_offset - n);
    }

    /// viewport.go:564-567.
    fn scroll_right(&mut self, n: i64) {
        self.set_x_offset(self.x_offset + n);
    }

    /// viewport.go:580-588.
    fn goto_top(&mut self) {
        if self.at_top() {
            return;
        }
        self.set_y_offset(0);
    }

    /// viewport.go:590-595.
    fn goto_bottom(&mut self) {
        self.set_y_offset(self.max_y_offset());
    }

    /// The key half of viewport.go:663-694 `updateAsModel`, with keymap.go
    /// `DefaultKeyMap` inlined. bubbles `key.Matches` compares
    /// `msg.String()`, which [`KeyEvent::key_string`] ports, so the match
    /// strings below are the DefaultKeyMap key lists verbatim.
    fn handle_key(&mut self, msg: &KeyEvent) {
        match msg.key_string().as_str() {
            "pgdown" | "space" | "f" => self.page_down(),
            "pgup" | "b" => self.page_up(),
            "d" | "ctrl+d" => self.half_page_down(),
            "u" | "ctrl+u" => self.half_page_up(),
            "down" | "j" => self.scroll_down(1),
            "up" | "k" => self.scroll_up(1),
            // PARITY: DefaultKeyMap binds "h" to Left too, but help.go's
            // own "h" (toggle) branch shadows it before the viewport ever
            // sees the key; kept for a verbatim table.
            "left" | "h" => self.scroll_left(DEFAULT_HORIZONTAL_STEP),
            "right" | "l" => self.scroll_right(DEFAULT_HORIZONTAL_STEP),
            _ => {}
        }
    }

    /// The mouse half of viewport.go:696-722 `updateAsModel`: only wheel
    /// messages scroll (`MouseWheelEnabled` defaults to true and help never
    /// disables it); click/release/motion fall through unchanged.
    fn handle_mouse(&mut self, msg: &MouseEvent) {
        if msg.kind != MouseKind::Wheel {
            return;
        }
        match msg.button {
            MouseButton::WheelDown => {
                // Go `msg.Mod.Contains(tea.ModShift)` — contains, not
                // equality, so e.g. alt+shift+wheel also scrolls sideways.
                if msg.mods.shift {
                    self.scroll_right(DEFAULT_HORIZONTAL_STEP);
                } else {
                    self.scroll_down(MOUSE_WHEEL_DELTA);
                }
            }
            MouseButton::WheelUp => {
                if msg.mods.shift {
                    self.scroll_left(DEFAULT_HORIZONTAL_STEP);
                } else {
                    self.scroll_up(MOUSE_WHEEL_DELTA);
                }
            }
            MouseButton::WheelLeft => self.scroll_left(DEFAULT_HORIZONTAL_STEP),
            MouseButton::WheelRight => self.scroll_right(DEFAULT_HORIZONTAL_STEP),
            _ => {}
        }
    }

    /// viewport.go:330-365 `visibleLines` on the paths help reaches
    /// (SoftWrap false, FillHeight false, no gutter, no highlights).
    fn visible_lines(&self) -> Vec<Line<'static>> {
        let max_height = self.height.max(0);
        let max_width = self.width.max(0);

        if max_height == 0 || max_width == 0 {
            return Vec::new();
        }

        let total = self.lines.len() as i64;
        let mut lines: Vec<Line<'static>> = Vec::new();
        if total > 0 {
            let ridx = self.y_offset.min(total);
            let bottom = clamp(ridx + max_height, ridx, total);
            lines = self.lines[ridx as usize..bottom as usize].to_vec();
        }

        // viewport.go:352-354: if the longest line fits and we're not
        // horizontally scrolled, no cutting is needed.
        if (self.x_offset == 0 && self.longest_line_width <= max_width) || max_width == 0 {
            return lines;
        }

        // Cut the lines to the viewport width (viewport.go:361-363).
        lines
            .into_iter()
            .map(|l| cut_line(&l, self.x_offset, self.x_offset + max_width))
            .collect()
    }

    /// viewport.go:728-750 `View`: the visible window padded to exactly
    /// width×height with unstyled spaces (`lipgloss Width+Height render`;
    /// help sets no `Style`, so the outer style pass is a no-op).
    fn view(&self) -> Text<'static> {
        let (w, h) = (self.width, self.height);
        if w == 0 || h == 0 {
            return text_from_str("");
        }
        GoStyle::new()
            .width(w)
            .height(h)
            .render_text(Text::from(self.visible_lines()))
    }
}

/// viewport.go:752-757 `clamp` (swaps the bounds if inverted).
fn clamp(v: i64, low: i64, high: i64) -> i64 {
    let (low, high) = if high < low { (high, low) } else { (low, high) };
    if v < low {
        low
    } else if v > high {
        high
    } else {
        v
    }
}

/// viewport.go:759-765 `maxLineWidth` (ansi.StringWidth → the width shim
/// via [`line_width`]).
fn max_line_width(lines: &[Line<'static>]) -> i64 {
    lines.iter().map(line_width).max().unwrap_or(0) as i64
}

/// x/ansi `Cut(s, left, right)` (truncate.go:15-46) over spans: truncate
/// to `right` columns, then drop the first `left` columns.
fn cut_line(line: &Line<'static>, left: i64, right: i64) -> Line<'static> {
    if right <= left {
        return Line::default();
    }
    let truncated = truncate_line_right(line, right);
    if left == 0 {
        return truncated;
    }
    truncate_line_left(truncated, left)
}

/// x/ansi truncate.go `truncate` — keep the longest grapheme prefix whose
/// width fits in `length`, empty tail.
// PARITY: duplicated from layout.rs's private `truncate_line` (this unit
// may not modify layout.rs); keep the two in sync.
fn truncate_line_right(line: &Line<'static>, length: i64) -> Line<'static> {
    if line_width(line) as i64 <= length {
        return line.clone();
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
                // Once over, ignore all remaining printable content.
                ignoring = true;
                break;
            }
            cur_width += w;
            kept.push_str(g.symbol);
        }
        if !kept.is_empty() {
            out.push(Span::styled(kept, span.style));
        }
    }
    Line::from(out)
}

/// x/ansi truncate.go:187-266 `truncateLeft` (empty prefix): drop grapheme
/// clusters until their cumulative width exceeds `n`; the cluster
/// straddling the boundary is emitted whole (Go writes the full cluster
/// once `curWidth > n`), then everything after passes through.
fn truncate_line_left(line: Line<'static>, n: i64) -> Line<'static> {
    if n <= 0 {
        return line;
    }
    let mut out: Vec<Span<'static>> = Vec::new();
    let mut cur_width: i64 = 0;
    let mut emitting = false;
    for span in &line.spans {
        if emitting {
            out.push(span.clone());
            continue;
        }
        let mut kept = String::new();
        for g in span.styled_graphemes(Style::default()) {
            if emitting {
                kept.push_str(g.symbol);
                continue;
            }
            cur_width += grapheme_width(g.symbol) as i64;
            if cur_width > n {
                emitting = true;
                kept.push_str(g.symbol);
            }
        }
        if !kept.is_empty() {
            out.push(Span::styled(kept, span.style));
        }
    }
    Line::from(out)
}

// ---------------------------------------------------------------------------
// Tests. Go has no help_test.go, so all tests below are Rust-only; the
// rendered overlay itself is covered by the differential harness.
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use pretty_assertions::assert_eq;

    use super::*;
    use crate::key::{KeyCode, KeyMods};
    use crate::layout::{adaptive_to_color, text_to_string};
    use leet_charts::styles::COLOR_SUBHEADING;

    /// Builds the KeyEvent Bubble Tea would report for a binding-style key
    /// string (the subset these tests press).
    fn key(s: &str) -> KeyEvent {
        let (code, text, mods) = match s {
            "up" => (KeyCode::Up, None, KeyMods::NONE),
            "down" => (KeyCode::Down, None, KeyMods::NONE),
            "left" => (KeyCode::Left, None, KeyMods::NONE),
            "right" => (KeyCode::Right, None, KeyMods::NONE),
            "pgup" => (KeyCode::PgUp, None, KeyMods::NONE),
            "pgdown" => (KeyCode::PgDown, None, KeyMods::NONE),
            "esc" => (KeyCode::Esc, None, KeyMods::NONE),
            "space" => (KeyCode::Space, Some(" ".to_string()), KeyMods::NONE),
            "ctrl+c" => (KeyCode::Char('c'), None, KeyMods::CTRL),
            "ctrl+u" => (KeyCode::Char('u'), None, KeyMods::CTRL),
            "ctrl+d" => (KeyCode::Char('d'), None, KeyMods::CTRL),
            s => {
                let mut chars = s.chars();
                let c = chars.next().unwrap();
                assert_eq!(chars.next(), None, "single-char key expected: {s:?}");
                (KeyCode::Char(c), Some(c.to_string()), KeyMods::NONE)
            }
        };
        KeyEvent { code, text, mods }
    }

    fn press(h: &mut HelpModel, s: &str) -> Option<HelpCmd> {
        h.update(&Event::Key(key(s)))
    }

    fn wheel(button: MouseButton, mods: KeyMods) -> Event {
        Event::Mouse(MouseEvent {
            kind: MouseKind::Wheel,
            button,
            x: 0,
            y: 0,
            mods,
        })
    }

    /// A fresh help model sized and toggled open.
    fn open_help(width: i64, height: i64) -> HelpModel {
        let mut h = HelpModel::new();
        h.set_size(width, height);
        h.toggle();
        h
    }

    fn content_string(h: &HelpModel) -> String {
        text_to_string(&Text::from(h.viewport.lines.clone()))
    }

    fn expected_entry_count<A>(categories: &[BindingCategory<A>], tips: usize) -> usize {
        // 4 header entries + per category (name + bindings + blank) + tips.
        4 + categories
            .iter()
            .map(|c| 2 + c.bindings.len())
            .sum::<usize>()
            + tips
    }

    /// Every category name, key list and description of a binding table
    /// must appear in `content`. The key column wraps at 24 columns
    /// (helpKeyStyle `Width(24)` word-wraps in lipgloss, e.g. symon's
    /// "w, up, s, down, a, left, d, right"), so joined key lists are
    /// compared post-wrap, line by line.
    fn assert_content_has_categories<A>(content: &str, categories: &[BindingCategory<A>]) {
        for category in categories {
            assert!(
                content.contains(category.name),
                "missing {:?}",
                category.name
            );
            for binding in &category.bindings {
                let keys = binding.keys.join(", ");
                let key_col = text_to_string(&help_key_style(true).render(&keys));
                for line in key_col.split('\n') {
                    let line = line.trim_end();
                    assert!(
                        content.contains(line),
                        "missing key text {line:?} of {keys:?}"
                    );
                }
                assert!(
                    content.contains(binding.description),
                    "missing description {:?}",
                    binding.description
                );
            }
        }
    }

    /// Rust-only: every category name, joined key list and description of
    /// the mode's binding table appears verbatim in the generated content —
    /// the overlay flows from keybindings.rs, it does not re-type strings.
    #[test]
    fn content_flows_from_binding_tables() {
        let mut h = open_help(200, 60);

        h.set_mode(ViewMode::Workspace);
        assert_content_has_categories(&content_string(&h), &workspace_key_bindings());

        h.set_mode(ViewMode::Run);
        assert_content_has_categories(&content_string(&h), &run_key_bindings());

        h.set_mode(ViewMode::Symon);
        let content = content_string(&h);
        assert_content_has_categories(&content, &symon_key_bindings());
        assert!(content.contains("Live system monitor"));
    }

    /// Rust-only: locks the line structure Go's string concatenation
    /// produces — 7 art lines, a blank, the header entries, one line per
    /// entry, and a trailing blank line.
    #[test]
    fn content_line_structure_matches_go_string_shape() {
        let h = open_help(200, 60);
        let content = content_string(&h);
        let lines: Vec<&str> = content.split('\n').collect();

        assert_eq!(
            lines.len(),
            7 + 1 + expected_entry_count(&workspace_key_bindings(), 5) + 1
        );

        // Art block: leading blank row (the raw literals start with "\n"),
        // then the glyph rows joined with the 4-space separator.
        assert_eq!(lines[0].trim(), "");
        assert!(lines[1].contains("██     ██  █████"));
        assert!(lines[1].contains("██      ███████ ███████ ████████"));
        // Blank separator from Go's `+ "\n\n"`.
        assert_eq!(lines[7], "");
        // Header entries: section line, then key column padded to 24.
        assert_eq!(
            lines[8],
            "── W&B LEET: Lightweight Experiment Exploration Tool ──"
        );
        assert_eq!(lines[9], format!("version{}{}", " ".repeat(17), VERSION));
        assert_eq!(lines[10], format!("view{}workspace", " ".repeat(20)));
        assert_eq!(lines[11], "");
        assert_eq!(lines[12], "General");
        // Trailing blank line from the final "\n".
        assert_eq!(lines[lines.len() - 1], "");
    }

    /// Rust-only: modeLabel and the per-mode table/tips selection,
    /// including the Go `default:` fallback for the undefined mode.
    #[test]
    fn set_mode_switches_label_tables_and_tips() {
        let mut h = open_help(200, 60);

        for (mode, label, marker) in [
            (ViewMode::Workspace, "workspace", "Toggle runs sidebar"),
            (
                ViewMode::Run,
                "single run",
                "Toggle left sidebar with run overview",
            ),
            (ViewMode::Symon, "symon", "Live system monitor"),
            (ViewMode::Undefined, "unknown", "Toggle runs sidebar"),
        ] {
            h.set_mode(mode);
            let content = content_string(&h);
            assert!(
                content.contains(&format!("view{}{}", " ".repeat(20), label)),
                "mode {mode:?}: label {label:?} missing"
            );
            assert!(
                content.contains(marker),
                "mode {mode:?}: {marker:?} missing"
            );
        }

        // Symon swaps the runs-filter tips for the symon tips.
        h.set_mode(ViewMode::Symon);
        assert!(!content_string(&h).contains("Runs filter example"));
        h.set_mode(ViewMode::Workspace);
        assert!(content_string(&h).contains("Runs filter example"));
    }

    /// Rust-only: Toggle activates, regenerates content and jumps to the
    /// top; SetMode/SetSize only regenerate while active (help.go guards).
    #[test]
    fn toggle_and_regeneration_guards() {
        let mut h = HelpModel::new();
        assert!(!h.is_active());

        // Inactive SetMode/SetSize do not populate the viewport.
        h.set_mode(ViewMode::Run);
        h.set_size(120, 40);
        assert!(h.viewport.lines.is_empty());

        h.toggle();
        assert!(h.is_active());
        assert!(!h.viewport.lines.is_empty());
        assert_eq!(h.viewport.y_offset, 0);

        // Scroll away, close, reopen: GotoTop before SetContent.
        press(&mut h, "space");
        assert!(h.viewport.y_offset > 0);
        h.toggle();
        assert!(!h.is_active());
        h.toggle();
        assert_eq!(h.viewport.y_offset, 0);
    }

    /// Rust-only: the DefaultKeyMap scroll keys move the window exactly as
    /// bubbles' viewport does — line, page, half page — with the
    /// AtTop/AtBottom no-op guards and offset clamps.
    #[test]
    fn key_scrolling_matches_viewport() {
        let mut h = open_help(80, 11); // viewport is 80×10
        let total = h.viewport.lines.len() as i64;
        let max_y = total - 10;
        assert!(max_y > 20, "content should overflow the window");

        for (k, want) in [
            ("j", 1),
            ("down", 2),
            ("k", 1),
            ("up", 0),
            ("up", 0), // AtTop: no-op
            ("space", 10),
            ("f", 20),
            ("pgdown", 30),
            ("b", 20),
            ("pgup", 10),
            ("d", 15),
            ("u", 10),
            ("ctrl+d", 15),
            ("ctrl+u", 10),
        ] {
            assert_eq!(press(&mut h, k), None);
            assert_eq!(h.viewport.y_offset, want, "after key {k:?}");
        }

        // Page to the bottom: the offset clamps to maxYOffset and further
        // downward keys are no-ops.
        for _ in 0..50 {
            press(&mut h, "f");
        }
        assert_eq!(h.viewport.y_offset, max_y);
        press(&mut h, "j");
        assert_eq!(h.viewport.y_offset, max_y);
        press(&mut h, "space");
        assert_eq!(h.viewport.y_offset, max_y);
    }

    /// Rust-only: wheel scrolling — 3 lines vertically, 6 columns for
    /// shift+wheel and horizontal wheels, X clamped to
    /// longestLineWidth − width; non-wheel mouse events are ignored.
    #[test]
    fn wheel_scrolling_matches_viewport() {
        let mut h = open_help(40, 11);
        let max_x = h.viewport.longest_line_width - 40;
        assert!(max_x > 6, "content should overflow horizontally");

        h.update(&wheel(MouseButton::WheelDown, KeyMods::NONE));
        assert_eq!(h.viewport.y_offset, 3);
        h.update(&wheel(MouseButton::WheelDown, KeyMods::NONE));
        assert_eq!(h.viewport.y_offset, 6);
        h.update(&wheel(MouseButton::WheelUp, KeyMods::NONE));
        assert_eq!(h.viewport.y_offset, 3);

        h.update(&wheel(MouseButton::WheelDown, KeyMods::SHIFT));
        assert_eq!((h.viewport.y_offset, h.viewport.x_offset), (3, 6));
        h.update(&wheel(MouseButton::WheelUp, KeyMods::SHIFT));
        assert_eq!((h.viewport.y_offset, h.viewport.x_offset), (3, 0));

        h.update(&wheel(MouseButton::WheelRight, KeyMods::NONE));
        assert_eq!(h.viewport.x_offset, 6);
        h.update(&wheel(MouseButton::WheelLeft, KeyMods::NONE));
        assert_eq!(h.viewport.x_offset, 0);

        // X clamps at longestLineWidth − width.
        for _ in 0..1000 {
            h.update(&wheel(MouseButton::WheelRight, KeyMods::NONE));
        }
        assert_eq!(h.viewport.x_offset, max_x);

        // Clicks/motion never scroll (viewport only reacts to wheel msgs).
        h.update(&Event::Mouse(MouseEvent {
            kind: MouseKind::Click,
            button: MouseButton::Left,
            x: 1,
            y: 1,
            mods: KeyMods::NONE,
        }));
        assert_eq!((h.viewport.y_offset, h.viewport.x_offset), (3, max_x));
    }

    /// Rust-only: the help.go Update switch — h/?/esc toggle, q/ctrl+c quit
    /// (without deactivating), everything ignored while inactive.
    #[test]
    fn update_key_routing_matches_help_go() {
        let mut h = open_help(80, 24);

        assert_eq!(press(&mut h, "q"), Some(HelpCmd::Quit));
        assert!(h.is_active(), "quit does not deactivate help");
        assert_eq!(press(&mut h, "ctrl+c"), Some(HelpCmd::Quit));

        for k in ["h", "?", "esc"] {
            assert!(h.is_active());
            assert_eq!(press(&mut h, k), None);
            assert!(!h.is_active(), "key {k:?} should close help");
            h.toggle();
        }

        // Inactive: no scrolling, no quit, empty view.
        h.toggle();
        assert!(!h.is_active());
        assert_eq!(press(&mut h, "j"), None);
        assert_eq!(press(&mut h, "q"), None);
        assert_eq!(h.viewport.y_offset, 0);
        assert_eq!(h.view(), Text::default());
    }

    /// Rust-only: View shape — the viewport pads to width×(height−1), the
    /// content style adds 2 columns of left margin and 1 top-margin row,
    /// and Place is a no-op on the resulting oversized block (Go quirk:
    /// the overlay overflows its box and the terminal clips it).
    #[test]
    fn view_dimensions_match_go() {
        let mut h = open_help(80, 24); // h.height = 23
        let view = h.view();
        assert_eq!(view.lines.len(), 24); // 23 + top margin row
        for (i, line) in view.lines.iter().enumerate() {
            assert_eq!(line_width(line), 82, "line {i}"); // 80 + left margin
        }
        // Top margin row and margined content rows.
        assert_eq!(
            text_to_string(&Text::from(vec![view.lines[0].clone()])).trim(),
            ""
        );
        assert!(text_to_string(&Text::from(vec![view.lines[2].clone()])).starts_with("  "));

        // Scrolled all the way down the window stays fully padded.
        for _ in 0..50 {
            press(&mut h, "f");
        }
        let view = h.view();
        assert_eq!(view.lines.len(), 24);
        for line in &view.lines {
            assert_eq!(line_width(line), 82);
        }
    }

    /// Rust-only: horizontal window math — visible lines are cut to
    /// [xOffset, xOffset+width) like ansi.Cut, including the Go quirk that
    /// a wide cluster straddling the left bound is emitted whole.
    #[test]
    fn horizontal_cut_matches_ansi_cut() {
        let mut vp = HelpViewport::new(3, 2);
        vp.set_content(text_from_str("abcdef\nxy"));
        vp.scroll_right(DEFAULT_HORIZONTAL_STEP); // clamps to 6-3=3
        assert_eq!(vp.x_offset, 3);
        let visible = Text::from(vp.visible_lines());
        assert_eq!(text_to_string(&visible), "def\n");

        // PARITY: x/ansi truncateLeft keeps the cluster that crosses the
        // left bound: Cut("世界", 1, 3) = "世".
        assert_eq!(
            text_to_string(&Text::from(vec![cut_line(&Line::from("世界"), 1, 3)])),
            "世"
        );
        // And the right bound drops a wide cluster that does not fit:
        // Cut("a世b", 0, 2) = "a".
        assert_eq!(
            text_to_string(&Text::from(vec![cut_line(&Line::from("a世b"), 0, 2)])),
            "a"
        );
    }

    /// Rust-only: SetContent clamps a stale offset to the new bottom
    /// (viewport.go:259-261) and treats a single empty line as no content
    /// (viewport.go:236-238).
    #[test]
    fn set_content_clamps_offset_and_drops_empty() {
        let mut vp = HelpViewport::new(10, 2);
        vp.set_content(text_from_str("a\nb\nc\nd\ne"));
        vp.set_y_offset(3);
        vp.set_content(text_from_str("a\nb\nc"));
        assert_eq!(vp.y_offset, 1); // maxYOffset = 3-2

        vp.set_content(text_from_str(""));
        assert!(vp.lines.is_empty());
        assert_eq!(vp.y_offset, 0);
    }

    /// Rust-only: the eager dark-flag replacement for Go's darkBackground
    /// global — the flag is picked up at the next content regeneration,
    /// not retroactively (matching Go's bake-at-Render timing).
    #[test]
    fn dark_background_applies_on_next_regeneration() {
        let mut h = open_help(200, 60);
        h.set_dark_background(true);
        h.set_mode(ViewMode::Workspace); // regenerate
        let key_span_style = h.viewport.lines[9].spans[0].style;
        assert_eq!(
            key_span_style.fg,
            Some(adaptive_to_color(COLOR_SUBHEADING, true))
        );

        // Flag change alone leaves the baked content untouched...
        h.set_dark_background(false);
        assert_eq!(
            h.viewport.lines[9].spans[0].style.fg,
            Some(adaptive_to_color(COLOR_SUBHEADING, true))
        );
        // ...until the next regeneration.
        h.set_mode(ViewMode::Workspace);
        assert_eq!(
            h.viewport.lines[9].spans[0].style.fg,
            Some(adaptive_to_color(COLOR_SUBHEADING, false))
        );
    }
}
