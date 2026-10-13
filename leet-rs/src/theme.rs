//! Colors, styles, and UI constants.

use std::sync::atomic::{AtomicBool, Ordering};

use ratatui::style::{Color, Modifier, Style};

/// Whether the terminal has a dark background. Default true.
static DARK_BACKGROUND: AtomicBool = AtomicBool::new(true);

pub fn set_dark_background(dark: bool) {
    DARK_BACKGROUND.store(dark, Ordering::Relaxed);
}

pub fn is_dark_background() -> bool {
    DARK_BACKGROUND.load(Ordering::Relaxed)
}

/// Detected terminal background color, if any.
static TERM_BG: std::sync::OnceLock<Option<(u8, u8, u8)>> = std::sync::OnceLock::new();

pub fn set_terminal_background(rgb: Option<(u8, u8, u8)>) {
    let _ = TERM_BG.set(rgb);
    if let Some((r, g, b)) = rgb {
        // Perceived luminance decides light vs dark.
        let lum = 0.2126 * f64::from(r) + 0.7152 * f64::from(g) + 0.0722 * f64::from(b);
        set_dark_background(lum < 128.0);
    }
}

fn terminal_background() -> Option<(u8, u8, u8)> {
    TERM_BG.get().copied().flatten()
}

/// A color that picks between light and dark variants based on the terminal
/// background.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Adaptive {
    pub light: (u8, u8, u8),
    pub dark: (u8, u8, u8),
}

pub const fn hex(v: u32) -> (u8, u8, u8) {
    (
        ((v >> 16) & 0xff) as u8,
        ((v >> 8) & 0xff) as u8,
        (v & 0xff) as u8,
    )
}

pub const fn adaptive(light: u32, dark: u32) -> Adaptive {
    Adaptive {
        light: hex(light),
        dark: hex(dark),
    }
}

pub const fn uniform(v: u32) -> Adaptive {
    Adaptive {
        light: hex(v),
        dark: hex(v),
    }
}

impl Adaptive {
    pub fn color(self) -> Color {
        let (r, g, b) = self.rgb();
        Color::Rgb(r, g, b)
    }

    pub fn rgb(self) -> (u8, u8, u8) {
        if is_dark_background() {
            self.dark
        } else {
            self.light
        }
    }
}

impl From<Adaptive> for Color {
    fn from(a: Adaptive) -> Color {
        a.color()
    }
}

// ---- Immutable UI constants ----

pub const STATUS_BAR_HEIGHT: u16 = 1;

/// Blank columns on each side of every content area.
pub const CONTENT_PADDING: u16 = 1;
pub const CONTENT_PADDING_COLS: u16 = 2 * CONTENT_PADDING;

/// The single terminal column occupied by a sidebar's vertical border rule.
pub const SIDEBAR_BORDER_COLS: u16 = 1;

/// Total non-content columns inside a sidebar.
pub const SIDEBAR_OVERHEAD: i32 = (SIDEBAR_BORDER_COLS + CONTENT_PADDING_COLS) as i32;

/// Blank row at the bottom of a sidebar separating content from status bar.
pub const SIDEBAR_BOTTOM_PADDING: u16 = 1;

pub const MIN_CHART_WIDTH: u16 = 20;
pub const MIN_CHART_HEIGHT: u16 = 5;
pub const MIN_METRIC_CHART_WIDTH: u16 = 18;
pub const MIN_METRIC_CHART_HEIGHT: u16 = 4;
pub const CHART_BORDER_SIZE: u16 = 2;
pub const CHART_TITLE_HEIGHT: i32 = 1;
pub const CHART_HEADER_HEIGHT: i32 = 1;

// Default grid sizes.
pub const DEFAULT_METRICS_GRID_ROWS: i32 = 4;
pub const DEFAULT_METRICS_GRID_COLS: i32 = 3;
pub const DEFAULT_SYSTEM_GRID_ROWS: i32 = 6;
pub const DEFAULT_SYSTEM_GRID_COLS: i32 = 2;
pub const DEFAULT_WORKSPACE_METRICS_GRID_ROWS: i32 = 3;
pub const DEFAULT_WORKSPACE_METRICS_GRID_COLS: i32 = 3;
pub const DEFAULT_WORKSPACE_SYSTEM_GRID_ROWS: i32 = 3;
pub const DEFAULT_WORKSPACE_SYSTEM_GRID_COLS: i32 = 3;
pub const DEFAULT_SYMON_GRID_ROWS: i32 = 3;
pub const DEFAULT_SYMON_GRID_COLS: i32 = 3;

