//! Port of `core/internal/leet/flexlayout.go`.
//!
//! A small flexbox-style vertical stack for the central column plus sidebar
//! width helpers. Pure layout math; Go `int` ports as `isize` (PORTING.md
//! numeric rules).

use leet_charts::styles::{
    SIDEBAR_BORDER_COLS, SIDEBAR_MAX_WIDTH, SIDEBAR_MIN_WIDTH, SIDEBAR_OVERHEAD,
    SIDEBAR_WIDTH_RATIO, SIDEBAR_WIDTH_RATIO_BOTH,
};
use leet_data::width::line_width;

/// stackSectionID identifies a vertically stacked pane in the main content
/// area.
///
/// PARITY: Go declares this as an `int` iota enum (flexlayout.go:6-14); the
/// discriminants below are the iota values and double as the index into
/// [`VerticalStackLayout::sections`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum StackSectionId {
    Metrics = 0,
    // PARITY: PARITY.md flags stackSectionSystemMetrics as likely dead code;
    // ported mechanically regardless (referenced from workspace.go
    // computeViewports, workspace.go:518-549).
    SystemMetrics = 1,
    Media = 2,
    ConsoleLogs = 3,
}

/// Go `stackSectionCount` (flexlayout.go:13): the length of the fixed
/// per-section layout array.
pub const STACK_SECTION_COUNT: usize = 4;

/// stackSectionSpec describes one pane in a vertical stack.
#[derive(Debug, Clone, Copy)]
pub struct StackSectionSpec {
    pub id: StackSectionId,
    pub visible: bool,
    pub height: isize,
    pub flex: bool,
}

/// stackSectionLayout stores the computed origin and height of one pane.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct StackSectionLayout {
    pub y: isize,
    pub height: isize,
}

/// verticalStackLayout is a small flexbox-style layout for the central column.
///
/// Fixed-height panes (system/media/logs) keep their current animated heights.
/// The optional flex pane (metrics) consumes the remaining height after gaps.
#[derive(Debug, Clone, Copy, Default)]
pub struct VerticalStackLayout {
    pub total_height: isize,
    pub visible_count: isize,
    pub sections: [StackSectionLayout; STACK_SECTION_COUNT],
}

/// computeVerticalStackLayout computes a top-to-bottom stack with a 1-line gap
/// between adjacent visible panes.
pub fn compute_vertical_stack_layout(
    total_height: isize,
    specs: &[StackSectionSpec],
) -> VerticalStackLayout {
    let mut layout = VerticalStackLayout {
        total_height: total_height.max(0),
        ..Default::default()
    };

    let mut visible: Vec<StackSectionSpec> = Vec::with_capacity(specs.len());
    let mut fixed_height: isize = 0;
    let mut flex_index: isize = -1;
    for spec in specs {
        if !spec.visible {
            continue;
        }
        let mut spec = *spec;
        spec.height = spec.height.max(0);
        if spec.flex {
            // PARITY: like Go (flexlayout.go:56-60), a later flex spec simply
            // overwrites flexIndex; earlier flex specs keep their clamped
            // height and are never counted into fixedHeight.
            flex_index = visible.len() as isize;
        } else {
            fixed_height += spec.height;
        }
        visible.push(spec);
    }

    layout.visible_count = visible.len() as isize;
    if visible.is_empty() {
        return layout;
    }

    let gap_lines = (visible.len() as isize - 1).max(0);
    let remaining = (layout.total_height - fixed_height - gap_lines).max(0);
    if flex_index >= 0 {
        visible[flex_index as usize].height = remaining;
    }

    let mut y: isize = 0;
    for (i, spec) in visible.iter().enumerate() {
        layout.sections[spec.id as usize] = StackSectionLayout {
            y,
            height: spec.height,
        };
        y += spec.height;
        if i < visible.len() - 1 {
            y += 1;
        }
    }

    layout
}

