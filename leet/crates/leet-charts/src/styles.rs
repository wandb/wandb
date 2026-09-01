//! Port of `core/internal/leet/styles.go`: adaptive colors, the 14 chart
//! color palettes, layout/UI constants, terminal-background zebra-stripe
//! math, and tag color-contrast math.
//!
//! lipgloss.Style OBJECTS (borders/padding and the named `*Style` vars —
//! `headerStyle`, `borderStyle`/`focusedBorderStyle`, `titleStyle`,
//! `axisStyle`, `labelStyle`, `inspectionLineStyle`/`inspectionLegendStyle`,
//! `statusBarStyle`, `errorStyle`, `runOverviewTagStyle`, the run-overview /
//! left / right sidebar styles with `LeftBorder`/`RightBorder`, the console
//! logs pane styles, `helpKeyStyle` etc., `evenRunStyle`/`oddRunStyle`/
//! `selectedRunStyle`/`selectedRunInactiveStyle`, `symonContainerStyle`) and
//! the string helpers `renderHorizontalSeparator`/`joinWithSeparators` are
//! NOT ported here — they land with the leet-tui join helpers (Phase 4).
//! Only colors, constants, and math live in this module.
//! `inspectionLegendStyle`'s two colors exist ONLY inline in the Go style
//! var and are consumed by chart-internal render code in this crate, so
//! they ARE exported here ([`INSPECTION_LEGEND_FG`] /
//! [`INSPECTION_LEGEND_BG`]).

use std::time::Duration;

// ---------------------------------------------------------------------------
// Colors.
// ---------------------------------------------------------------------------

/// A 24-bit sRGB color.
///
/// Go represents colors as lipgloss hex strings ("#RRGGBB"); the port uses
/// this plain struct. Hex serialization/parsing round-trips exactly through
/// [`Rgb::to_hex`] / [`parse_hex_color`] (Go's `"#%02x%02x%02x"`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Rgb(pub u8, pub u8, pub u8);

impl Rgb {
    /// Serializes as lowercase "#rrggbb", byte-identical to Go's
    /// `fmt.Sprintf("#%02x%02x%02x", r, g, b)`.
    pub fn to_hex(self) -> String {
        const HEX_DIGITS: &[u8; 16] = b"0123456789abcdef";
        let Rgb(r, g, b) = self;
        let mut s = String::with_capacity(7);
        s.push('#');
        for byte in [r, g, b] {
            s.push(HEX_DIGITS[usize::from(byte >> 4)] as char);
            s.push(HEX_DIGITS[usize::from(byte & 0x0f)] as char);
        }
        s
    }
}

/// Value of a single hex digit, or None if `c` is not a hex digit.
const fn hex_digit_value(c: u8) -> Option<u8> {
    match c {
        b'0'..=b'9' => Some(c - b'0'),
        b'a'..=b'f' => Some(c - b'a' + 10),
        b'A'..=b'F' => Some(c - b'A' + 10),
        _ => None,
    }
}

/// Compile-time "#RRGGBB" parser. Keeps every palette hex literal
/// byte-verbatim with styles.go; a malformed literal fails the build.
const fn hex(s: &str) -> Rgb {
    const fn nib(c: u8) -> u8 {
        match hex_digit_value(c) {
            Some(v) => v,
            None => panic!("invalid hex digit in color literal"),
        }
    }
    let b = s.as_bytes();
    assert!(b.len() == 7, "color literal must be \"#RRGGBB\"");
    assert!(b[0] == b'#', "color literal must be \"#RRGGBB\"");
    Rgb(
        nib(b[1]) * 16 + nib(b[2]),
        nib(b[3]) * 16 + nib(b[4]),
        nib(b[5]) * 16 + nib(b[6]),
    )
}

/// AdaptiveColor picks between Light and Dark variants based on the
/// terminal background. (styles.go:36-44.)
///
/// Go resolves through the package-global `darkBackground atomic.Bool`
/// (styles.go:17-31; CONCURRENCY.md S13), defaulting to dark and updated on
/// `tea.BackgroundColorMsg`. The port keeps NO global: update/view run on a
/// single thread, so leet-tui owns the runtime flag and passes it into
/// [`AdaptiveColor::resolve`] explicitly. See [`default_dark_background`]
/// for the Go default / test-mode forcing.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct AdaptiveColor {
    pub light: Rgb,
    pub dark: Rgb,
}

impl AdaptiveColor {
    /// Resolves to the variant for the given background flag
    /// (Go `AdaptiveColor.RGBA` via `lipgloss.LightDark`).
    pub fn resolve(self, dark: bool) -> Rgb {
        if dark { self.dark } else { self.light }
    }
}

/// Const shorthand for an `AdaptiveColor` from two "#RRGGBB" literals.
const fn adaptive(light: &str, dark: &str) -> AdaptiveColor {
    AdaptiveColor {
        light: hex(light),
        dark: hex(dark),
    }
}

/// styles.go:199-202 (`uniformAdaptiveColor`).
const fn uniform_adaptive_color(h: &str) -> AdaptiveColor {
    let c = hex(h);
    AdaptiveColor { light: c, dark: c }
}

/// The initial value of Go's `darkBackground` flag: dark (styles.go:23).
/// Under the test harness the background is forced dark unless
/// `WANDB_LEET_TEST_BG=light` (testmode.go). At runtime leet-tui overwrites
/// this with the value from the background-color event
/// (Go `SetDarkBackground`, styles.go:28).
pub fn default_dark_background() -> bool {
    !(leet_data::test_mode::enabled() && leet_data::test_mode::forced_light_background())
}

// ---------------------------------------------------------------------------
// Terminal background detection (zebra-stripe math). styles.go:46-109.
// ---------------------------------------------------------------------------

/// Test-mode arm of Go `initTerminalBg` (styles.go:56-68): frozen values
/// under the harness, no terminal query; the Rust port uses the same
/// constants (see leet/docs/PARITY.md).
///
/// Returns None outside test mode — the runtime termenv/OSC-11 background
/// query is plumbed by leet-tui, which passes the detected color into
/// [`get_odd_run_style_color`]. (Go caches the query in `termBg*` package
/// globals under `termBgOnce`; the port keeps no global state — see
/// CONCURRENCY.md.)
pub fn test_mode_terminal_bg() -> Option<Rgb> {
    if !leet_data::test_mode::enabled() {
        return None;
    }
    if leet_data::test_mode::forced_light_background() {
        Some(Rgb(0xfa, 0xfa, 0xfa))
    } else {
        Some(Rgb(0x1e, 0x1e, 0x1e))
    }
}