// Sidebar constants (golden-ratio-based proportions).
pub const SIDEBAR_WIDTH_RATIO: f64 = 0.382;
pub const SIDEBAR_WIDTH_RATIO_BOTH: f64 = 0.236;
pub const SIDEBAR_MIN_WIDTH: i32 = 40;
pub const SIDEBAR_MAX_WIDTH: i32 = 120;

/// Key/value column width ratio in sidebars.
pub const SIDEBAR_KEY_WIDTH_RATIO: f64 = 0.4;

// Rune constants.
pub const BOX_LIGHT_VERTICAL: char = '\u{2502}'; // │
pub const EM_DASH: char = '\u{2014}'; // —
pub const MEDIUM_SHADE_BLOCK: char = '\u{2592}'; // ▒

// ---- Brand and functional colors ----

pub const MOON_900: Color = Color::Rgb(0x17, 0x1A, 0x1F);
pub const WANDB_COLOR: Color = Color::Rgb(0xFC, 0xBC, 0x32);

pub const TEAL_450: Adaptive = adaptive(0x10BFCC, 0xE1F7FA);

/// Color for main items such as chart titles.
pub const COLOR_ACCENT: Adaptive = adaptive(0x6c6c6c, 0xbcbcbc);
/// Main text color.
pub const COLOR_TEXT: Adaptive = adaptive(0x8a8a8a, 0x8a8a8a);
/// Extra or parenthetical text; chart axis lines.
pub const COLOR_SUBTLE: Adaptive = adaptive(0x585858, 0x585858);
/// Layout elements: borders and separators.
pub const COLOR_LAYOUT: Adaptive = adaptive(0x949494, 0x444444);
pub const COLOR_DARK: Color = Color::Rgb(0x17, 0x17, 0x17);
/// Layout elements when highlighted or focused.
pub const COLOR_LAYOUT_HIGHLIGHT: Adaptive = TEAL_450;
/// Top-level headings (logo, help section headings).
pub const COLOR_HEADING: Color = WANDB_COLOR;
/// Lower-level headings (help keys, metrics grid header).
pub const COLOR_SUBHEADING: Adaptive = adaptive(0x3a3a3a, 0xeeeeee);
/// Key color in key-value pairs (ANSI 243).
pub const COLOR_ITEM_KEY: Color = Color::Indexed(243);
pub const COLOR_ITEM_VALUE: Adaptive = adaptive(0x262626, 0xd0d0d0);
/// Selected line in lists.
pub const COLOR_SELECTED: Adaptive = adaptive(0xFCBC32, 0xFCBC32);

pub const COLOR_SELECTED_RUN_INACTIVE: Adaptive = adaptive(0xF5D28A, 0x6B5200);

// ---- ASCII art ----

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

// ---- Color schemes ----

pub const COLOR_MODE_PER_PLOT: &str = "per_plot";
pub const COLOR_MODE_PER_SERIES: &str = "per_series";

pub const DEFAULT_COLOR_SCHEME: &str = "wandb-vibe-10";
pub const DEFAULT_PER_PLOT_COLOR_SCHEME: &str = "sunset-glow";
pub const DEFAULT_TAG_COLOR_SCHEME: &str = DEFAULT_COLOR_SCHEME;
pub const DEFAULT_SINGLE_RUN_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;
pub const DEFAULT_SYSTEM_COLOR_SCHEME: &str = "wandb-vibe-10";
pub const DEFAULT_FRENCH_FRIES_COLOR_SCHEME: &str = "viridis";
pub const DEFAULT_SYSTEM_COLOR_MODE: &str = COLOR_MODE_PER_SERIES;

