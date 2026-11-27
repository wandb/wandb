//! Image decoding plus half-block ANSI and Kitty graphics rendering caches.

use std::collections::HashMap;
use std::io::Cursor;
use std::sync::atomic::{AtomicU32, Ordering};
use std::time::{Duration, Instant};

use image::RgbaImage;
use image::imageops::FilterType;
use ratatui::buffer::Buffer;
use ratatui::layout::Rect;
use ratatui::style::{Color, Style};

use super::kitty;
use crate::textwrap::truncate_value;
use crate::theme;

/// How an image is drawn into the terminal.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PictureMode {
    /// Universal half-block ANSI glyphs.
    Glyph,
    /// Full-resolution Kitty graphics (Unicode placeholder placement).
    Kitty,
}

/// A visible media placement: image path plus its cell dimensions.
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct MediaRenderKey {
    pub path: String,
    pub width: u16,
    pub height: u16,
}

const MEDIA_ERROR_RETRY_AFTER: Duration = Duration::from_secs(1);

/// Cache caps: decoded full-resolution images are large (RGBA), rendered
/// glyph frames are tiny. Keeping recently used entries beyond the visible
/// set makes run-switching and pane toggles cache-warm instead of paying a
/// synchronous re-decode in the render path.
const DECODED_CACHE_CAP: usize = 32;
const GLYPH_CACHE_CAP: usize = 256;

/// Default terminal cell pixel dimensions, used until the real cell size is
/// known.
const DEFAULT_CELL_PIXEL_W: u32 = 8;
const DEFAULT_CELL_PIXEL_H: u32 = 16;

/// Kitty graphics image IDs live in a terminal-wide namespace. Media
/// thumbnail IDs are allocated from a process-wide counter starting well
/// above other IDs so images never overwrite each other, including across
/// the workspace and single-run media panes.
const MEDIA_KITTY_ID_BASE: u32 = 10_000;

static MEDIA_KITTY_ID_COUNTER: AtomicU32 = AtomicU32::new(0);

fn next_media_kitty_id() -> u32 {
    MEDIA_KITTY_ID_BASE + MEDIA_KITTY_ID_COUNTER.fetch_add(1, Ordering::Relaxed) + 1
}

/// A rendered half-block frame: one `(fg, bg)` pair per cell, row-major.
/// `None` colors mean "terminal default" (fully transparent source pixels).
struct GlyphImage {
    width: u16,
    height: u16,
    cells: Vec<(Option<Color>, Option<Color>)>,
}

struct KittyPicture {
    id: u32,
    /// The image generation transmitted, to re-transmit on image change.
    transmitted: bool,
}

struct RenderError {
    text: String,
    at: Instant,
}

/// Owns image decoding plus ANSI/Kitty rendering caches for a media pane.
pub struct MediaImageRenderer {
    mode: PictureMode,
    /// The terminal's cell pixel dimensions, so Kitty images are encoded at
    /// the display's true resolution. Zero until known.
    cell_pixel_w: u32,
    cell_pixel_h: u32,
    decoded: HashMap<String, RgbaImage>,
    decoded_last_use: HashMap<String, u64>,
    errors: HashMap<String, RenderError>,
    glyphs: HashMap<MediaRenderKey, GlyphImage>,
    glyphs_last_use: HashMap<MediaRenderKey, u64>,
    /// Monotonic counter for LRU bookkeeping; bumped once per park cycle.
    use_tick: u64,
    pictures: HashMap<MediaRenderKey, KittyPicture>,
    /// Raw escape sequences to write to the terminal after the next draw.
    pending_output: String,
}

impl Default for MediaImageRenderer {
    fn default() -> Self {
        Self::new()
    }
}

impl MediaImageRenderer {
    pub fn new() -> Self {
        Self {
            mode: PictureMode::Glyph,
            cell_pixel_w: 0,
            cell_pixel_h: 0,
            decoded: HashMap::new(),
            decoded_last_use: HashMap::new(),
            errors: HashMap::new(),
            glyphs: HashMap::new(),
            glyphs_last_use: HashMap::new(),
            use_tick: 0,
            pictures: HashMap::new(),
            pending_output: String::new(),
        }
    }