/// blendRGB blends (r,g,b) toward (tr,tg,tb) by alpha (0.0–1.0).
/// (styles.go:87-95.)
///
/// Go serializes the result through `Sprintf("#%02x%02x%02x")` into a
/// lipgloss.Color; u8→hex→u8 round-trips exactly, so the port returns
/// [`Rgb`] directly.
pub fn blend_rgb(r: u8, g: u8, b: u8, tr: u8, tg: u8, tb: u8, alpha: f64) -> Rgb {
    let blend = |base: u8, target: u8| -> u8 {
        let v = f64::from(base) * (1.0 - alpha) + f64::from(target) * alpha;
        v as u8
    };
    Rgb(blend(r, tr), blend(g, tg), blend(b, tb))
}

/// getOddRunStyleColor returns a color 5% darker than the terminal
/// background. (styles.go:97-109.)
///
/// Go calls `initTerminalBg()` internally; the port takes the detected
/// terminal background as a parameter (`None` == not detected). Under the
/// harness pass [`test_mode_terminal_bg`]'s value.
pub fn get_odd_run_style_color(term_bg: Option<Rgb>) -> AdaptiveColor {
    if let Some(Rgb(r, g, b)) = term_bg {
        let c = blend_rgb(r, g, b, 128, 128, 128, 0.05);
        // A detected background yields one concrete color regardless of the
        // light/dark flag; represented as a uniform AdaptiveColor.
        return AdaptiveColor { light: c, dark: c };
    }

    AdaptiveColor {
        light: hex("#d0d0d0"),
        dark: hex("#1c1c1c"),
    }
}

// ---------------------------------------------------------------------------
// Immutable UI constants. styles.go:111-145.
// ---------------------------------------------------------------------------

pub const STATUS_BAR_HEIGHT: i64 = 1;
/// Horizontal padding for the status bar (left and right).
pub const STATUS_BAR_PADDING: i64 = 1;

/// ContentPadding is the number of blank columns on each side of every
/// content area (sidebars, main-column panes, status bar). This is the
/// single source of truth for horizontal content insets.
pub const CONTENT_PADDING: i64 = 1;

/// ContentPaddingCols is the total horizontal columns consumed by
/// ContentPadding (left + right).
pub const CONTENT_PADDING_COLS: i64 = 2 * CONTENT_PADDING;

/// SidebarBorderCols is the single terminal column occupied by a
/// sidebar's vertical border rule (│).
pub const SIDEBAR_BORDER_COLS: i64 = 1;

/// SidebarOverhead is the total non-content columns inside a sidebar:
/// one vertical border + ContentPadding on each side.
pub const SIDEBAR_OVERHEAD: i64 = SIDEBAR_BORDER_COLS + CONTENT_PADDING_COLS;

/// SidebarBottomPadding is the blank row at the bottom of a sidebar
/// that separates content from the status bar.
pub const SIDEBAR_BOTTOM_PADDING: i64 = 1;

pub const MIN_CHART_WIDTH: i64 = 20;
pub const MIN_CHART_HEIGHT: i64 = 5;
pub const MIN_METRIC_CHART_WIDTH: i64 = 18;
pub const MIN_METRIC_CHART_HEIGHT: i64 = 4;
pub const CHART_BORDER_SIZE: i64 = 2;
pub const CHART_TITLE_HEIGHT: i64 = 1;
pub const CHART_HEADER_HEIGHT: i64 = 1;

// Default grid sizes (styles.go:147-164) are hosted in `leet_data::config`
// (Go config.go's defaultConfig consumes them and leet-data cannot depend on
// leet-charts). Re-exported here so call sites stay greppable against
// styles.go.
pub use leet_data::config::{
    DEFAULT_METRICS_GRID_COLS, DEFAULT_METRICS_GRID_ROWS, DEFAULT_SYMON_GRID_COLS,
    DEFAULT_SYMON_GRID_ROWS, DEFAULT_SYSTEM_GRID_COLS, DEFAULT_SYSTEM_GRID_ROWS,
    DEFAULT_WORKSPACE_METRICS_GRID_COLS, DEFAULT_WORKSPACE_METRICS_GRID_ROWS,
    DEFAULT_WORKSPACE_SYSTEM_GRID_COLS, DEFAULT_WORKSPACE_SYSTEM_GRID_ROWS,
};

// Sidebar constants. styles.go:166-179.

/// We are using the golden ratio `phi` for visually pleasing layout
/// proportions: 1 - 1/phi.
pub const SIDEBAR_WIDTH_RATIO: f64 = 0.382;
/// When both sidebars visible: (1 - 1/phi) / phi ≈ 0.236.
pub const SIDEBAR_WIDTH_RATIO_BOTH: f64 = 0.236;
pub const SIDEBAR_MIN_WIDTH: i64 = 40;
pub const SIDEBAR_MAX_WIDTH: i64 = 120;

/// Key/value column width ratio: 40% of available width for keys.
pub const SIDEBAR_KEY_WIDTH_RATIO: f64 = 0.4;

/// Default grid height for system metrics when not calculated from terminal
/// height.
pub const DEFAULT_SYSTEM_METRICS_GRID_HEIGHT: i64 = 40;

// Rune constants for UI drawing. styles.go:181-197.

/// BoxLightVertical is U+2502 and is "taller" than the ASCII vertical bar
/// U+007C.
pub const BOX_LIGHT_VERTICAL: char = '\u{2502}'; // │

/// The em dash.
pub const UNICODE_EM_DASH: char = '\u{2014}';

/// The regular whitespace.
pub const UNICODE_SPACE: char = '\u{0020}';

/// A medium-shaded block.
pub const MEDIUM_SHADE_BLOCK: char = '\u{2592}'; // ▒

// ---------------------------------------------------------------------------
// WANDB brand colors. styles.go:204-215.
// ---------------------------------------------------------------------------

// Primary colors.
pub const MOON900: Rgb = hex("#171A1F");
pub const WANDB_COLOR: Rgb = hex("#FCBC32");

// Secondary colors.
pub const TEAL450: AdaptiveColor = adaptive("#10BFCC", "#E1F7FA");

// Functional colors not specific to any visual component. styles.go:217-272.

/// Color for main items such as chart titles.
pub const COLOR_ACCENT: AdaptiveColor = adaptive("#6c6c6c", "#bcbcbc");

/// Main text color that appears the most frequently on the screen.
pub const COLOR_TEXT: AdaptiveColor = adaptive(
    "#8a8a8a", // ANSI color 245
    "#8a8a8a",
);

/// Color for extra or parenthetical text or information.
/// Axis lines in charts.
pub const COLOR_SUBTLE: AdaptiveColor = adaptive(
    "#585858", // ANSI color 240
    "#585858",
);

/// Color for layout elements, like borders and separator lines.
pub const COLOR_LAYOUT: AdaptiveColor = adaptive("#949494", "#444444");

pub const COLOR_DARK: Rgb = hex("#171717");