pub static COLOR_SCHEMES: &[(&str, &[Adaptive])] = &[
    (
        "sunset-glow", // Golden-pink gradient
        &[
            adaptive(0xB84FD4, 0xE281FE),
            adaptive(0xBD5AB9, 0xE78DE3),
            adaptive(0xBF60AB, 0xE993D5),
            adaptive(0xC36C91, 0xED9FBB),
            adaptive(0xC67283, 0xF0A5AD),
            adaptive(0xC87875, 0xF2AB9F),
            adaptive(0xCC8451, 0xF6B784),
            adaptive(0xCE8A45, 0xF8BD78),
            adaptive(0xD19038, 0xFBC36B),
            adaptive(0xD59C1C, 0xFFCF4F),
        ],
    ),
    (
        "blush-tide", // Pink-teal gradient
        &[
            adaptive(0xD94F8C, 0xF9A7CC),
            adaptive(0xCA60AC, 0xEEB3E0),
            adaptive(0xB96FC4, 0xE4BFEE),
            adaptive(0xA77DD4, 0xDBC9F7),
            adaptive(0x9489DF, 0xD5D3FC),
            adaptive(0x8095E5, 0xD1DCFE),
            adaptive(0x6AA1E6, 0xD0E5FF),
            adaptive(0x50ACE2, 0xD3ECFE),
            adaptive(0x33B6D9, 0xD8F2FC),
            adaptive(0x10BFCC, 0xE1F7FA),
        ],
    ),
    (
        "gilded-lagoon", // Golden-teal gradient
        &[
            adaptive(0xD59C1C, 0xFFCF4F),
            adaptive(0xC2A636, 0xEADB74),
            adaptive(0xAFAD4C, 0xDAE492),
            adaptive(0x9CB35F, 0xCFEBAB),
            adaptive(0x8AB872, 0xC8EFC0),
            adaptive(0x77BB83, 0xC5F3D2),
            adaptive(0x62BE95, 0xC7F5E1),
            adaptive(0x4CBFA6, 0xCDF6ED),
            adaptive(0x32C0B9, 0xD5F7F5),
            adaptive(0x10BFCC, 0xE1F7FA),
        ],
    ),
    (
        "bootstrap-vibe", // Badge-friendly utility tones
        &[
            adaptive(0x6c757d, 0xa7b0b8),
            adaptive(0x0d6efd, 0x78aefc),
            adaptive(0x198754, 0x72cf9d),
            adaptive(0x0dcaf0, 0x7be3fa),
            adaptive(0xfd7e14, 0xffb574),
            adaptive(0xdc3545, 0xf28a93),
            adaptive(0x6f42c1, 0xb99aff),
            adaptive(0x20c997, 0x83e6ca),
        ],
    ),
    (
        "wandb-vibe-10",
        &[
            adaptive(0x8A8D91, 0xB1B4B9),
            adaptive(0x3DBAC4, 0x58D3DB),
            adaptive(0x42B88A, 0x5ED6A4),
            adaptive(0xE07040, 0xFCA36F),
            adaptive(0xE85565, 0xFF7A88),
            adaptive(0x5A96E0, 0x7DB1FA),
            adaptive(0x9AC24A, 0xBBE06B),
            adaptive(0xE0AD20, 0xFFCF4D),
            adaptive(0xC85EE8, 0xE180FF),
            adaptive(0x9475E8, 0xB199FF),
        ],
    ),
    (
        "wandb-vibe-20",
        &[
            adaptive(0xAEAFB3, 0xD4D5D9),
            adaptive(0x454B54, 0x565C66),
            adaptive(0x7AD4DB, 0xA9EDF2),
            adaptive(0x04707F, 0x038194),
            adaptive(0x6DDBA8, 0xA1F0CB),
            adaptive(0x00704A, 0x00875A),
            adaptive(0xEAB08A, 0xFFCFB2),
            adaptive(0xA84728, 0xC2562F),
            adaptive(0xEAA0A5, 0xFFC7CA),
            adaptive(0xB82038, 0xCC2944),
            adaptive(0x8FBDE8, 0xBDD9FF),
            adaptive(0x2850A8, 0x1F59C4),
            adaptive(0xB0D470, 0xD0ED9D),
            adaptive(0x4E7424, 0x5F8A2D),
            adaptive(0xEAC860, 0xFFE49E),
            adaptive(0x9A5E10, 0xB8740F),
            adaptive(0xD99DE8, 0xEFC2FC),
            adaptive(0x8528A8, 0x9E36C2),
            adaptive(0xB8A8E8, 0xD6C9FF),
            adaptive(0x5538B0, 0x6645D1),
        ],
    ),
    (
        // Colorblind-friendly siennas/blues/grays, gradient-ordered.
        "dusk-shore",
        &[
            adaptive(0x823520, 0x994228),
            adaptive(0xA84728, 0xC2562F),
            adaptive(0xBA5028, 0xD96534),
            adaptive(0xD86030, 0xFC8F58),
            adaptive(0xE07040, 0xFCA36F),
            adaptive(0xE89865, 0xFFBA91),
            adaptive(0xEAB08A, 0xFFCFB2),
            adaptive(0x78A8E8, 0xA4C9FC),
            adaptive(0x5A96E0, 0x7DB1FA),
            adaptive(0x4880DA, 0x629DF5),
            adaptive(0x2E68CC, 0x397EED),
            adaptive(0x2258BE, 0x286CE0),
            adaptive(0x2850A8, 0x1F59C4),
            adaptive(0x8A8D91, 0xB1B4B9),
            adaptive(0x606872, 0x79808A),
            adaptive(0x454B54, 0x565C66),
        ],
    ),
    (
        // Same palette as "dusk-shore", interleaved for differentiation.
        "clear-signal",
        &[
            adaptive(0xBA5028, 0xD96534),
            adaptive(0x2258BE, 0x286CE0),
            adaptive(0x4880DA, 0x629DF5),
            adaptive(0x823520, 0x994228),
            adaptive(0xE07040, 0xFCA36F),
            adaptive(0xEAB08A, 0xFFCFB2),
            adaptive(0x8A8D91, 0xB1B4B9),
            adaptive(0x606872, 0x79808A),
            adaptive(0x5A96E0, 0x7DB1FA),
            adaptive(0x2850A8, 0x1F59C4),
            adaptive(0xA84728, 0xC2562F),
            adaptive(0xD86030, 0xFC8F58),
            adaptive(0xE89865, 0xFFBA91),
            adaptive(0x78A8E8, 0xA4C9FC),
            adaptive(0x2E68CC, 0x397EED),
            adaptive(0x454B54, 0x565C66),
        ],
    ),
    // Sequential palettes for French Fries percentage heatmaps.
    (
        "traffic-light",
        &[
            uniform(0x1A9850),
            uniform(0x3EAE51),
            uniform(0x67C35C),
            uniform(0x97D168),
            uniform(0xC8DE72),
            uniform(0xF1DD6B),
            uniform(0xFDB863),
            uniform(0xF89C5A),
            uniform(0xF67C4B),
            uniform(0xE85D4F),
            uniform(0xD73027),
        ],
    ),
    (
        "viridis",
        &[
            uniform(0x440154),
            uniform(0x482475),
            uniform(0x414487),
            uniform(0x355F8D),
            uniform(0x2A788E),
            uniform(0x21918C),
            uniform(0x22A884),
            uniform(0x44BF70),
            uniform(0x7AD151),
            uniform(0xBDDF26),
            uniform(0xFDE725),
        ],
    ),
    (
        "plasma",
        &[
            uniform(0x0D0887),
            uniform(0x41049D),
            uniform(0x6A00A8),
            uniform(0x8F0DA4),
            uniform(0xB12A90),
            uniform(0xCC4778),
            uniform(0xE16462),
            uniform(0xF2844B),
            uniform(0xFCA636),
            uniform(0xFCCE25),
            uniform(0xF0F921),
        ],
    ),
    (
        "inferno",
        &[
            uniform(0x000004),
            uniform(0x160B39),
            uniform(0x420A68),
            uniform(0x6A176E),
            uniform(0x932667),
            uniform(0xBC3754),
            uniform(0xDD513A),
            uniform(0xF37819),
            uniform(0xFCA50A),
            uniform(0xF6D746),
            uniform(0xFCFFA4),
        ],
    ),
    (
        "magma",
        &[
            uniform(0x000004),
            uniform(0x140E36),
            uniform(0x3B0F70),
            uniform(0x641A80),
            uniform(0x8C2981),
            uniform(0xB73779),
            uniform(0xDE4968),
            uniform(0xF7705C),
            uniform(0xFE9F6D),
            uniform(0xFECF92),
            uniform(0xFCFDBF),
        ],
    ),
    (
        "cividis",
        &[
            uniform(0x00224E),
            uniform(0x083370),
            uniform(0x35456C),
            uniform(0x4F576C),
            uniform(0x666970),
            uniform(0x7D7C78),
            uniform(0x948E77),
            uniform(0xAEA371),
            uniform(0xC8B866),
            uniform(0xE5CF52),
            uniform(0xFEE838),
        ],
    ),
];