    pub fn mode(&self) -> PictureMode {
        self.mode
    }

    /// Records the terminal's cell pixel size (e.g. from a TIOCGWINSZ probe).
    pub fn set_cell_pixel_size(&mut self, w: u32, h: u32) {
        if w > 0 && h > 0 && (w, h) != (self.cell_pixel_w, self.cell_pixel_h) {
            self.cell_pixel_w = w;
            self.cell_pixel_h = h;
            self.invalidate_pictures();
        }
    }

    /// Switches between Glyph and Kitty modes. Returns true if the mode
    /// changed (Kitty requires terminal support).
    pub fn toggle_mode(&mut self) -> bool {
        match self.mode {
            PictureMode::Glyph => {
                if !kitty::terminal_signals_kitty_graphics() {
                    return false;
                }
                self.mode = PictureMode::Kitty;
                true
            }
            PictureMode::Kitty => {
                self.mode = PictureMode::Glyph;
                self.invalidate_pictures();
                true
            }
        }
    }

    fn invalidate_pictures(&mut self) {
        for pic in self.pictures.values() {
            self.pending_output.push_str(&kitty::delete_image(pic.id));
        }
        self.pictures.clear();
    }

    /// Takes any escape sequences that must be written raw to the terminal.
    pub fn take_pending_output(&mut self) -> Option<String> {
        if self.pending_output.is_empty() {
            return None;
        }
        Some(std::mem::take(&mut self.pending_output))
    }

    /// Ensures every visible placement has a transmitted Kitty image and
    /// deletes images that scrolled out of view. No-op in Glyph mode.
    pub fn prepare_visible(&mut self, keys: &[MediaRenderKey]) {
        if self.mode != PictureMode::Kitty {
            return;
        }

        for key in keys {
            if key.path.is_empty() || key.width == 0 || key.height == 0 {
                continue;
            }
            if self.pictures.get(key).is_some_and(|p| p.transmitted) {
                continue;
            }
            if self.image(&key.path).is_none() {
                continue;
            }
            self.transmit_picture(key);
        }

        let stale: Vec<MediaRenderKey> = self
            .pictures
            .keys()
            .filter(|k| !keys.contains(k))
            .cloned()
            .collect();
        for key in stale {
            if let Some(pic) = self.pictures.remove(&key) {
                self.pending_output.push_str(&kitty::delete_image(pic.id));
            }
        }
    }

    /// Ages the caches: marks visible placements as recently used and evicts
    /// the least-recently-used entries beyond the cache caps.
    ///
    /// Recently viewed but momentarily hidden images stay warm, so moving
    /// between runs or toggling sibling panes does not re-decode.
    pub fn park(&mut self, keys: &[MediaRenderKey]) {
        self.use_tick += 1;
        for key in keys {
            if key.path.is_empty() || key.width == 0 || key.height == 0 {
                continue;
            }
            self.decoded_last_use
                .insert(key.path.clone(), self.use_tick);
            self.glyphs_last_use.insert(key.clone(), self.use_tick);
        }

        evict_lru(
            &mut self.decoded,
            &mut self.decoded_last_use,
            DECODED_CACHE_CAP,
        );
        evict_lru(&mut self.glyphs, &mut self.glyphs_last_use, GLYPH_CACHE_CAP);

        let tick = self.use_tick;
        let visible = &self.decoded_last_use;
        self.errors
            .retain(|path, _| visible.get(path).is_some_and(|&t| t == tick));
    }

    /// Draws the image at `path` into `area`.
    pub fn render(&mut self, path: &str, area: Rect, buf: &mut Buffer) {
        if area.width == 0 || area.height == 0 {
            return;
        }
        if path.is_empty() {
            render_placeholder(area, buf, "Missing image path");
            return;
        }

        let key = MediaRenderKey {
            path: path.to_string(),
            width: area.width,
            height: area.height,
        };

        if self.mode == PictureMode::Kitty
            && let Some(pic) = self.pictures.get(&key)
            && pic.transmitted
        {
            draw_kitty_placeholders(pic.id, area, buf);
            return;
        }
        // Transitional fallback until the image is transmitted.

        self.render_glyph(&key, area, buf);
    }