/// Color for layout elements when they're highlighted or focused.
pub const COLOR_LAYOUT_HIGHLIGHT: AdaptiveColor = TEAL450;

/// Color for top-level headings; least frequent.
/// Leet logo, help page section headings.
pub const COLOR_HEADING: Rgb = WANDB_COLOR;

/// Color for lower-level headings; more frequent than headings.
/// Help page keys, metrics grid header.
pub const COLOR_SUBHEADING: AdaptiveColor = adaptive("#3a3a3a", "#eeeeee");

/// Colors for key-value pairs such as run summary or config items.
// PARITY: Go colorItemKey is lipgloss.Color("243") — an xterm-256 palette
// INDEX, not a hex color. #767676 is that index on the standard grayscale
// ramp (8 + (243-232)*10 = 118), consistent with the hex equivalents Go
// itself notes for colorText (245 = #8a8a8a) and colorSubtle (240 =
// #585858). If cell-level parity requires the indexed SGR form (38;5;243),
// leet-tui must special-case this constant when emitting.
pub const COLOR_ITEM_KEY: Rgb = hex("#767676");
pub const COLOR_ITEM_VALUE: AdaptiveColor = adaptive("#262626", "#d0d0d0");

/// Color used for the selected line in lists.
pub const COLOR_SELECTED: AdaptiveColor = adaptive("#FCBC32", "#FCBC32");

// Workspace view mode colors (the even/odd/selected run *style objects*
// land with leet-tui). styles.go:798-811.

pub const WORKSPACE_HEADER_LINES: i64 = 1;

pub const COLOR_SELECTED_RUN_INACTIVE_STYLE: AdaptiveColor = adaptive("#F5D28A", "#6B5200");

// ---------------------------------------------------------------------------
// ASCII art for the loading screen and the help page. styles.go:274-289.
// ---------------------------------------------------------------------------

pub const WANDB_ART: &str = "
██     ██  █████  ███    ██ ██████  ██████
██     ██ ██   ██ ████   ██ ██   ██ ██   ██
██  █  ██ ███████ ██ ██  ██ ██   ██ ██████
██ ███ ██ ██   ██ ██  ██ ██ ██   ██ ██   ██
 ███ ███  ██   ██ ██   ████ ██████  ██████
";

pub const LEET_ART: &str = "
██      ███████ ███████ ████████
██      ██      ██         ██
██      █████   █████      ██
██      ██      ██         ██
███████ ███████ ███████    ██
";

// ---------------------------------------------------------------------------
// Color schemes. styles.go:291-522.
// ---------------------------------------------------------------------------