impl VerticalStackLayout {
    // PARITY: Go's Height/Y bounds-check `id < 0 || id >= stackSectionCount`
    // and return 0 (flexlayout.go:87-99); `StackSectionId` makes out-of-range
    // ids unrepresentable, so the guard is dropped.
    pub fn height(&self, id: StackSectionId) -> isize {
        self.sections[id as usize].height
    }

    pub fn y(&self, id: StackSectionId) -> isize {
        self.sections[id as usize].y
    }
}

pub fn expanded_sidebar_width(terminal_width: isize, opposite_visible: bool) -> isize {
    let mut ratio = SIDEBAR_WIDTH_RATIO;
    if opposite_visible {
        ratio = SIDEBAR_WIDTH_RATIO_BOTH;
    }
    // PARITY: Go `int(float64(terminalWidth) * ratio)` truncates toward zero
    // (flexlayout.go:106); Rust `as isize` matches.
    clamp(
        (terminal_width as f64 * ratio) as isize,
        SIDEBAR_MIN_WIDTH as isize,
        SIDEBAR_MAX_WIDTH as isize,
    )
}

/// sidebarContentWidth returns the width available for text content inside a
/// sidebar after subtracting the vertical border and both padding columns.
pub fn sidebar_content_width(total_width: isize) -> isize {
    (total_width - SIDEBAR_OVERHEAD as isize).max(0)
}

/// sidebarInnerWidth returns the width to pass to the sidebar's lipgloss Style
/// (includes content + padding, excludes the border column).
pub fn sidebar_inner_width(total_width: isize) -> isize {
    (total_width - SIDEBAR_BORDER_COLS as isize).max(0)
}

pub fn filter_non_empty_sections(sections: Vec<String>) -> Vec<String> {
    let mut filtered = Vec::with_capacity(sections.len());
    for section in sections {
        if section.is_empty() {
            continue;
        }
        filtered.push(section);
    }
    filtered
}

pub fn place_main_column(width: isize, height: isize, content: &str) -> String {
    if width <= 0 || height <= 0 {
        return String::new();
    }
    // Go calls lipgloss.Place(width, height, Left, Top, content)
    // (flexlayout.go:136); the Left/Top case is replicated verbatim below
    // (PORTING.md: lipgloss place helpers are reimplemented, padding cells
    // are UNSTYLED spaces).
    place_vertical_top(height, &place_horizontal_left(width, content))
}

/// Go `clamp` (config.go:322-329). The leet-data port keeps it private to
/// `leet_data::config`, so it is re-declared here for `expandedSidebarWidth`.
fn clamp(val: isize, minimum: isize, maximum: isize) -> isize {
    if val < minimum {
        return minimum;
    }
    if val > maximum {
        return maximum;
    }
    val
}

/// lipgloss v2 `getLines` (get.go:630-643): expands tabs to 4 spaces,
/// normalizes CRLF, splits on `\n`, and returns the widest line's display
/// width.
fn get_lines(s: &str) -> (Vec<String>, isize) {
    let s = s.replace('\t', "    ").replace("\r\n", "\n");
    let lines: Vec<String> = s.split('\n').map(str::to_string).collect();
    let widest = lines
        .iter()
        .map(|l| line_width(l) as isize)
        .max()
        .unwrap_or(0);
    (lines, widest)
}

/// lipgloss v2 `PlaceHorizontal(width, Left, str)` (position.go:43-86),
/// default whitespace (unstyled spaces).
///
/// PARITY: when the content is at least `width` wide, Go returns the ORIGINAL
/// string unmodified — tabs survive; otherwise the emitted lines are the
/// tab-expanded ones from getLines. No truncation ever happens.
fn place_horizontal_left(width: isize, s: &str) -> String {
    let (lines, content_width) = get_lines(s);
    let gap = width - content_width;

    if gap <= 0 {
        return s.to_string();
    }

    let mut b = String::new();
    for (i, l) in lines.iter().enumerate() {
        // Is this line shorter than the longest line?
        let short = (content_width - line_width(l) as isize).max(0);
        b.push_str(l);
        b.push_str(&" ".repeat((gap + short) as usize));
        if i < lines.len() - 1 {
            b.push('\n');
        }
    }

    b
}

