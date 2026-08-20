//! Tiered grid differ + agent-legible reports.
//!
//! Tier 1 (chars): 0 mismatched cells, absolute counts, after normalization
//! (masks applied, `(space, any-style)` ≡ blank, wide-char continuations
//! skipped). Tier 2 (color): fg/bg/attrs on non-blank cells. Tier 0
//! (structural) is implemented as Tier 1 on scenarios that restrict
//! themselves to structural snapshots — border extraction comes later if
//! unicode-hostile fixtures need it.

use crate::grid::{Cell, CellColor, Grid};
use crate::scenario::Mask;

/// Canonicalize a color for comparison: xterm-256 indices 16..=255 have
/// fixed RGB values, so `Indexed(243)` and `Rgb(118,118,118)` are the SAME
/// color in different SGR encodings (Go lipgloss emits indexed for colors
/// declared as "243"; the Rust port emits truecolor). Indices 0..=15 are
/// terminal-theme-dependent and stay symbolic.
fn canonical_color(c: Option<CellColor>) -> Option<CellColor> {
    match c {
        Some(CellColor::Indexed(n)) if n >= 16 => {
            let rgb = if n >= 232 {
                let v = 8 + 10 * (n - 232);
                (v, v, v)
            } else {
                const STEPS: [u8; 6] = [0, 95, 135, 175, 215, 255];
                let i = n - 16;
                (
                    STEPS[(i / 36) as usize],
                    STEPS[((i % 36) / 6) as usize],
                    STEPS[(i % 6) as usize],
                )
            };
            Some(CellColor::Rgb(rgb.0, rgb.1, rgb.2))
        }
        other => other,
    }
}

fn colors_eq(a: Option<CellColor>, b: Option<CellColor>) -> bool {
    canonical_color(a) == canonical_color(b)
}

#[derive(Debug, Clone)]
pub struct CellDiff {
    pub col: usize,
    pub row: usize,
    pub a: Cell,
    pub b: Cell,
    /// True if the difference is style-only (chars match).
    pub style_only: bool,
}

#[derive(Debug, Clone, Default)]
pub struct DiffReport {
    pub char_diffs: Vec<CellDiff>,
    pub style_diffs: Vec<CellDiff>,
    pub size_mismatch: Option<((usize, usize), (usize, usize))>,
    pub cursor_mismatch: Option<(String, String)>,
}

impl DiffReport {
    pub fn tier1_clean(&self) -> bool {
        self.char_diffs.is_empty() && self.size_mismatch.is_none()
    }

    pub fn tier2_clean(&self) -> bool {
        self.tier1_clean() && self.style_diffs.is_empty()
    }

    pub fn clean_at(&self, tier: u8) -> bool {
        match tier {
            0 | 1 => self.tier1_clean(),
            _ => self.tier2_clean(),
        }
    }
}

pub fn diff_grids(a: &Grid, b: &Grid, masks: &[Mask]) -> DiffReport {
    let mut report = DiffReport::default();

    if (a.cols, a.rows) != (b.cols, b.rows) {
        report.size_mismatch = Some(((a.cols, a.rows), (b.cols, b.rows)));
        return report;
    }

    let mut a = a.clone();
    let mut b = b.clone();
    for m in masks {
        a.mask(m.x, m.y, m.w, m.h);
        b.mask(m.x, m.y, m.w, m.h);
    }

    for row in 0..a.rows {
        for col in 0..a.cols {
            let ca = a.cell(col, row);
            let cb = b.cell(col, row);

            let chars_match = ca.ch == cb.ch || (ca.is_char_blank() && cb.is_char_blank());
            if !chars_match {
                report.char_diffs.push(CellDiff {
                    col,
                    row,
                    a: *ca,
                    b: *cb,
                    style_only: false,
                });
                continue;
            }
            // Style tier: skip blanks — padding style is normalized away
            // (lipgloss Join/Place padding is unstyled spaces; see docs).
            if !ca.is_char_blank()
                && (!colors_eq(ca.fg, cb.fg) || !colors_eq(ca.bg, cb.bg) || ca.attrs != cb.attrs)
            {
                report.style_diffs.push(CellDiff {
                    col,
                    row,
                    a: *ca,
                    b: *cb,
                    style_only: true,
                });
            }
        }
    }

    if a.cursor != b.cursor {
        report.cursor_mismatch = Some((format!("{:?}", a.cursor), format!("{:?}", b.cursor)));
    }

    report
}

/// Human/agent-legible side-by-side rendering with diff markers.
/// `a_label`/`b_label` name the two sides (e.g. "run1" vs "run2", or
/// "oracle" vs "rust").
pub fn render_report(
    a: &Grid,
    b: &Grid,
    report: &DiffReport,
    a_label: &str,
    b_label: &str,
) -> String {
    use std::fmt::Write as _;
    let mut out = String::new();

    if let Some(((ac, ar), (bc, br))) = report.size_mismatch {
        let _ = writeln!(
            out,
            "SIZE MISMATCH: {a_label}={ac}x{ar} {b_label}={bc}x{br}"
        );
        return out;
    }

    let _ = writeln!(
        out,
        "char diffs: {}   style diffs: {}   cursor: {}",
        report.char_diffs.len(),
        report.style_diffs.len(),
        report
            .cursor_mismatch
            .as_ref()
            .map(|(x, y)| format!("MISMATCH {x} vs {y}"))
            .unwrap_or_else(|| "ok".to_string()),
    );

    // Per-diff detail (capped).
    for d in report.char_diffs.iter().take(50) {
        let _ = writeln!(
            out,
            "  [{},{}] char {:?} vs {:?}",
            d.col, d.row, d.a.ch, d.b.ch
        );
    }
    for d in report.style_diffs.iter().take(20) {
        let _ = writeln!(
            out,
            "  [{},{}] style {:?} fg{:?}/bg{:?}/a{} vs fg{:?}/bg{:?}/a{}",
            d.col, d.row, d.a.ch, d.a.fg, d.a.bg, d.a.attrs, d.b.fg, d.b.bg, d.b.attrs
        );
    }

    // Rows containing char diffs, side by side with a marker line.
    let mut rows_with_diffs: Vec<usize> = report.char_diffs.iter().map(|d| d.row).collect();
    rows_with_diffs.sort_unstable();
    rows_with_diffs.dedup();

    let a_rows = a.text_rows();
    let b_rows = b.text_rows();
    for &row in rows_with_diffs.iter().take(20) {
        let _ = writeln!(out, "row {row:3} {a_label:>8}: |{}|", a_rows[row]);
        let _ = writeln!(out, "        {b_label:>8}: |{}|", b_rows[row]);
        let mut marker = String::new();
        for col in 0..a.cols {
            if report
                .char_diffs
                .iter()
                .any(|d| d.row == row && d.col == col)
            {
                marker.push('^');
            } else {
                marker.push(' ');
            }
        }
        let _ = writeln!(out, "                  |{marker}|");
    }
    out
}