/// Color schemes for displaying data (metrics and system metrics) on the
/// charts.
///
/// Each scheme consists of an ordered list of colors,
/// where each new graph, and/or a line on a multi-line graph takes the next
/// color. Colors get reused in a cyclic manner.
///
/// PARITY: Go stores these in a map (`colorSchemes`, styles.go:296) whose
/// iteration order is random; entry order here follows the Go source
/// declaration and must stay in sync with
/// `leet_data::config::COLOR_SCHEME_NAMES` (asserted in tests).
pub static COLOR_SCHEMES: &[(&str, &[AdaptiveColor])] = &[
    (
        "sunset-glow", // Golden-pink gradient
        &[
            adaptive("#B84FD4", "#E281FE"),
            adaptive("#BD5AB9", "#E78DE3"),
            adaptive("#BF60AB", "#E993D5"),
            adaptive("#C36C91", "#ED9FBB"),
            adaptive("#C67283", "#F0A5AD"),
            adaptive("#C87875", "#F2AB9F"),
            adaptive("#CC8451", "#F6B784"),
            adaptive("#CE8A45", "#F8BD78"),
            adaptive("#D19038", "#FBC36B"),
            adaptive("#D59C1C", "#FFCF4F"),
        ],
    ),
    (
        "blush-tide", // Pink-teal gradient
        &[
            adaptive("#D94F8C", "#F9A7CC"),
            adaptive("#CA60AC", "#EEB3E0"),
            adaptive("#B96FC4", "#E4BFEE"),
            adaptive("#A77DD4", "#DBC9F7"),
            adaptive("#9489DF", "#D5D3FC"),
            adaptive("#8095E5", "#D1DCFE"),
            adaptive("#6AA1E6", "#D0E5FF"),
            adaptive("#50ACE2", "#D3ECFE"),
            adaptive("#33B6D9", "#D8F2FC"),
            adaptive("#10BFCC", "#E1F7FA"), // == teal450
        ],
    ),
    (
        "gilded-lagoon", // Golden-teal gradient
        &[
            adaptive("#D59C1C", "#FFCF4F"),
            adaptive("#C2A636", "#EADB74"),
            adaptive("#AFAD4C", "#DAE492"),
            adaptive("#9CB35F", "#CFEBAB"),
            adaptive("#8AB872", "#C8EFC0"),
            adaptive("#77BB83", "#C5F3D2"),
            adaptive("#62BE95", "#C7F5E1"),
            adaptive("#4CBFA6", "#CDF6ED"),
            adaptive("#32C0B9", "#D5F7F5"),
            adaptive("#10BFCC", "#E1F7FA"), // == teal450
        ],
    ),
    (
        "bootstrap-vibe", // Badge-friendly palette with familiar utility tones
        &[
            adaptive("#6c757d", "#a7b0b8"),
            adaptive("#0d6efd", "#78aefc"),
            adaptive("#198754", "#72cf9d"),
            adaptive("#0dcaf0", "#7be3fa"),
            adaptive("#fd7e14", "#ffb574"),
            adaptive("#dc3545", "#f28a93"),
            adaptive("#6f42c1", "#b99aff"),
            adaptive("#20c997", "#83e6ca"),
        ],
    ),
    (
        "wandb-vibe-10",
        &[
            adaptive("#8A8D91", "#B1B4B9"),
            adaptive("#3DBAC4", "#58D3DB"),
            adaptive("#42B88A", "#5ED6A4"),
            adaptive("#E07040", "#FCA36F"),
            adaptive("#E85565", "#FF7A88"),
            adaptive("#5A96E0", "#7DB1FA"),
            adaptive("#9AC24A", "#BBE06B"),
            adaptive("#E0AD20", "#FFCF4D"),
            adaptive("#C85EE8", "#E180FF"),
            adaptive("#9475E8", "#B199FF"),
        ],
    ),
    (
        "wandb-vibe-20",
        &[
            adaptive("#AEAFB3", "#D4D5D9"),
            adaptive("#454B54", "#565C66"),
            adaptive("#7AD4DB", "#A9EDF2"),
            adaptive("#04707F", "#038194"),
            adaptive("#6DDBA8", "#A1F0CB"),
            adaptive("#00704A", "#00875A"),
            adaptive("#EAB08A", "#FFCFB2"),
            adaptive("#A84728", "#C2562F"),
            adaptive("#EAA0A5", "#FFC7CA"),
            adaptive("#B82038", "#CC2944"),
            adaptive("#8FBDE8", "#BDD9FF"),
            adaptive("#2850A8", "#1F59C4"),
            adaptive("#B0D470", "#D0ED9D"),
            adaptive("#4E7424", "#5F8A2D"),
            adaptive("#EAC860", "#FFE49E"),
            adaptive("#9A5E10", "#B8740F"),
            adaptive("#D99DE8", "#EFC2FC"),
            adaptive("#8528A8", "#9E36C2"),
            adaptive("#B8A8E8", "#D6C9FF"),
            adaptive("#5538B0", "#6645D1"),
        ],
    ),
    // This palette has been tested with deuteranopia, protanopia, and
    // tritanopia simulators. Those forms of color blindness are less common
    // than deuteranomaly. This palette focuses on siennas/blues/grays only,
    // which are commonly colorblind-friendly across most forms of color
    // blindness. Gradient ordering: warm siennas → cool blues → neutral
    // grays.
    (
        "dusk-shore",
        &[
            adaptive("#823520", "#994228"),
            adaptive("#A84728", "#C2562F"),
            adaptive("#BA5028", "#D96534"),
            adaptive("#D86030", "#FC8F58"),
            adaptive("#E07040", "#FCA36F"),
            adaptive("#E89865", "#FFBA91"),
            adaptive("#EAB08A", "#FFCFB2"),
            adaptive("#78A8E8", "#A4C9FC"),
            adaptive("#5A96E0", "#7DB1FA"),
            adaptive("#4880DA", "#629DF5"),
            adaptive("#2E68CC", "#397EED"),
            adaptive("#2258BE", "#286CE0"),
            adaptive("#2850A8", "#1F59C4"),
            adaptive("#8A8D91", "#B1B4B9"),
            adaptive("#606872", "#79808A"),
            adaptive("#454B54", "#565C66"),
        ],
    ),
    // Same colorblind-friendly sienna/blue/gray palette as "dusk-shore", but
    // with colors interleaved for maximum visual differentiation between
    // adjacent series.
    (
        "clear-signal",
        &[
            adaptive("#BA5028", "#D96534"),
            adaptive("#2258BE", "#286CE0"),
            adaptive("#4880DA", "#629DF5"),
            adaptive("#823520", "#994228"),
            adaptive("#E07040", "#FCA36F"),
            adaptive("#EAB08A", "#FFCFB2"),
            adaptive("#8A8D91", "#B1B4B9"),
            adaptive("#606872", "#79808A"),
            adaptive("#5A96E0", "#7DB1FA"),
            adaptive("#2850A8", "#1F59C4"),
            adaptive("#A84728", "#C2562F"),
            adaptive("#D86030", "#FC8F58"),
            adaptive("#E89865", "#FFBA91"),
            adaptive("#78A8E8", "#A4C9FC"),
            adaptive("#2E68CC", "#397EED"),
            adaptive("#454B54", "#565C66"),
        ],
    ),
    // Sequential palettes suitable for French Fries percentage heatmaps.
    (
        "traffic-light",
        &[
            uniform_adaptive_color("#1A9850"),
            uniform_adaptive_color("#3EAE51"),
            uniform_adaptive_color("#67C35C"),
            uniform_adaptive_color("#97D168"),
            uniform_adaptive_color("#C8DE72"),
            uniform_adaptive_color("#F1DD6B"),
            uniform_adaptive_color("#FDB863"),
            uniform_adaptive_color("#F89C5A"),
            uniform_adaptive_color("#F67C4B"),
            uniform_adaptive_color("#E85D4F"),
            uniform_adaptive_color("#D73027"),
        ],
    ),
    (
        "viridis",
        &[
            uniform_adaptive_color("#440154"),
            uniform_adaptive_color("#482475"),
            uniform_adaptive_color("#414487"),
            uniform_adaptive_color("#355F8D"),
            uniform_adaptive_color("#2A788E"),
            uniform_adaptive_color("#21918C"),
            uniform_adaptive_color("#22A884"),
            uniform_adaptive_color("#44BF70"),
            uniform_adaptive_color("#7AD151"),
            uniform_adaptive_color("#BDDF26"),
            uniform_adaptive_color("#FDE725"),
        ],
    ),
    (
        "plasma",
        &[
            uniform_adaptive_color("#0D0887"),
            uniform_adaptive_color("#41049D"),
            uniform_adaptive_color("#6A00A8"),
            uniform_adaptive_color("#8F0DA4"),
            uniform_adaptive_color("#B12A90"),
            uniform_adaptive_color("#CC4778"),
            uniform_adaptive_color("#E16462"),
            uniform_adaptive_color("#F2844B"),
            uniform_adaptive_color("#FCA636"),
            uniform_adaptive_color("#FCCE25"),
            uniform_adaptive_color("#F0F921"),
        ],
    ),
    (
        "inferno",
        &[
            uniform_adaptive_color("#000004"),
            uniform_adaptive_color("#160B39"),
            uniform_adaptive_color("#420A68"),
            uniform_adaptive_color("#6A176E"),
            uniform_adaptive_color("#932667"),
            uniform_adaptive_color("#BC3754"),
            uniform_adaptive_color("#DD513A"),
            uniform_adaptive_color("#F37819"),
            uniform_adaptive_color("#FCA50A"),
            uniform_adaptive_color("#F6D746"),
            uniform_adaptive_color("#FCFFA4"),
        ],
    ),
    (
        "magma",
        &[
            uniform_adaptive_color("#000004"),
            uniform_adaptive_color("#140E36"),
            uniform_adaptive_color("#3B0F70"),
            uniform_adaptive_color("#641A80"),
            uniform_adaptive_color("#8C2981"),
            uniform_adaptive_color("#B73779"),
            uniform_adaptive_color("#DE4968"),
            uniform_adaptive_color("#F7705C"),
            uniform_adaptive_color("#FE9F6D"),
            uniform_adaptive_color("#FECF92"),
            uniform_adaptive_color("#FCFDBF"),
        ],
    ),
    (
        "cividis",
        &[
            uniform_adaptive_color("#00224E"),
            uniform_adaptive_color("#083370"),
            uniform_adaptive_color("#35456C"),
            uniform_adaptive_color("#4F576C"),
            uniform_adaptive_color("#666970"),
            uniform_adaptive_color("#7D7C78"),
            uniform_adaptive_color("#948E77"),
            uniform_adaptive_color("#AEA371"),
            uniform_adaptive_color("#C8B866"),
            uniform_adaptive_color("#E5CF52"),
            uniform_adaptive_color("#FEE838"),
        ],
    ),
];