pub fn is_known_color_scheme(scheme: &str) -> bool {
    COLOR_SCHEMES.iter().any(|(name, _)| *name == scheme)
}

fn color_scheme_or_default(scheme: &str, fallback: &str) -> &'static [Adaptive] {
    COLOR_SCHEMES
        .iter()
        .find(|(name, colors)| *name == scheme && !colors.is_empty())
        .or_else(|| COLOR_SCHEMES.iter().find(|(name, _)| *name == fallback))
        .map(|(_, colors)| *colors)
        .unwrap_or(&[])
}

/// The palette for the requested scheme, falling back to the default.
pub fn graph_colors(scheme: &str) -> &'static [Adaptive] {
    color_scheme_or_default(scheme, DEFAULT_COLOR_SCHEME)
}

/// The palette for French Fries heatmaps.
pub fn french_fries_colors(scheme: &str) -> &'static [Adaptive] {
    color_scheme_or_default(scheme, DEFAULT_FRENCH_FRIES_COLOR_SCHEME)
}

/// Deterministically maps a name to a palette index (FNV-1a 32-bit).
pub fn color_index(name: &str, palette_len: usize) -> usize {
    if palette_len == 0 {
        return 0;
    }
    let mut hash: u32 = 0x811c9dc5;
    for b in name.bytes() {
        hash ^= u32::from(b);
        hash = hash.wrapping_mul(0x01000193);
    }
    (hash % palette_len as u32) as usize
}