    fn render_glyph(&mut self, key: &MediaRenderKey, area: Rect, buf: &mut Buffer) {
        if self.glyphs.contains_key(key) {
            self.glyphs_last_use.insert(key.clone(), self.use_tick);
        } else {
            match self.image(&key.path) {
                Some(img) => {
                    let glyph = render_half_blocks(&img, key.width, key.height);
                    self.glyphs.insert(key.clone(), glyph);
                    self.glyphs_last_use.insert(key.clone(), self.use_tick);
                }
                None => {
                    let text = self
                        .errors
                        .get(&key.path)
                        .map(|e| e.text.clone())
                        .unwrap_or_default();
                    render_placeholder(area, buf, &truncate_value(&text, area.width as usize));
                    return;
                }
            }
        }

        let glyph = &self.glyphs[key];
        for y in 0..glyph.height.min(area.height) {
            for x in 0..glyph.width.min(area.width) {
                let (fg, bg) = glyph.cells[y as usize * glyph.width as usize + x as usize];
                let cell = &mut buf[(area.x + x, area.y + y)];
                match (fg, bg) {
                    (None, None) => {
                        cell.set_char(' ');
                    }
                    _ => {
                        cell.set_char('▄');
                        if let Some(fg) = fg {
                            cell.fg = fg;
                        }
                        if let Some(bg) = bg {
                            cell.bg = bg;
                        }
                    }
                }
            }
        }
    }

    /// Returns the decoded image for `path`, decoding and caching on demand.
    /// Failures are cached with a retry deadline.
    fn image(&mut self, path: &str) -> Option<RgbaImage> {
        if let Some(img) = self.decoded.get(path) {
            self.decoded_last_use
                .insert(path.to_string(), self.use_tick);
            return Some(img.clone());
        }
        if let Some(err) = self.errors.get(path)
            && err.at.elapsed() < MEDIA_ERROR_RETRY_AFTER
        {
            return None;
        }

        match image::open(path) {
            Ok(img) => {
                let img = img.to_rgba8();
                self.errors.remove(path);
                self.decoded.insert(path.to_string(), img.clone());
                self.decoded_last_use
                    .insert(path.to_string(), self.use_tick);
                Some(img)
            }
            Err(err) => {
                self.errors.insert(
                    path.to_string(),
                    RenderError {
                        text: err.to_string(),
                        at: Instant::now(),
                    },
                );
                None
            }
        }
    }

    fn transmit_picture(&mut self, key: &MediaRenderKey) {
        let Some(img) = self.image(&key.path) else {
            return;
        };

        let cell_w = if self.cell_pixel_w > 0 {
            self.cell_pixel_w
        } else {
            DEFAULT_CELL_PIXEL_W
        };
        let cell_h = if self.cell_pixel_h > 0 {
            self.cell_pixel_h
        } else {
            DEFAULT_CELL_PIXEL_H
        };
        let target_w = key.width as u32 * cell_w;
        let target_h = key.height as u32 * cell_h;

        let canvas = contain_image(&img, target_w, target_h);

        let mut png = Vec::new();
        if image::DynamicImage::ImageRgba8(canvas)
            .write_to(&mut Cursor::new(&mut png), image::ImageFormat::Png)
            .is_err()
        {
            return;
        }

        let id = match self.pictures.get(key) {
            Some(pic) => pic.id,
            None => next_media_kitty_id(),
        };
        self.pending_output
            .push_str(&kitty::encode_transmit(&png, id, key.width, key.height));
        self.pictures.insert(
            key.clone(),
            KittyPicture {
                id,
                transmitted: true,
            },
        );
    }
}

/// Evicts the least-recently-used entries of `map` down to `cap`.
fn evict_lru<K: std::hash::Hash + Eq + Clone, V>(
    map: &mut HashMap<K, V>,
    last_use: &mut HashMap<K, u64>,
    cap: usize,
) {
    if map.len() <= cap {
        return;
    }
    let mut entries: Vec<(K, u64)> = map
        .keys()
        .map(|k| (k.clone(), last_use.get(k).copied().unwrap_or(0)))
        .collect();
    entries.sort_by_key(|&(_, t)| t);
    for (key, _) in entries.into_iter().take(map.len() - cap) {
        map.remove(&key);
        last_use.remove(&key);
    }
}