/// Looks up a palette by name (Go `colorSchemes[scheme]` map access).
pub fn color_scheme(name: &str) -> Option<&'static [AdaptiveColor]> {
    COLOR_SCHEMES
        .iter()
        .find(|(n, _)| *n == name)
        .map(|&(_, colors)| colors)
}

/// styles.go:503-508 (`colorSchemeOrDefault`).
fn color_scheme_or_default(scheme: &str, fallback: &str) -> &'static [AdaptiveColor] {
    if let Some(colors) = color_scheme(scheme)
        && !colors.is_empty()
    {
        return colors;
    }
    // PARITY: Go returns the nil map value for an unknown fallback; the port
    // returns an empty slice (both mean "no palette").
    color_scheme(fallback).unwrap_or(&[])
}

/// GraphColors returns the palette for the requested scheme.
///
/// If the scheme is unknown, it falls back to DefaultColorScheme.
pub fn graph_colors(scheme: &str) -> &'static [AdaptiveColor] {
    color_scheme_or_default(scheme, leet_data::config::DEFAULT_COLOR_SCHEME)
}

/// FrenchFriesColors returns the palette for the requested French Fries
/// heatmap scheme.
///
/// If the scheme is unknown, it falls back to DefaultFrenchFriesColorScheme.
pub fn french_fries_colors(scheme: &str) -> &'static [AdaptiveColor] {
    color_scheme_or_default(scheme, leet_data::config::DEFAULT_FRENCH_FRIES_COLOR_SCHEME)
}

// ---------------------------------------------------------------------------
// Chart inspection legend colors. styles.go:558-566.
// ---------------------------------------------------------------------------

// Go declares these inline inside the `inspectionLegendStyle` lipgloss var
// (the style OBJECT itself is not ported — see the module doc). The colors
// are exported here because their consumers are chart-internal render code
// in this crate: `epoch_line_chart::draw_inspection_overlay` legend cells
// (epochlinechart.go:795,849,856) and the french-fries inspection legend
// (frenchfrieschart.go:419).

/// Foreground of `inspectionLegendStyle` (styles.go:559-562).
pub const INSPECTION_LEGEND_FG: AdaptiveColor = adaptive("#111111", "#EEEEEE");

/// Background of `inspectionLegendStyle` (styles.go:563-566).
pub const INSPECTION_LEGEND_BG: AdaptiveColor = adaptive("#EEEEEE", "#333333");

// ---------------------------------------------------------------------------
// Tag color-contrast math. styles.go:579-654.
// ---------------------------------------------------------------------------

/// colorIndex returns a deterministic palette index for the given name:
/// FNV-1a (32-bit) of the name, mod the palette length.
///
/// DIVERGENCE(hosting): Go defines colorIndex in epochlinechart.go:51; it is
/// hosted here because `run_overview_tag_background_color` needs it and the
/// epoch_line_chart module ports separately. `epoch_line_chart` and
/// `workspace_run_colors` must reuse this fn, not re-port it.
pub fn color_index(name: &str, palette_len: usize) -> usize {
    if palette_len == 0 {
        return 0;
    }

    // Go hash/fnv New32a: offset basis 2166136261, prime 16777619.
    let mut sum: u32 = 2_166_136_261;
    for &byte in name.as_bytes() {
        sum ^= u32::from(byte);
        sum = sum.wrapping_mul(16_777_619);
    }

    (sum % palette_len as u32) as usize
}

/// runOverviewTagLightText is the default (white) foreground for tag badges
/// when the background is too dark for dark text to be legible.
pub const RUN_OVERVIEW_TAG_LIGHT_TEXT: Rgb = hex("#ffffff");

/// runOverviewTagBackgroundColor returns the background color for a tag
/// badge. It deterministically maps tag to a color in the given scheme so
/// that the same tag always gets the same color.
pub fn run_overview_tag_background_color(scheme: &str, tag: &str) -> AdaptiveColor {
    let colors = graph_colors(scheme);
    colors[color_index(tag, colors.len())]
}

/// runOverviewTagForegroundColor picks a foreground color (light or dark)
/// for each adaptive variant of bg that satisfies WCAG contrast
/// requirements.
pub fn run_overview_tag_foreground_color(bg: AdaptiveColor) -> AdaptiveColor {
    AdaptiveColor {
        light: run_overview_tag_text_color(bg.light),
        dark: run_overview_tag_text_color(bg.dark),
    }
}

/// runOverviewTagTextColor returns white or dark text for a single
/// background color, choosing whichever yields the higher WCAG contrast
/// ratio — that is the INTENT of the Go code, but not its behavior:
///
// PARITY (Go bug, reproduced): Go stringifies the background with
// fmt.Sprint and re-parses via parseHexColor. Under lipgloss v1 colors
// were strings and this worked; lipgloss v2's Color() returns a parsed
// color.Color struct, so fmt.Sprint yields "{177 153 255 255}"-style
// output, the Sscanf parse ALWAYS fails, and the function ALWAYS returns
// runOverviewTagLightText (white). The WCAG branch below is dead code in
// Go today — verified by the frame differential (oracle renders white on
// every badge, e.g. #B199FF where contrast math would pick dark). Keep
// calling the (ported, tested) contrast machinery the day Go fixes this;
// until then, mirror the bug.
pub fn run_overview_tag_text_color(bg: Rgb) -> Rgb {
    let Rgb(r, g, b) = bg;

    let _light_contrast = contrast_ratio_rgb(r, g, b, 0xff, 0xff, 0xff);
    let _dark_contrast = contrast_ratio_rgb(r, g, b, 0x17, 0x17, 0x17);

    RUN_OVERVIEW_TAG_LIGHT_TEXT
}

/// parseHexColor extracts 8-bit RGB components from a "#RRGGBB" hex string.
/// It returns None if hex is not in the expected format.
///
/// PARITY: Go scans with `fmt.Sscanf(hex, "#%02x%02x%02x", ...)`, which
/// reads one-or-two hex digits per component (so "#abcde" parses as
/// ab/cd/0e), ignores trailing input ("#aabbccdd" parses as aa/bb/cc), and
/// skips spaces/tabs before each verb. All three quirks are preserved.
pub fn parse_hex_color(hex: &str) -> Option<Rgb> {
    let rest = hex.strip_prefix('#')?;
    let mut bytes = rest.bytes().peekable();

    let mut component = || -> Option<u8> {
        while matches!(bytes.peek(), Some(&b' ') | Some(&b'\t')) {
            bytes.next();
        }
        let hi = hex_digit_value(bytes.next()?)?;
        // The second digit is optional: %02x caps the width at two.
        match bytes.peek().copied().and_then(hex_digit_value) {
            Some(lo) => {
                bytes.next();
                Some(hi * 16 + lo)
            }
            None => Some(hi),
        }
    };

    let r = component()?;
    let g = component()?;
    let b = component()?;
    Some(Rgb(r, g, b))
}