/// lipgloss v2 `PlaceVertical(height, Top, str)` (position.go:90-134),
/// default whitespace: appends blank lines (spaces to the content's widest
/// line) until `height` lines total. Noop when content is already tall
/// enough.
fn place_vertical_top(height: isize, s: &str) -> String {
    let content_height = s.matches('\n').count() as isize + 1;
    let gap = height - content_height;

    if gap <= 0 {
        return s.to_string();
    }

    let (_, width) = get_lines(s);
    let empty_line = " ".repeat(width.max(0) as usize);
    let mut b = String::from(s);
    b.push('\n');
    for i in 0..gap {
        b.push_str(&empty_line);
        if i < gap - 1 {
            b.push('\n');
        }
    }

    b
}

// No Go test file exists for flexlayout.go; the cases below pin the Go
// behavior directly from the spec (flexlayout.go + vendored lipgloss v2
// position.go/get.go) per PARITY.md RUN-01/RUN-02.
#[cfg(test)]
mod tests {
    use super::*;

    fn spec(id: StackSectionId, visible: bool, height: isize, flex: bool) -> StackSectionSpec {
        StackSectionSpec {
            id,
            visible,
            height,
            flex,
        }
    }

    #[test]
    fn flex_section_consumes_remaining_height_after_fixed_and_gaps() {
        // metrics flex + media 10 + logs 8 in 40 rows: 2 gap lines,
        // remaining = 40 - 18 - 2 = 20.
        let layout = compute_vertical_stack_layout(
            40,
            &[
                spec(StackSectionId::Metrics, true, 0, true),
                spec(StackSectionId::Media, true, 10, false),
                spec(StackSectionId::ConsoleLogs, true, 8, false),
            ],
        );
        assert_eq!(layout.total_height, 40);
        assert_eq!(layout.visible_count, 3);
        assert_eq!(layout.y(StackSectionId::Metrics), 0);
        assert_eq!(layout.height(StackSectionId::Metrics), 20);
        assert_eq!(layout.y(StackSectionId::Media), 21);
        assert_eq!(layout.height(StackSectionId::Media), 10);
        assert_eq!(layout.y(StackSectionId::ConsoleLogs), 32);
        assert_eq!(layout.height(StackSectionId::ConsoleLogs), 8);
    }

    #[test]
    fn fixed_only_stack_keeps_heights_and_inserts_gaps() {
        let layout = compute_vertical_stack_layout(
            100,
            &[
                spec(StackSectionId::Media, true, 5, false),
                spec(StackSectionId::ConsoleLogs, true, 7, false),
            ],
        );
        assert_eq!(layout.visible_count, 2);
        assert_eq!(layout.y(StackSectionId::Media), 0);
        assert_eq!(layout.height(StackSectionId::Media), 5);
        assert_eq!(layout.y(StackSectionId::ConsoleLogs), 6);
        assert_eq!(layout.height(StackSectionId::ConsoleLogs), 7);
    }

    #[test]
    fn hidden_sections_are_skipped_and_default_to_zero() {
        let layout = compute_vertical_stack_layout(
            30,
            &[
                spec(StackSectionId::Metrics, true, 0, true),
                spec(StackSectionId::SystemMetrics, false, 12, false),
                spec(StackSectionId::Media, false, 9, false),
                spec(StackSectionId::ConsoleLogs, true, 6, false),
            ],
        );
        // 1 gap between the two visible panes: metrics = 30 - 6 - 1 = 23.
        assert_eq!(layout.visible_count, 2);
        assert_eq!(layout.height(StackSectionId::Metrics), 23);
        assert_eq!(layout.y(StackSectionId::ConsoleLogs), 24);
        // Hidden panes keep the zero layout.
        assert_eq!(layout.y(StackSectionId::SystemMetrics), 0);
        assert_eq!(layout.height(StackSectionId::SystemMetrics), 0);
        assert_eq!(layout.y(StackSectionId::Media), 0);
        assert_eq!(layout.height(StackSectionId::Media), 0);
    }

