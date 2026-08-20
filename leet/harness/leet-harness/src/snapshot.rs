//! Frozen snapshot format: a human-diffable text file per frame.
//!
//! ```text
//! #leet-frame v1 cols=120 rows=40 cursor=0,0,hidden
//! <row 0 chars, exactly `cols` display columns>
//! ...
//! #styles
//! <one JSON line per row: RLE runs of [count, fg, bg, attrs]>
//! ```
//!
//! fg/bg encoding: "d" default, "i<n>" indexed, "#rrggbb" RGB.

use std::fmt::Write as _;
use std::path::Path;

use anyhow::{Context, Result, bail};

use crate::grid::{Cell, CellColor, CursorState, Grid};

pub fn save(grid: &Grid, path: &Path) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    std::fs::write(path, encode(grid)).with_context(|| format!("write {}", path.display()))
}

pub fn load(path: &Path) -> Result<Grid> {
    let data = std::fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    decode(&data).with_context(|| format!("decode snapshot {}", path.display()))
}

pub fn encode(grid: &Grid) -> String {
    let mut out = String::new();
    let _ = writeln!(
        out,
        "#leet-frame v1 cols={} rows={} cursor={},{},{}",
        grid.cols,
        grid.rows,
        grid.cursor.col,
        grid.cursor.row,
        if grid.cursor.visible {
            "visible"
        } else {
            "hidden"
        }
    );
    for row in grid.text_rows() {
        // Trailing spaces are stripped (repo pre-commit hooks would anyway);
        // decode() restores missing cells as blanks.
        out.push_str(row.trim_end_matches(' '));
        out.push('\n');
    }
    out.push_str("#styles\n");
    for r in 0..grid.rows {
        let mut runs: Vec<(usize, String, String, u8)> = Vec::new();
        for c in 0..grid.cols {
            let cell = grid.cell(c, r);
            let fg = encode_color(cell.fg);
            let bg = encode_color(cell.bg);
            match runs.last_mut() {
                Some((n, lfg, lbg, lat)) if *lfg == fg && *lbg == bg && *lat == cell.attrs => {
                    *n += 1;
                }
                _ => runs.push((1, fg, bg, cell.attrs)),
            }
        }
        let json: Vec<serde_json::Value> = runs
            .into_iter()
            .map(|(n, fg, bg, at)| serde_json::json!([n, fg, bg, at]))
            .collect();
        out.push_str(&serde_json::Value::Array(json).to_string());
        out.push('\n');
    }
    out
}

pub fn decode(data: &str) -> Result<Grid> {
    let mut lines = data.lines();
    let header = lines.next().unwrap_or_default();
    let Some(rest) = header.strip_prefix("#leet-frame v1 ") else {
        bail!("bad snapshot header: {header:?}");
    };

    let mut cols = 0usize;
    let mut rows = 0usize;
    let mut cursor = CursorState {
        col: 0,
        row: 0,
        visible: false,
    };
    for part in rest.split(' ') {
        if let Some(v) = part.strip_prefix("cols=") {
            cols = v.parse()?;
        } else if let Some(v) = part.strip_prefix("rows=") {
            rows = v.parse()?;
        } else if let Some(v) = part.strip_prefix("cursor=") {
            let bits: Vec<&str> = v.split(',').collect();
            if bits.len() == 3 {
                cursor = CursorState {
                    col: bits[0].parse()?,
                    row: bits[1].parse()?,
                    visible: bits[2] == "visible",
                };
            }
        }
    }
    if cols == 0 || rows == 0 {
        bail!("bad snapshot dimensions");
    }

    let mut grid = Grid::blank(cols, rows);
    grid.cursor = cursor;

    // Char rows.
    let mut char_rows = Vec::with_capacity(rows);
    for _ in 0..rows {
        char_rows.push(lines.next().context("missing char row")?);
    }
    if lines.next() != Some("#styles") {
        bail!("missing #styles section");
    }

    for (r, row_str) in char_rows.iter().enumerate() {
        let style_line = lines.next().context("missing style row")?;
        let runs: Vec<(usize, String, String, u8)> =
            serde_json::from_str(style_line).context("parse style row")?;

        // Expand chars: snapshot rows store display columns; wide chars
        // occupy one char followed by an implicit continuation column.
        let mut col = 0usize;
        for ch in row_str.chars() {
            if col >= cols {
                break;
            }
            grid.cell_mut(col, r).ch = ch;
            let w = char_display_width(ch);
            grid.cell_mut(col, r).width = w;
            col += 1;
            if w == 2 && col < cols {
                *grid.cell_mut(col, r) = Cell {
                    ch,
                    width: 0,
                    fg: None,
                    bg: None,
                    attrs: 0,
                };
                col += 1;
            }
        }

        let mut col = 0usize;
        for (n, fg, bg, attrs) in runs {
            for _ in 0..n {
                if col >= cols {
                    break;
                }
                let cell = grid.cell_mut(col, r);
                cell.fg = decode_color(&fg)?;
                cell.bg = decode_color(&bg)?;
                cell.attrs = attrs;
                col += 1;
            }
        }
    }
    Ok(grid)
}