/// contrastRatioRGB computes the WCAG 2.x contrast ratio between two RGB
/// colors. The returned value ranges from 1 (identical) to 21 (black vs
/// white).
pub fn contrast_ratio_rgb(r1: u8, g1: u8, b1: u8, r2: u8, g2: u8, b2: u8) -> f64 {
    let mut l1 = relative_luminance(r1, g1, b1);
    let mut l2 = relative_luminance(r2, g2, b2);
    if l1 < l2 {
        std::mem::swap(&mut l1, &mut l2);
    }
    (l1 + 0.05) / (l2 + 0.05)
}

/// relativeLuminance returns the WCAG relative luminance of an sRGB color.
/// See <https://www.w3.org/TR/WCAG21/#dfn-relative-luminance>.
///
/// Note: WCAG = Web Content Accessibility Guidelines.
pub fn relative_luminance(r: u8, g: u8, b: u8) -> f64 {
    // FMA rule: keep Go's term-by-term arithmetic shape.
    let lr = 0.2126 * srgb_to_linear(r);
    let lg = 0.7152 * srgb_to_linear(g);
    let lb = 0.0722 * srgb_to_linear(b);
    lr + lg + lb
}

/// srgbToLinear converts a single 8-bit sRGB channel value to linear-light
/// using the IEC 61966-2-1 transfer function.
pub fn srgb_to_linear(c: u8) -> f64 {
    let v = f64::from(c) / 255.0;
    if v <= 0.04045 {
        return v / 12.92;
    }
    // PARITY: Go math.Pow vs f64::powf may differ in the last ulp; the
    // contrast gaps between the palette colors and the two candidate
    // foregrounds are orders of magnitude larger.
    ((v + 0.055) / 1.055).powf(2.4)
}

// ---------------------------------------------------------------------------
// Animation constants. styles.go:778-785.
// ---------------------------------------------------------------------------

/// The duration for sidebar animations.
pub const ANIMATION_DURATION: Duration = Duration::from_millis(150);

/// The number of steps in sidebar animations.
pub const ANIMATION_STEPS: u32 = 10;