    #[test]
    fn no_visible_sections_returns_empty_layout() {
        let layout =
            compute_vertical_stack_layout(50, &[spec(StackSectionId::Media, false, 10, false)]);
        assert_eq!(layout.total_height, 50);
        assert_eq!(layout.visible_count, 0);
        for section in layout.sections {
            assert_eq!(section, StackSectionLayout::default());
        }
    }

    #[test]
    fn empty_specs_returns_empty_layout() {
        let layout = compute_vertical_stack_layout(50, &[]);
        assert_eq!(layout.visible_count, 0);
    }

    #[test]
    fn negative_total_height_clamps_to_zero() {
        let layout =
            compute_vertical_stack_layout(-5, &[spec(StackSectionId::Metrics, true, 0, true)]);
        assert_eq!(layout.total_height, 0);
        assert_eq!(layout.height(StackSectionId::Metrics), 0);
    }

    #[test]
    fn negative_spec_height_clamps_to_zero() {
        let layout = compute_vertical_stack_layout(
            10,
            &[
                spec(StackSectionId::Metrics, true, 0, true),
                spec(StackSectionId::Media, true, -4, false),
            ],
        );
        // media clamps to 0; metrics = 10 - 0 - 1 gap = 9.
        assert_eq!(layout.height(StackSectionId::Media), 0);
        assert_eq!(layout.height(StackSectionId::Metrics), 9);
        assert_eq!(layout.y(StackSectionId::Media), 10);
    }

    #[test]
    fn flex_height_floors_at_zero_when_fixed_overflows() {
        let layout = compute_vertical_stack_layout(
            10,
            &[
                spec(StackSectionId::Metrics, true, 0, true),
                spec(StackSectionId::Media, true, 20, false),
            ],
        );
        assert_eq!(layout.height(StackSectionId::Metrics), 0);
        // Fixed pane keeps its height even though it overflows.
        assert_eq!(layout.y(StackSectionId::Media), 1);
        assert_eq!(layout.height(StackSectionId::Media), 20);
    }

    #[test]
    fn single_visible_flex_section_takes_full_height_without_gaps() {
        let layout =
            compute_vertical_stack_layout(17, &[spec(StackSectionId::Metrics, true, 3, true)]);
        assert_eq!(layout.visible_count, 1);
        assert_eq!(layout.y(StackSectionId::Metrics), 0);
        assert_eq!(layout.height(StackSectionId::Metrics), 17);
    }

    #[test]
    fn last_flex_spec_wins_and_earlier_flex_keeps_input_height() {
        // PARITY quirk (flexlayout.go:56-60): two flex specs — only the last
        // gets the remaining height; the first keeps its clamped input height
        // and is NOT counted into fixedHeight, so the stack can overflow.
        let layout = compute_vertical_stack_layout(
            20,
            &[
                spec(StackSectionId::Metrics, true, 5, true),
                spec(StackSectionId::Media, true, 0, true),
            ],
        );
        // remaining = 20 - 0 fixed - 1 gap = 19.
        assert_eq!(layout.height(StackSectionId::Metrics), 5);
        assert_eq!(layout.y(StackSectionId::Media), 6);
        assert_eq!(layout.height(StackSectionId::Media), 19);
    }

    #[test]
    fn expanded_sidebar_width_uses_golden_ratio_truncated() {
        // 200 * 0.382 = 76.4 → 76 (Go int() truncation).
        assert_eq!(expanded_sidebar_width(200, false), 76);
        // 200 * 0.236 = 47.2 → 47.
        assert_eq!(expanded_sidebar_width(200, true), 47);
    }