// ---- Styles ----

pub fn header_style() -> Style {
    Style::new()
        .add_modifier(Modifier::BOLD)
        .fg(COLOR_SUBHEADING.color())
}

pub fn nav_info_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

pub fn border_style() -> Style {
    Style::new().fg(COLOR_LAYOUT.color())
}

pub fn focused_border_style() -> Style {
    Style::new().fg(COLOR_LAYOUT_HIGHLIGHT.color())
}

pub fn title_style() -> Style {
    Style::new()
        .fg(COLOR_ACCENT.color())
        .add_modifier(Modifier::BOLD)
}

pub fn series_count_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

pub fn axis_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

pub fn label_style() -> Style {
    Style::new().fg(COLOR_TEXT.color())
}

pub fn inspection_line_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

pub fn inspection_legend_style() -> Style {
    Style::new()
        .fg(adaptive(0x111111, 0xEEEEEE).color())
        .bg(adaptive(0xEEEEEE, 0x333333).color())
}

pub fn status_bar_style() -> Style {
    Style::new().fg(MOON_900).bg(COLOR_LAYOUT_HIGHLIGHT.color())
}

pub fn sidebar_key_style() -> Style {
    Style::new().fg(COLOR_ITEM_KEY)
}

pub fn sidebar_value_style() -> Style {
    Style::new().fg(COLOR_ITEM_VALUE.color())
}

pub fn sidebar_highlighted_item_style() -> Style {
    Style::new().fg(COLOR_DARK).bg(COLOR_SELECTED.color())
}

pub fn sidebar_section_header_style() -> Style {
    Style::new()
        .add_modifier(Modifier::BOLD)
        .fg(COLOR_SUBHEADING.color())
}

pub fn sidebar_section_style() -> Style {
    Style::new()
        .fg(COLOR_TEXT.color())
        .add_modifier(Modifier::BOLD)
}

pub fn help_key_style() -> Style {
    Style::new()
        .add_modifier(Modifier::BOLD)
        .fg(COLOR_SUBHEADING.color())
}

pub fn help_desc_style() -> Style {
    Style::new().fg(COLOR_TEXT.color())
}

pub fn help_section_style() -> Style {
    Style::new().add_modifier(Modifier::BOLD).fg(COLOR_HEADING)
}

pub fn logs_timestamp_style() -> Style {
    Style::new().fg(COLOR_SUBTLE.color())
}

pub fn logs_value_style() -> Style {
    Style::new().fg(COLOR_ITEM_VALUE.color())
}

pub fn logs_highlighted_style() -> Style {
    Style::new().bg(COLOR_SELECTED.color()).fg(COLOR_DARK)
}

pub fn selected_run_style() -> Style {
    Style::new().bg(COLOR_SELECTED.color()).fg(COLOR_DARK)
}

pub fn selected_run_inactive_style() -> Style {
    Style::new().bg(COLOR_SELECTED_RUN_INACTIVE.color())
}