/// The tick interval used for sidebar animations
/// (ANIMATION_DURATION / ANIMATION_STEPS).
pub const ANIMATION_FRAME: Duration = Duration::from_millis(15);

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;
    use proptest::prelude::*;

    /// The palette registry must match the name list leet-data duplicates
    /// for config validation (declaration order preserved), and hold all 14
    /// schemes.
    #[test]
    fn scheme_names_match_config_registry() {
        let names: Vec<&str> = COLOR_SCHEMES.iter().map(|&(n, _)| n).collect();
        assert_eq!(names, leet_data::config::COLOR_SCHEME_NAMES.to_vec());
        assert_eq!(COLOR_SCHEMES.len(), 14);
    }

    #[test]
    fn palette_lengths() {
        let want: &[(&str, usize)] = &[
            ("sunset-glow", 10),
            ("blush-tide", 10),
            ("gilded-lagoon", 10),
            ("bootstrap-vibe", 8),
            ("wandb-vibe-10", 10),
            ("wandb-vibe-20", 20),
            ("dusk-shore", 16),
            ("clear-signal", 16),
            ("traffic-light", 11),
            ("viridis", 11),
            ("plasma", 11),
            ("inferno", 11),
            ("magma", 11),
            ("cividis", 11),
        ];
        for &(name, len) in want {
            assert_eq!(color_scheme(name).unwrap().len(), len, "{name}");
        }
    }

    #[test]
    fn palette_hex_spot_checks() {
        // First/last entries of representative palettes, verbatim from Go.
        let sunset = color_scheme("sunset-glow").unwrap();
        assert_eq!(sunset[0].light.to_hex(), "#b84fd4");
        assert_eq!(sunset[0].dark.to_hex(), "#e281fe");
        assert_eq!(sunset[9].light.to_hex(), "#d59c1c");
        assert_eq!(sunset[9].dark.to_hex(), "#ffcf4f");

        // blush-tide and gilded-lagoon both end in teal450.
        let blush = color_scheme("blush-tide").unwrap();
        let gilded = color_scheme("gilded-lagoon").unwrap();
        assert_eq!(blush[9], TEAL450);
        assert_eq!(gilded[9], TEAL450);

        let wv20 = color_scheme("wandb-vibe-20").unwrap();
        assert_eq!(wv20[0], adaptive("#AEAFB3", "#D4D5D9"));
        assert_eq!(wv20[19], adaptive("#5538B0", "#6645D1"));

        let viridis = color_scheme("viridis").unwrap();
        assert_eq!(viridis[0].light, Rgb(0x44, 0x01, 0x54));
        assert_eq!(viridis[10].light, Rgb(0xFD, 0xE7, 0x25));

        let cividis = color_scheme("cividis").unwrap();
        assert_eq!(cividis[0].light, Rgb(0x00, 0x22, 0x4E));
        assert_eq!(cividis[10].light, Rgb(0xFE, 0xE8, 0x38));
    }

    #[test]
    fn sequential_palettes_are_uniform() {
        for name in [
            "traffic-light",
            "viridis",
            "plasma",
            "inferno",
            "magma",
            "cividis",
        ] {
            for c in color_scheme(name).unwrap() {
                assert_eq!(c.light, c.dark, "{name}");
            }
        }
    }

    #[test]
    fn graph_colors_known_scheme() {
        assert_eq!(
            graph_colors("dusk-shore"),
            color_scheme("dusk-shore").unwrap()
        );
    }

    #[test]
    fn graph_colors_falls_back_to_default_scheme() {
        assert_eq!(
            graph_colors("no-such-scheme"),
            color_scheme(leet_data::config::DEFAULT_COLOR_SCHEME).unwrap()
        );
    }

    #[test]
    fn french_fries_colors_falls_back_to_viridis() {
        assert_eq!(
            french_fries_colors("no-such-scheme"),
            color_scheme("viridis").unwrap()
        );
        assert_eq!(
            french_fries_colors("plasma"),
            color_scheme("plasma").unwrap()
        );
    }

    #[test]
    fn adaptive_color_resolve() {
        assert_eq!(TEAL450.resolve(false), Rgb(0x10, 0xBF, 0xCC));
        assert_eq!(TEAL450.resolve(true), Rgb(0xE1, 0xF7, 0xFA));
        assert_eq!(COLOR_LAYOUT_HIGHLIGHT, TEAL450);
        assert_eq!(COLOR_HEADING, WANDB_COLOR);
    }

    /// Expected values from a Go probe of
    /// `fmt.Sscanf(s, "#%02x%02x%02x", ...)` (see PARITY comment on
    /// parse_hex_color).
    #[test]
    fn parse_hex_color_go_sscanf_semantics() {
        // Well-formed, lower and upper case.
        assert_eq!(parse_hex_color("#d0d0d0"), Some(Rgb(0xd0, 0xd0, 0xd0)));
        assert_eq!(parse_hex_color("#FCBC32"), Some(Rgb(0xfc, 0xbc, 0x32)));
        // Sscanf quirk: one-digit final component.
        assert_eq!(parse_hex_color("#abcde"), Some(Rgb(171, 205, 14)));
        // Sscanf quirk: trailing input ignored.
        assert_eq!(parse_hex_color("#aabbccdd"), Some(Rgb(170, 187, 204)));
        // Errors (Go returns ok=false).
        assert_eq!(parse_hex_color("#fff"), None);
        assert_eq!(parse_hex_color("243"), None); // ANSI-indexed colorItemKey form
        assert_eq!(parse_hex_color(""), None);
        assert_eq!(parse_hex_color("#"), None);
        assert_eq!(parse_hex_color("#GGGGGG"), None);
        assert_eq!(parse_hex_color("not-a-color"), None);
    }

    #[test]
    fn to_hex_matches_go_sprintf() {
        assert_eq!(Rgb(0xFC, 0xBC, 0x32).to_hex(), "#fcbc32");
        assert_eq!(Rgb(0, 0, 0).to_hex(), "#000000");
        assert_eq!(Rgb(255, 255, 255).to_hex(), "#ffffff");
        assert_eq!(Rgb(0x0a, 0x00, 0x04).to_hex(), "#0a0004");
    }

    #[test]
    fn hex_round_trip_all_palette_colors() {
        for &(name, colors) in COLOR_SCHEMES {
            for c in colors {
                for rgb in [c.light, c.dark] {
                    assert_eq!(parse_hex_color(&rgb.to_hex()), Some(rgb), "{name}");
                }
            }
        }
    }

    proptest! {
        #[test]
        fn hex_round_trip(r: u8, g: u8, b: u8) {
            let rgb = Rgb(r, g, b);
            let hex = rgb.to_hex();
            prop_assert_eq!(hex.len(), 7);
            prop_assert_eq!(parse_hex_color(&hex), Some(rgb));
        }
    }

    #[test]
    fn blend_rgb_matches_go() {
        // Dark test-mode background #1e1e1e toward gray 128 at alpha 0.05:
        // 30*0.95 + 128*0.05 = 34.9 -> 34.
        assert_eq!(
            blend_rgb(0x1e, 0x1e, 0x1e, 128, 128, 128, 0.05),
            Rgb(34, 34, 34)
        );
        // Light test-mode background #fafafa: 250*0.95 + 128*0.05 = 243.9 -> 243.
        assert_eq!(
            blend_rgb(0xfa, 0xfa, 0xfa, 128, 128, 128, 0.05),
            Rgb(243, 243, 243)
        );
        // Alpha extremes.
        assert_eq!(blend_rgb(10, 20, 30, 200, 210, 220, 0.0), Rgb(10, 20, 30));
        assert_eq!(
            blend_rgb(10, 20, 30, 200, 210, 220, 1.0),
            Rgb(200, 210, 220)
        );
    }

    #[test]
    fn odd_run_style_color() {
        // Detected background: uniform blended color.
        assert_eq!(
            get_odd_run_style_color(Some(Rgb(0x1e, 0x1e, 0x1e))),
            AdaptiveColor {
                light: Rgb(34, 34, 34),
                dark: Rgb(34, 34, 34),
            }
        );
        // Not detected: adaptive fallback (styles.go:105-108).
        assert_eq!(
            get_odd_run_style_color(None),
            AdaptiveColor {
                light: Rgb(0xd0, 0xd0, 0xd0),
                dark: Rgb(0x1c, 0x1c, 0x1c),
            }
        );
    }

    /// Expected indices from a Go probe of colorIndex
    /// (epochlinechart.go:51).
    #[test]
    fn color_index_matches_go_fnv1a() {
        let cases: &[(&str, usize, usize)] = &[
            // (name, index mod 10, index mod 8)
            ("baseline", 2, 2),
            ("ablation", 9, 3),
            ("prod", 4, 4),
            ("smoke-test", 7, 1),
            ("", 1, 5),
        ];
        for &(name, want10, want8) in cases {
            assert_eq!(color_index(name, 10), want10, "{name:?} mod 10");
            assert_eq!(color_index(name, 8), want8, "{name:?} mod 8");
        }
    }

    #[test]
    fn color_index_empty_palette_is_zero() {
        assert_eq!(color_index("anything", 0), 0);
    }

    #[test]
    fn contrast_ratio_extremes() {
        assert_eq!(contrast_ratio_rgb(0, 0, 0, 255, 255, 255), 21.0);
        assert_eq!(contrast_ratio_rgb(255, 255, 255, 0, 0, 0), 21.0);
        assert_eq!(contrast_ratio_rgb(0x17, 0x17, 0x17, 0x17, 0x17, 0x17), 1.0);
    }

    #[test]
    fn relative_luminance_extremes() {
        assert_eq!(relative_luminance(255, 255, 255), 1.0);
        assert_eq!(relative_luminance(0, 0, 0), 0.0);
        assert_eq!(srgb_to_linear(0), 0.0);
    }

    /// Contrast ratios cross-checked against a Go probe of
    /// contrastRatioRGB (printed with %.17g).
    // The literals are the Go probe's %.17g output verbatim; %.17g emits
    // more digits than the shortest f64 representation.
    #[allow(clippy::excessive_precision)]
    #[test]
    fn contrast_ratio_matches_go() {
        let cases: &[(Rgb, f64, f64)] = &[
            // (bg, contrast vs white, contrast vs #171717)
            (
                Rgb(0xFF, 0xCF, 0x4F),
                1.469_555_833_255_873_8,
                12.199_495_825_420_652,
            ),
            (
                Rgb(0x0D, 0x08, 0x87),
                14.981_805_267_570_538,
                1.196_640_854_212_277_1,
            ),
            (
                Rgb(0xB8, 0x4F, 0xD4),
                4.111_877_903_690_182_9,
                4.360_012_790_491_263_8,
            ),
            (
                Rgb(0x45, 0x4B, 0x54),
                8.795_843_717_155_46,
                2.038_217_234_130_825_8,
            ),
        ];
        for &(Rgb(r, g, b), want_light, want_dark) in cases {
            let light = contrast_ratio_rgb(r, g, b, 0xff, 0xff, 0xff);
            let dark = contrast_ratio_rgb(r, g, b, 0x17, 0x17, 0x17);
            // powf vs math.Pow may differ in the last ulp; allow a tiny slack.
            assert!(
                (light - want_light).abs() < 1e-12,
                "light {light} vs {want_light}"
            );
            assert!(
                (dark - want_dark).abs() < 1e-12,
                "dark {dark} vs {want_dark}"
            );
        }
    }

    /// PARITY (Go bug, see run_overview_tag_text_color): under lipgloss v2
    /// the Go function's hex re-parse always fails, so EVERY background
    /// gets white text. Verified against the oracle frame differential
    /// (workspace-multi tag badges, e.g. #B199FF renders white although
    /// the dead WCAG branch would pick dark). An earlier version of this
    /// test asserted a Go probe of the extracted contrast ALGORITHM — the
    /// probe missed the fmt.Sprint type regression; the frames are truth.
    #[test]
    fn tag_text_color_always_white_go_bug() {
        let light = RUN_OVERVIEW_TAG_LIGHT_TEXT;
        for bg in [
            Rgb(0xFF, 0xCF, 0x4F),
            Rgb(0x0D, 0x08, 0x87),
            Rgb(0xff, 0xff, 0xff),
            Rgb(0x17, 0x17, 0x17),
            Rgb(0xB8, 0x4F, 0xD4),
            Rgb(0xB1, 0x99, 0xFF),
            Rgb(0x45, 0x4B, 0x54),
        ] {
            assert_eq!(run_overview_tag_text_color(bg), light, "{}", bg.to_hex());
        }
        // The (dead in Go) contrast math itself stays correct: dark text
        // would win on a bright badge, white on a dark one.
        assert!(
            contrast_ratio_rgb(0xFF, 0xCF, 0x4F, 0x17, 0x17, 0x17)
                > contrast_ratio_rgb(0xFF, 0xCF, 0x4F, 0xff, 0xff, 0xff)
        );
        assert!(
            contrast_ratio_rgb(0x0D, 0x08, 0x87, 0xff, 0xff, 0xff)
                > contrast_ratio_rgb(0x0D, 0x08, 0x87, 0x17, 0x17, 0x17)
        );
    }

    #[test]
    fn tag_background_deterministic() {
        let a = run_overview_tag_background_color("wandb-vibe-10", "baseline");
        let b = run_overview_tag_background_color("wandb-vibe-10", "baseline");
        assert_eq!(a, b);
        // colorIndex("baseline") % 10 == 2 (Go probe).
        assert_eq!(a, color_scheme("wandb-vibe-10").unwrap()[2]);
        // Unknown scheme falls back to the default palette.
        assert_eq!(
            run_overview_tag_background_color("no-such-scheme", "baseline"),
            color_scheme(leet_data::config::DEFAULT_COLOR_SCHEME).unwrap()[2]
        );
    }

    #[test]
    fn tag_foreground_per_variant() {
        // PARITY (Go bug): both variants always resolve to white — see
        // tag_text_color_always_white_go_bug.
        let fg = run_overview_tag_foreground_color(adaptive("#B84FD4", "#E281FE"));
        assert_eq!(fg.light, RUN_OVERVIEW_TAG_LIGHT_TEXT);
        assert_eq!(fg.dark, RUN_OVERVIEW_TAG_LIGHT_TEXT);
        let fg = run_overview_tag_foreground_color(adaptive("#454B54", "#565C66"));
        assert_eq!(fg.light, RUN_OVERVIEW_TAG_LIGHT_TEXT);
        assert_eq!(fg.dark, RUN_OVERVIEW_TAG_LIGHT_TEXT);
    }

    #[test]
    fn test_mode_helpers_inert_outside_test_mode() {
        // Unit tests run without WANDB_LEET_TEST=1; guard in case the
        // environment sets it (the OnceLock caches whatever it sees first).
        if !leet_data::test_mode::enabled() {
            assert_eq!(test_mode_terminal_bg(), None);
            assert!(default_dark_background());
        }
    }

    #[test]
    fn named_colors_verbatim() {
        assert_eq!(MOON900, Rgb(0x17, 0x1A, 0x1F));
        assert_eq!(WANDB_COLOR, Rgb(0xFC, 0xBC, 0x32));
        assert_eq!(COLOR_ACCENT, adaptive("#6c6c6c", "#bcbcbc"));
        assert_eq!(COLOR_TEXT.light, COLOR_TEXT.dark);
        assert_eq!(COLOR_TEXT.light, Rgb(0x8a, 0x8a, 0x8a));
        assert_eq!(COLOR_SUBTLE.light, Rgb(0x58, 0x58, 0x58));
        assert_eq!(COLOR_LAYOUT, adaptive("#949494", "#444444"));
        assert_eq!(COLOR_DARK, Rgb(0x17, 0x17, 0x17));
        assert_eq!(COLOR_SUBHEADING, adaptive("#3a3a3a", "#eeeeee"));
        assert_eq!(COLOR_ITEM_KEY, Rgb(0x76, 0x76, 0x76)); // ANSI 243
        assert_eq!(COLOR_ITEM_VALUE, adaptive("#262626", "#d0d0d0"));
        assert_eq!(COLOR_SELECTED.light, WANDB_COLOR);
        assert_eq!(COLOR_SELECTED.dark, WANDB_COLOR);
        assert_eq!(
            COLOR_SELECTED_RUN_INACTIVE_STYLE,
            adaptive("#F5D28A", "#6B5200")
        );
        assert_eq!(RUN_OVERVIEW_TAG_LIGHT_TEXT, Rgb(0xff, 0xff, 0xff));
        // inspectionLegendStyle colors (styles.go:558-566).
        assert_eq!(INSPECTION_LEGEND_FG, adaptive("#111111", "#EEEEEE"));
        assert_eq!(INSPECTION_LEGEND_BG, adaptive("#EEEEEE", "#333333"));
    }

    #[test]
    fn ascii_art_shape() {
        // Go backtick literals start and end with a newline; content is
        // byte-verified against styles.go by the port review, this guards
        // the shape.
        for art in [WANDB_ART, LEET_ART] {
            assert!(art.starts_with('\n'));
            assert!(art.ends_with('\n'));
            assert_eq!(art.lines().skip(1).count(), 5);
        }
        assert!(WANDB_ART.lines().nth(1).unwrap().starts_with("██     ██"));
        assert!(LEET_ART.lines().nth(5).unwrap().starts_with("███████"));
    }

    #[test]
    fn animation_constants() {
        assert_eq!(ANIMATION_DURATION, Duration::from_millis(150));
        assert_eq!(ANIMATION_STEPS, 10);
        // AnimationFrame = AnimationDuration / AnimationSteps.
        assert_eq!(ANIMATION_FRAME, ANIMATION_DURATION / ANIMATION_STEPS);
    }
}