    #[test]
    fn expanded_sidebar_width_clamps_to_min_and_max() {
        // 80 * 0.382 = 30.56 → 30 → clamped to SidebarMinWidth 40.
        assert_eq!(expanded_sidebar_width(80, false), 40);
        // 400 * 0.382 = 152.8 → 152 → clamped to SidebarMaxWidth 120.
        assert_eq!(expanded_sidebar_width(400, false), 120);
        // 300 * 0.236 = 70.8 → 70 within [40, 120].
        assert_eq!(expanded_sidebar_width(300, true), 70);
    }

    #[test]
    fn sidebar_content_width_subtracts_overhead_and_floors_at_zero() {
        // SidebarOverhead = 1 border + 2 padding = 3.
        assert_eq!(sidebar_content_width(40), 37);
        assert_eq!(sidebar_content_width(3), 0);
        assert_eq!(sidebar_content_width(0), 0);
    }

    #[test]
    fn sidebar_inner_width_subtracts_border_and_floors_at_zero() {
        // SidebarBorderCols = 1.
        assert_eq!(sidebar_inner_width(40), 39);
        assert_eq!(sidebar_inner_width(1), 0);
        assert_eq!(sidebar_inner_width(0), 0);
    }

    #[test]
    fn filter_non_empty_sections_drops_empties_preserving_order() {
        let got = filter_non_empty_sections(vec![
            String::new(),
            "a".to_string(),
            String::new(),
            "b".to_string(),
        ]);
        assert_eq!(got, vec!["a".to_string(), "b".to_string()]);
        assert_eq!(filter_non_empty_sections(vec![]), Vec::<String>::new());
    }

    #[test]
    fn place_main_column_returns_empty_for_non_positive_dims() {
        assert_eq!(place_main_column(0, 5, "x"), "");
        assert_eq!(place_main_column(5, 0, "x"), "");
        assert_eq!(place_main_column(-1, -1, "x"), "");
    }

    #[test]
    fn place_main_column_pads_left_top() {
        // Each line right-padded to width 5, then a blank 5-wide line
        // appended to reach height 3 (lipgloss Place(Left, Top)).
        assert_eq!(place_main_column(5, 3, "ab\ncdef"), "ab   \ncdef \n     ");
    }

    #[test]
    fn place_main_column_never_truncates_wide_content() {
        // PARITY: PlaceHorizontal is a noop when content ≥ width
        // (position.go:47-49); vertical padding still applies at the
        // content's own width.
        assert_eq!(place_main_column(2, 2, "abcd"), "abcd\n    ");
    }

    #[test]
    fn place_main_column_is_vertical_noop_when_content_tall_enough() {
        assert_eq!(place_main_column(5, 1, "a\nb"), "a    \nb    ");
    }

    #[test]
    fn place_main_column_tab_handling_matches_lipgloss() {
        // getLines (get.go:630-632) expands tabs to 4 spaces for measuring
        // AND for the emitted lines when padding happens…
        assert_eq!(place_main_column(8, 1, "a\tb"), "a    b  ");
        // …but the horizontal noop path returns the ORIGINAL string, tab
        // intact ("a\tb" measures 6 wide → gap = 0).
        assert_eq!(place_main_column(6, 1, "a\tb"), "a\tb");
    }

    #[test]
    fn place_main_column_measures_display_width() {
        // Wide rune: あ is 2 columns.
        assert_eq!(place_main_column(4, 1, "あ"), "あ  ");
        // ANSI escapes measure 0 (lipgloss padding is width-aware).
        assert_eq!(
            place_main_column(4, 1, "\u{1b}[31mab\u{1b}[0m"),
            "\u{1b}[31mab\u{1b}[0m  "
        );
    }

    #[test]
    fn place_main_column_blank_line_width_uses_widest_line() {
        // PlaceVertical pads with spaces to the widest line of the
        // horizontally-placed block (position.go:100-102).
        assert_eq!(place_main_column(3, 2, "abcd"), "abcd\n    ");
        assert_eq!(place_main_column(4, 2, "ab"), "ab  \n    ");
    }
}