fn encode_color(c: Option<CellColor>) -> String {
    match c {
        None => "d".to_string(),
        Some(CellColor::Indexed(i)) => format!("i{i}"),
        Some(CellColor::Rgb(r, g, b)) => format!("#{r:02x}{g:02x}{b:02x}"),
    }
}

fn decode_color(s: &str) -> Result<Option<CellColor>> {
    if s == "d" {
        return Ok(None);
    }
    if let Some(i) = s.strip_prefix('i') {
        return Ok(Some(CellColor::Indexed(i.parse()?)));
    }
    if let Some(hex) = s.strip_prefix('#')
        && hex.len() == 6
    {
        let r = u8::from_str_radix(&hex[0..2], 16)?;
        let g = u8::from_str_radix(&hex[2..4], 16)?;
        let b = u8::from_str_radix(&hex[4..6], 16)?;
        return Ok(Some(CellColor::Rgb(r, g, b)));
    }
    bail!("bad color encoding: {s:?}")
}

/// Approximate display width for round-tripping snapshots. The authoritative
/// width comes from the live capture (avt) — this only reconstructs the
/// continuation-cell convention for wide chars in stored files.
fn char_display_width(ch: char) -> u8 {
    // Braille, box drawing, blocks, ASCII: 1. CJK/emoji ranges: 2.
    match ch as u32 {
        0x1100..=0x115F
        | 0x2E80..=0x9FFF
        | 0xAC00..=0xD7A3
        | 0xF900..=0xFAFF
        | 0xFE30..=0xFE4F
        | 0xFF00..=0xFF60
        | 0xFFE0..=0xFFE6
        | 0x1F300..=0x1FAFF
        | 0x20000..=0x3FFFD => 2,
        _ => 1,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::grid::{ATTR_BOLD, Cell, CellColor};

    #[test]
    fn roundtrip_ascii_grid() {
        let mut g = Grid::blank(10, 3);
        g.cell_mut(0, 0).ch = 'h';
        g.cell_mut(1, 0).ch = 'i';
        g.cell_mut(1, 0).fg = Some(CellColor::Rgb(255, 0, 0));
        g.cell_mut(1, 0).attrs = ATTR_BOLD;
        g.cell_mut(5, 2).ch = '⣿';
        g.cursor.visible = true;
        g.cursor.col = 2;

        let encoded = encode(&g);
        let decoded = decode(&encoded).unwrap();
        assert_eq!(decoded, g);
    }

    #[test]
    fn wide_char_roundtrip_keeps_columns() {
        let mut g = Grid::blank(6, 1);
        g.cell_mut(0, 0).ch = '日';
        g.cell_mut(0, 0).width = 2;
        *g.cell_mut(1, 0) = Cell {
            ch: '日',
            width: 0,
            fg: None,
            bg: None,
            attrs: 0,
        };
        g.cell_mut(2, 0).ch = 'x';

        let decoded = decode(&encode(&g)).unwrap();
        assert_eq!(decoded.cell(2, 0).ch, 'x');
        assert_eq!(decoded.cell(0, 0).width, 2);
        assert_eq!(decoded.cell(1, 0).width, 0);
    }
}