/// Background 5% blended toward gray from the terminal background, for odd
/// rows in the workspace run list.
pub fn odd_run_style() -> Style {
    let bg = match terminal_background() {
        Some((r, g, b)) => {
            let blend = |base: u8| -> u8 { (f64::from(base) * 0.95 + 128.0 * 0.05).round() as u8 };
            Color::Rgb(blend(r), blend(g), blend(b))
        }
        None => {
            if is_dark_background() {
                Color::Rgb(0x1c, 0x1c, 0x1c)
            } else {
                Color::Rgb(0xd0, 0xd0, 0xd0)
            }
        }
    };
    Style::new().bg(bg)
}

// ---- Tag badge colors (WCAG-contrast-aware) ----

/// Background color for a tag badge: deterministic per tag.
pub fn tag_background_color(scheme: &str, tag: &str) -> Adaptive {
    let colors = graph_colors(scheme);
    colors[color_index(tag, colors.len())]
}

/// White or dark text for a single background color, whichever yields the
/// higher WCAG contrast ratio.
fn tag_text_color(bg: (u8, u8, u8)) -> Color {
    let light = contrast_ratio_rgb(bg, (0xff, 0xff, 0xff));
    let dark = contrast_ratio_rgb(bg, (0x17, 0x17, 0x17));
    if dark >= light {
        COLOR_DARK
    } else {
        Color::Rgb(0xff, 0xff, 0xff)
    }
}

/// Complete badge style for a tag.
pub fn tag_style(scheme: &str, tag: &str) -> Style {
    let bg = tag_background_color(scheme, tag);
    Style::new()
        .fg(tag_text_color(bg.rgb()))
        .bg(bg.color())
        .add_modifier(Modifier::BOLD)
}

// ---- Shared render helpers ----

/// Draws a full-width em-dash separator line, used between vertically
/// stacked panes in the central column instead of per-pane top borders.
pub fn render_horizontal_separator(area: ratatui::layout::Rect, buf: &mut ratatui::buffer::Buffer) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    let line: String = std::iter::repeat_n(EM_DASH, area.width as usize).collect();
    buf.set_stringn(area.x, area.y, &line, area.width as usize, border_style());
}

/// Renders the wandb/leet ASCII art centered in the given area.
pub fn render_logo_art(area: ratatui::layout::Rect, buf: &mut ratatui::buffer::Buffer) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    let style = Style::new().fg(COLOR_HEADING).add_modifier(Modifier::BOLD);

    let wandb: Vec<&str> = WANDB_ART.trim_matches('\n').lines().collect();
    let leet: Vec<&str> = LEET_ART.trim_matches('\n').lines().collect();
    let line_width = |lines: &[&str]| lines.iter().map(|l| l.chars().count()).max().unwrap_or(0);
    let wandb_w = line_width(&wandb);
    let leet_w = line_width(&leet);
    let block_w = wandb_w.max(leet_w);
    let block_h = wandb.len() + leet.len();

    let x0 = area.x as i32 + (area.width as i32 - block_w as i32) / 2;
    let mut y = area.y as i32 + (area.height as i32 - block_h as i32) / 2;

    for group in [&wandb, &leet] {
        for line in group {
            let w = line.chars().count();
            // Each art block is centered within the combined block width.
            let x = x0 + (block_w as i32 - w as i32) / 2;
            if y >= area.y as i32 && y < area.bottom() as i32 && x >= 0 {
                buf.set_stringn(
                    x as u16,
                    y as u16,
                    line,
                    area.right().saturating_sub(x as u16) as usize,
                    style,
                );
            }
            y += 1;
        }
    }
}

/// WCAG 2.x contrast ratio between two RGB colors (1..=21).
fn contrast_ratio_rgb(a: (u8, u8, u8), b: (u8, u8, u8)) -> f64 {
    let l1 = relative_luminance(a);
    let l2 = relative_luminance(b);
    let (hi, lo) = if l1 < l2 { (l2, l1) } else { (l1, l2) };
    (hi + 0.05) / (lo + 0.05)
}

fn relative_luminance((r, g, b): (u8, u8, u8)) -> f64 {
    0.2126 * srgb_to_linear(r) + 0.7152 * srgb_to_linear(g) + 0.0722 * srgb_to_linear(b)
}

fn srgb_to_linear(c: u8) -> f64 {
    let v = f64::from(c) / 255.0;
    if v <= 0.04045 {
        v / 12.92
    } else {
        ((v + 0.055) / 1.055).powf(2.4)
    }
}