/// Scales `img` to fit within (w, h) pixels preserving aspect ratio and
/// centers it on a transparent canvas of exactly (w, h).
fn contain_image(img: &RgbaImage, w: u32, h: u32) -> RgbaImage {
    let (sw, sh) = img.dimensions();
    if sw == 0 || sh == 0 || w == 0 || h == 0 {
        return RgbaImage::new(w.max(1), h.max(1));
    }

    // Inscribed rect: compare cross products to avoid floating point.
    let (iw, ih) = if (sw as u64) * (h as u64) >= (sh as u64) * (w as u64) {
        (w, ((sh as u64 * w as u64) / sw as u64).max(1) as u32)
    } else {
        (((sw as u64 * h as u64) / sh as u64).max(1) as u32, h)
    };

    let scaled = image::imageops::resize(img, iw, ih, FilterType::CatmullRom);
    let mut canvas = RgbaImage::new(w, h);
    let ox = (w.saturating_sub(iw)) / 2;
    let oy = (h.saturating_sub(ih)) / 2;
    image::imageops::overlay(&mut canvas, &scaled, ox as i64, oy as i64);
    canvas
}

/// Renders `img` as half-block cells: the image is contained (letterboxed)
/// into a (cols, rows*2) square-pixel grid, then each cell shows its top
/// pixel as the background and bottom pixel as the '▄' foreground.
fn render_half_blocks(img: &RgbaImage, cols: u16, rows: u16) -> GlyphImage {
    let grid_w = cols as u32;
    let grid_h = rows as u32 * 2;
    let canvas = contain_image(img, grid_w, grid_h);

    let mut cells = Vec::with_capacity(cols as usize * rows as usize);
    for y in 0..rows as u32 {
        for x in 0..grid_w {
            let top = canvas.get_pixel(x, y * 2);
            let bottom = canvas.get_pixel(x, y * 2 + 1);
            cells.push((pixel_color(bottom), pixel_color(top)));
        }
    }

    GlyphImage {
        width: cols,
        height: rows,
        cells,
    }
}

/// Converts a pixel to a terminal color, compositing partial transparency
/// over black. Fully transparent pixels map to `None` (terminal default).
fn pixel_color(p: &image::Rgba<u8>) -> Option<Color> {
    let [r, g, b, a] = p.0;
    if a == 0 {
        return None;
    }
    let blend = |c: u8| ((c as u16 * a as u16) / 255) as u8;
    Some(Color::Rgb(blend(r), blend(g), blend(b)))
}

/// Fills `area` with Kitty Unicode placeholders addressing image `id`.
fn draw_kitty_placeholders(id: u32, area: Rect, buf: &mut Buffer) {
    let fg = Color::Rgb(
        ((id >> 16) & 0xff) as u8,
        ((id >> 8) & 0xff) as u8,
        (id & 0xff) as u8,
    );
    for y in 0..area.height {
        let row_dia = kitty::diacritic(y as usize);
        for x in 0..area.width {
            let symbol: String = [kitty::PLACEHOLDER, row_dia, kitty::diacritic(x as usize)]
                .iter()
                .collect();
            buf[(area.x + x, area.y + y)].set_symbol(&symbol).set_fg(fg);
        }
    }
}

/// Renders a centered placeholder message.
pub fn render_placeholder(area: Rect, buf: &mut Buffer, msg: &str) {
    if area.width == 0 || area.height == 0 {
        return;
    }
    let msg = truncate_value(msg, area.width as usize);
    let w = unicode_width::UnicodeWidthStr::width(msg.as_str()) as u16;
    let x = area.x + (area.width.saturating_sub(w)) / 2;
    let y = area.y + area.height.saturating_sub(1) / 2;
    buf.set_stringn(
        x,
        y,
        &msg,
        area.width as usize,
        Style::new().fg(theme::COLOR_SUBTLE.color()),
    );
}
