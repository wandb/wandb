//! Image-to-terminal rendering for the media pane.
//!
//! Port of exactly the chain `mediapane.go` drives (all Go cites are
//! repo-relative under `core/vendor/` unless marked `mediapane.go`):
//!
//! - `github.com/NimbleMarkets/ntcharts/v2/picture/picture.go` — the
//!   `picture.Model` (Glyph half-blocks + Kitty graphics), constructed at
//!   `renderPictureGlyph` (mediapane.go:1465-1481, Glyph) and
//!   `preparePictureLocked` (mediapane.go:1420-1449, Kitty).
//! - `picture/fit.go` — `prepareSource`: maps the source image onto the
//!   `cols×rows` cell rectangle at `cellW×cellH` px/cell. Scaling filter at
//!   every fit.go call site (fit.go:66, :101, :152): **x/image/draw
//!   CatmullRom** (BC-spline B=0, C=0.5, support 2 — scale.go:183-188),
//!   composited with `draw.Over` onto a bg-filled `*image.RGBA`.
//! - `golang.org/x/image/draw` kernel scaler (impl.go:5545-6171) — the
//!   separable two-pass convolution behind `draw.CatmullRom.Scale`. Only
//!   the paths fit.go reaches: no masks, `sr == src.Bounds()`, dst
//!   `*image.RGBA`, ops Over/Src (Over is rewritten to Src for opaque
//!   sources, impl.go:5564-5566).
//! - `github.com/NimbleMarkets/pixterm/pkg/ansimage/ansimage.go` — the
//!   glyph rasterizer. `picture.Model.View` calls
//!   `NewScaledFromImage(rendered, rows*2, cols, bg, ScaleModeResize,
//!   NoDithering)` (picture.go:533-540): resize filter is pixterm's
//!   `defaultFilter = imaging.Box` (ansimage.go:580, applied
//!   ansimage.go:588), then half-block cells: upper pixel → background SGR,
//!   lower pixel → foreground SGR, rune `▄` U+2584 (ansimage.go:39,
//!   :483-509). The dithering modes (8×4 px block averaging + brightness
//!   glyphs, ansimage.go:174-215, :770-814) are ported for completeness but
//!   unreachable from leet (picture.go always passes `NoDithering`).
//! - `github.com/disintegration/imaging/resize.go` — ONLY the
//!   `Resize`+`Box` path pixterm invokes (`Fill`/`Fit`/nearest and the
//!   other 14 filters are not ported). Box kernel: support 0.5,
//!   `|x| <= 0.5 → 1.0` (resize.go:442-451).
//! - `picture/kitty.go`, `charmbracelet/x/ansi/kitty/{options,writer,
//!   graphics,encoder}.go` — the Kitty graphics APC encoder: chunked
//!   base64 `ESC _ G ... ESC \` sequences, virtual placement + Unicode
//!   placeholder grid, delete commands. Image IDs are allocated above
//!   10 000 mirroring `mediaKittyIDCounter` (mediapane.go:44-58).
//! - `picture/kitty_capability.go` — the process-wide capability state
//!   (`KittySupported`/`ForceKittyCapability`). The terminal probe
//!   (`QueryKittySupport`: env preflight → 1×1 `a=q` APC + timeout tick,
//!   kitty_capability.go:116-140) and the CSI 16 t cell-size query are
//!   NOT ported here: test mode suppresses all capability queries
//!   (testmode.go:20-21), and the interactive probe is app-shell wiring
//!   (Phase 5). Phase-5 NOTE (tracked in PARITY.md §2.6/MED-03): Kitty
//!   mode resolves through the probe plus TWO distinct env heuristics —
//!   picture's `kittyEnvSignal` (kitty_capability.go:142-176, the probe
//!   preflight) and mediapane's `terminalSignalsKittyGraphics`
//!   (mediapane.go:1234-1252, consulted by `ensureKittyGraphicsEnabled`
//!   mediapane.go:1223-1231 only after honoring an affirmative probe
//!   result). The heuristics differ — only mediapane's checks
//!   GHOSTTY_BIN_DIR and lowercases TERM_PROGRAM/TERM before matching —
//!   so the shell must port BOTH plus the probe, or terminals that only
//!   one path recognizes lose Kitty mode.
//!
//! PARITY: Go's Glyph path renders to an ANSI string with per-row SGR
//! dedup and a trailing `[0m`; this port renders to `ratatui` styled
//! lines ([`Text`]) — one [`Line`] per cell row, spans grouped by
//! identical (bg, fg) runs — the cell-grid normalization of the same
//! output. Go's "empty view" is the empty string; here it is a zero-line
//! `Text` (`lines.is_empty()`).
//!
//! PARITY: decoder-level divergences (recorded in PARITY.md §2.6; media
//! tiles are Tier-2):
//! - JPEG: Go scales `*image.YCbCr` inline with integer BT.601 math
//!   (impl.go:5854+), the `image` crate converts YCbCr→RGB during decode
//!   with its own rounding.
//! - Sources decoding to more than 8 bits per channel (16-bit PNG → Go
//!   `*image.NRGBA64`/`*image.Gray16`, and any other non-8-bit type):
//!   [`SourceImage::from_dynamic`] quantizes to RGBA8 before scaling,
//!   while Go's kernel scaler dispatches such images at full 16-bit
//!   precision through the `image.RGBA64Image` path (impl.go:5615-5617).
//!   Rendered half-block/Kitty pixels can differ by ±1 channel step.
//
// Derived from NimbleMarkets/ntcharts
// (https://github.com/NimbleMarkets/ntcharts), vendored at
// core/vendor/github.com/NimbleMarkets/ntcharts.
// ntcharts - Copyright (c) 2024-2026 Neomantra Corp.
// Used under the MIT License (see LICENSE.txt in the vendored tree).
//
// The half-block/dithering rasterizer derives from NimbleMarkets/pixterm
// (https://github.com/NimbleMarkets/pixterm), Copyright 2017 Eliuk Blau,
// vendored at core/vendor/github.com/NimbleMarkets/pixterm. That source is
// subject to the Mozilla Public License v2.0
// (https://mozilla.org/MPL/2.0/); this file's ansimage section is a port
// of that code and carries the same notice.
//
// The Box resize derives from disintegration/imaging
// (https://github.com/disintegration/imaging), Copyright (c) 2012-2020
// Grigory Dryapak, MIT License (see LICENSE in the vendored tree).
//
// The CatmullRom kernel scaler derives from golang.org/x/image/draw,
// Copyright 2015 The Go Authors, BSD-3-Clause (see the vendored LICENSE).
//
// The Kitty options/chunking derive from charmbracelet/x/ansi/kitty
// (https://github.com/charmbracelet/x), MIT License.

use std::sync::Arc;
use std::sync::atomic::{AtomicI32, AtomicI64, AtomicU64, Ordering};

use image::codecs::png::{CompressionType, FilterType, PngEncoder};
use image::{ExtendedColorType, ImageEncoder};
use ratatui::style::{Color, Style};
use ratatui::text::{Line, Span, Text};

// ---------------------------------------------------------------------------
// Colors and image buffers (Go image/color, image.RGBA / image.NRGBA).
// ---------------------------------------------------------------------------

/// A Go `color.Color` as its `RGBA()` result: alpha-premultiplied 16-bit
/// channels (the `image/color` interface contract).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct GoColor {
    pub r: u16,
    pub g: u16,
    pub b: u16,
    pub a: u16,
}

/// Go `color.Transparent` (`image/color`: `Alpha16{0}` → all-zero RGBA()).
pub const TRANSPARENT: GoColor = GoColor {
    r: 0,
    g: 0,
    b: 0,
    a: 0,
};

/// A decoded media image in Go `image.NRGBA` semantics: straight
/// (non-premultiplied) 8-bit RGBA, bounds anchored at (0,0).
///
/// PARITY: Go keeps the decoder's native type (`*image.NRGBA`,
/// `*image.RGBA`, `*image.Gray`, ...) and the x/image/draw `scaleX` has
/// per-type fast paths (impl.go:5778-5852). The per-pixel 16-bit
/// premultiplied values those paths compute are identical once the pixels
/// are normalized to straight alpha: RGBA with a=0xff gives `c*0x101`,
/// exactly the NRGBA premultiply `c*(0xff*0x101)/0xff`; Gray gives
/// `r=g=b=c*0x101`. That equivalence holds for 8-bit source types only —
/// see the module header for the JPEG/YCbCr and >8-bit (`RGBA64Image`
/// path) caveats.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SourceImage {
    pub width: usize,
    pub height: usize,
    /// RGBA8, straight alpha, row-major, stride = width*4.
    pub pix: Vec<u8>,
    /// Go `image.Opaque()` — true iff every alpha byte is 0xff. Consulted
    /// by the kernel scaler's Over→Src rewrite (impl.go:5564-5566).
    opaque: bool,
}

impl SourceImage {
    /// Builds from straight-alpha RGBA8 bytes (must be `width*height*4`).
    pub fn from_nrgba(width: usize, height: usize, pix: Vec<u8>) -> Self {
        assert_eq!(pix.len(), width * height * 4, "pix length mismatch");
        let opaque = pix.chunks_exact(4).all(|p| p[3] == 0xff);
        SourceImage {
            width,
            height,
            pix,
            opaque,
        }
    }

    /// Normalizes an `image` crate decode result (mediapane.go:1451-1463
    /// `loadMediaImage` decodes png/jpeg/gif; the media pane port does the
    /// file I/O and calls this).
    ///
    /// PARITY: `to_rgba8()` quantizes >8-bit decodes (16-bit PNG → Go
    /// `*image.NRGBA64`/`*image.Gray16`) before scaling; Go scales those
    /// at 16-bit precision (`image.RGBA64Image`, impl.go:5615-5617).
    /// Decoder-level divergence — see the module header and PARITY.md
    /// §2.6.
    pub fn from_dynamic(img: &image::DynamicImage) -> Self {
        let rgba = img.to_rgba8();
        Self::from_nrgba(
            rgba.width() as usize,
            rgba.height() as usize,
            rgba.into_raw(),
        )
    }

    fn is_empty(&self) -> bool {
        self.width == 0 || self.height == 0
    }
}

/// Go `*image.RGBA`: alpha-premultiplied 8-bit RGBA, bounds at (0,0).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GoRgbaImage {
    pub width: usize,
    pub height: usize,
    pub pix: Vec<u8>,
}

impl GoRgbaImage {
    fn new(width: usize, height: usize) -> Self {
        GoRgbaImage {
            width,
            height,
            pix: vec![0; width * height * 4],
        }
    }

    /// `draw.Draw(out, target, &image.Uniform{C: bg}, ..., draw.Src)` —
    /// image/draw's uniform-fill fast path writes `uint8(c >> 8)` of the
    /// 16-bit premultiplied channels.
    fn fill_uniform_src(&mut self, bg: GoColor) {
        let px = [
            (bg.r >> 8) as u8,
            (bg.g >> 8) as u8,
            (bg.b >> 8) as u8,
            (bg.a >> 8) as u8,
        ];
        for p in self.pix.chunks_exact_mut(4) {
            p.copy_from_slice(&px);
        }
    }
}

/// Go `*image.NRGBA` (straight alpha) — the output type of
/// `imaging.Resize` (resize.go:65).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct GoNrgbaImage {
    pub width: usize,
    pub height: usize,
    pub pix: Vec<u8>,
}

/// The result of `prepareSource` (fit.go:23-46). Usually a composited
/// `*image.RGBA`; `fillTo`'s fast path (fit.go:60-63) returns the source
/// image itself untouched, so downstream stages accept both.
#[derive(Debug, Clone)]
pub enum PreparedImage {
    /// fit.go compositing output (`image.NewRGBA` — premultiplied).
    Rgba(GoRgbaImage),
    /// fit.go:61-63 fast path: `return src`.
    Source(Arc<SourceImage>),
}

impl PreparedImage {
    fn width(&self) -> usize {
        match self {
            PreparedImage::Rgba(i) => i.width,
            PreparedImage::Source(i) => i.width,
        }
    }

    fn height(&self) -> usize {
        match self {
            PreparedImage::Rgba(i) => i.height,
            PreparedImage::Source(i) => i.height,
        }
    }
}

/// Integer rectangle, Go `image.Rectangle` (min inclusive, max exclusive).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
struct Rect {
    min_x: i64,
    min_y: i64,
    max_x: i64,
    max_y: i64,
}

impl Rect {
    fn new(x0: i64, y0: i64, x1: i64, y1: i64) -> Rect {
        Rect {
            min_x: x0,
            min_y: y0,
            max_x: x1,
            max_y: y1,
        }
    }

    fn dx(&self) -> i64 {
        self.max_x - self.min_x
    }

    fn dy(&self) -> i64 {
        self.max_y - self.min_y
    }

    fn empty(&self) -> bool {
        self.min_x >= self.max_x || self.min_y >= self.max_y
    }

    fn intersect(&self, o: Rect) -> Rect {
        let r = Rect {
            min_x: self.min_x.max(o.min_x),
            min_y: self.min_y.max(o.min_y),
            max_x: self.max_x.min(o.max_x),
            max_y: self.max_y.min(o.max_y),
        };
        if r.empty() { Rect::default() } else { r }
    }
}

// ---------------------------------------------------------------------------
// x/image/draw CatmullRom kernel scaler (scale.go:115-292, impl.go:5545-6171).
// Only the subset fit.go reaches: no masks, sr == src bounds, dst *image.RGBA.
// ---------------------------------------------------------------------------

/// Porter-Duff op, Go `draw.Op`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Op {
    Over,
    Src,
}

/// CatmullRom kernel support (scale.go:183 `&Kernel{2, ...}`).
const CATMULL_ROM_SUPPORT: f64 = 2.0;

/// scale.go:183-188. Keep the exact arithmetic shape — Go's `float64()`
/// casts exist to forbid FMA fusion; Rust never fuses implicitly.
fn catmull_rom_kernel(t: f64) -> f64 {
    if t < 1.0 {
        (1.5 * t - 2.5) * t * t + 1.0
    } else {
        (((-0.5 * t) + 2.5) * t - 4.0) * t + 2.0
    }
}

/// scale.go:210-214.
struct KSource {
    i: usize,
    j: usize,
    inv_total_weight: f64,
    inv_total_weight_ffff: f64,
}

/// scale.go:216-220.
struct KContrib {
    coord: i64,
    weight: f64,
}

/// scale.go:222-229.
struct Distrib {
    sources: Vec<KSource>,
    contribs: Vec<KContrib>,
}

/// scale.go:231-292 `newDistrib`, with the CatmullRom kernel inlined.
fn new_distrib(dw: i64, sw: i64) -> Distrib {
    let scale = sw as f64 / dw as f64;
    let mut half_width = CATMULL_ROM_SUPPORT;
    let mut kernel_arg_scale = 1.0;
    // When shrinking, broaden the effective kernel support so that we still
    // visit every source pixel.
    if scale > 1.0 {
        half_width *= scale;
        kernel_arg_scale = 1.0 / scale;
    }

    // (i, j, center) per destination column/row (Go temporarily stores the
    // center in invTotalWeight; a scratch tuple is clearer and identical).
    let mut ranges: Vec<(i64, i64, f64)> = Vec::with_capacity(dw as usize);
    for x in 0..dw {
        let center = (x as f64 + 0.5) * scale - 0.5;
        let mut i = (center - half_width).floor() as i64;
        if i < 0 {
            i = 0;
        }
        let mut j = (center + half_width).ceil() as i64;
        if j > sw {
            j = sw;
            if j < i {
                j = i;
            }
        }
        ranges.push((i, j, center));
    }

    let mut sources: Vec<KSource> = Vec::with_capacity(dw as usize);
    let mut contribs: Vec<KContrib> = Vec::new();
    for &(bi, bj, center) in &ranges {
        let mut total_weight = 0.0;
        let l = contribs.len();
        for coord in bi..bj {
            let t = ((center - coord as f64) * kernel_arg_scale).abs();
            if t >= CATMULL_ROM_SUPPORT {
                continue;
            }
            let weight = catmull_rom_kernel(t);
            if weight == 0.0 {
                continue;
            }
            total_weight += weight;
            contribs.push(KContrib { coord, weight });
        }
        let total_weight = 1.0 / total_weight;
        sources.push(KSource {
            i: l,
            j: contribs.len(),
            inv_total_weight: total_weight,
            inv_total_weight_ffff: total_weight / 65535.0,
        });
    }

    Distrib { sources, contribs }
}

/// scale.go:304-313 `ftou`: converts [0.0, 1.0] to [0, 0xffff].
fn ftou(f: f64) -> u16 {
    let i = (65535.0 * f + 0.5) as i64;
    if i > 0xffff {
        0xffff
    } else if i > 0 {
        i as u16
    } else {
        0
    }
}

/// `draw.CatmullRom.Scale(dst, dr, src, src.Bounds(), op, nil)` — the exact
/// subset fit.go reaches (impl.go:5545-5649 with nil opts/masks, `sr` equal
/// to the full source bounds).
fn catmull_rom_scale(dst: &mut GoRgbaImage, dr: Rect, src: &SourceImage, op: Op) {
    let (dw, dh) = (dr.dx(), dr.dy());
    let (sw, sh) = (src.width as i64, src.height as i64);

    // adr is the affected destination pixels (impl.go:5556-5563).
    let dst_bounds = Rect::new(0, 0, dst.width as i64, dst.height as i64);
    let adr = dst_bounds.intersect(dr);
    if adr.empty() || sw == 0 || sh == 0 {
        return;
    }
    // Make adr relative to dr.Min.
    let adr = Rect::new(
        adr.min_x - dr.min_x,
        adr.min_y - dr.min_y,
        adr.max_x - dr.min_x,
        adr.max_y - dr.min_y,
    );
    // impl.go:5564-5566: opaque sources compose identically under Src.
    let op = if op == Op::Over && src.opaque {
        Op::Src
    } else {
        op
    };

    let horizontal = new_distrib(dw, sw);
    let vertical = new_distrib(dh, sh);

    // scaleX distributes the source image's columns over the temporary
    // image; scaleY distributes the temporary image's rows over the
    // destination (impl.go:5573-5583).
    let mut tmp = vec![[0f64; 4]; (dw * sh) as usize];

    // scaleX_NRGBA (impl.go:5800-5825): 16-bit premultiply per pixel.
    let mut t = 0usize;
    for y in 0..sh as usize {
        for s in &horizontal.sources {
            let (mut pr, mut pg, mut pb, mut pa) = (0f64, 0f64, 0f64, 0f64);
            for c in &horizontal.contribs[s.i..s.j] {
                let pi = (y * src.width + c.coord as usize) * 4;
                let pau = u32::from(src.pix[pi + 3]) * 0x101;
                let pru = u32::from(src.pix[pi]) * pau / 0xff;
                let pgu = u32::from(src.pix[pi + 1]) * pau / 0xff;
                let pbu = u32::from(src.pix[pi + 2]) * pau / 0xff;
                pr += f64::from(pru) * c.weight;
                pg += f64::from(pgu) * c.weight;
                pb += f64::from(pbu) * c.weight;
                pa += f64::from(pau) * c.weight;
            }
            tmp[t] = [
                pr * s.inv_total_weight_ffff,
                pg * s.inv_total_weight_ffff,
                pb * s.inv_total_weight_ffff,
                pa * s.inv_total_weight_ffff,
            ];
            t += 1;
        }
    }

    // scaleY_RGBA_Over (impl.go:6104-6139) / scaleY_RGBA_Src
    // (impl.go:6141-6171).
    let stride = dst.width * 4;
    for dx in adr.min_x..adr.max_x {
        let mut d = ((dr.min_y + adr.min_y) as usize) * stride + ((dr.min_x + dx) as usize) * 4;
        for s in &vertical.sources[adr.min_y as usize..adr.max_y as usize] {
            let (mut pr, mut pg, mut pb, mut pa) = (0f64, 0f64, 0f64, 0f64);
            for c in &vertical.contribs[s.i..s.j] {
                let p = &tmp[(c.coord * dw + dx) as usize];
                pr += p[0] * c.weight;
                pg += p[1] * c.weight;
                pb += p[2] * c.weight;
                pa += p[3] * c.weight;
            }

            if pr > pa {
                pr = pa;
            }
            if pg > pa {
                pg = pa;
            }
            if pb > pa {
                pb = pa;
            }

            match op {
                Op::Over => {
                    let pr0 = u32::from(ftou(pr * s.inv_total_weight));
                    let pg0 = u32::from(ftou(pg * s.inv_total_weight));
                    let pb0 = u32::from(ftou(pb * s.inv_total_weight));
                    let pa0 = u32::from(ftou(pa * s.inv_total_weight));
                    let pa1 = (0xffff - pa0) * 0x101;
                    dst.pix[d] = ((u32::from(dst.pix[d]) * pa1 / 0xffff + pr0) >> 8) as u8;
                    dst.pix[d + 1] = ((u32::from(dst.pix[d + 1]) * pa1 / 0xffff + pg0) >> 8) as u8;
                    dst.pix[d + 2] = ((u32::from(dst.pix[d + 2]) * pa1 / 0xffff + pb0) >> 8) as u8;
                    dst.pix[d + 3] = ((u32::from(dst.pix[d + 3]) * pa1 / 0xffff + pa0) >> 8) as u8;
                }
                Op::Src => {
                    dst.pix[d] = (ftou(pr * s.inv_total_weight) >> 8) as u8;
                    dst.pix[d + 1] = (ftou(pg * s.inv_total_weight) >> 8) as u8;
                    dst.pix[d + 2] = (ftou(pb * s.inv_total_weight) >> 8) as u8;
                    dst.pix[d + 3] = (ftou(pa * s.inv_total_weight) >> 8) as u8;
                }
            }
            d += stride;
        }
    }
}

// ---------------------------------------------------------------------------
// picture/fit.go — prepareSource and the three fit modes.
// ---------------------------------------------------------------------------

/// FitMode controls how the source image is mapped onto the cell rectangle
/// (picture.go:35-43). The zero value is `Contain`.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FitMode {
    /// Preserve aspect ratio, letterbox (default).
    #[default]
    Contain,
    /// Stretch to fill the cell rectangle.
    Fill,
    /// Preserve aspect ratio, crop to fill.
    Cover,
}

/// FitAnchor controls which edge or center is preserved when a fit mode
/// must crop overflow; only `Cover` consults it (picture.go:45-56).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum FitAnchor {
    #[default]
    Center,
    Top,
    Bottom,
    Left,
    Right,
}

/// fit.go:23-46 `prepareSource`: returns an image of bounds
/// `(cols*cellW × rows*cellH)` with src mapped onto the target cell
/// rectangle according to fit, composited over bg with `draw.Over`.
/// Returns `None` for non-positive dims; a bg-filled target when src is
/// empty.
#[allow(clippy::too_many_arguments)] // Go signature (fit.go:23).
pub fn prepare_source(
    src: &Arc<SourceImage>,
    fit: FitMode,
    cols: i64,
    rows: i64,
    cell_w: i64,
    cell_h: i64,
    bg: GoColor,
    anchor: FitAnchor,
) -> Option<PreparedImage> {
    if cols <= 0 || rows <= 0 || cell_w <= 0 || cell_h <= 0 {
        return None;
    }
    let tw = cols * cell_w;
    let th = rows * cell_h;
    let target = Rect::new(0, 0, tw, th);

    if src.is_empty() {
        let mut out = GoRgbaImage::new(tw as usize, th as usize);
        out.fill_uniform_src(bg);
        return Some(PreparedImage::Rgba(out));
    }

    Some(match fit {
        FitMode::Fill => fill_to(src, target, bg),
        FitMode::Cover => cover_to(src, target, bg, anchor),
        // FitContain and any out-of-range value.
        FitMode::Contain => contain_to(src, target, bg),
    })
}

/// fit.go:50-53: whether bg has zero alpha.
fn bg_is_transparent(bg: GoColor) -> bool {
    bg.a == 0
}

/// fit.go:60-68 `fillTo`.
fn fill_to(src: &Arc<SourceImage>, target: Rect, bg: GoColor) -> PreparedImage {
    if bg_is_transparent(bg) && src.width as i64 == target.dx() && src.height as i64 == target.dy()
    {
        return PreparedImage::Source(src.clone());
    }
    let mut out = GoRgbaImage::new(target.dx() as usize, target.dy() as usize);
    out.fill_uniform_src(bg);
    catmull_rom_scale(&mut out, target, src, Op::Over);
    PreparedImage::Rgba(out)
}

/// fit.go:73-103 `containTo`.
fn contain_to(src: &Arc<SourceImage>, target: Rect, bg: GoColor) -> PreparedImage {
    let mut out = GoRgbaImage::new(target.dx() as usize, target.dy() as usize);
    out.fill_uniform_src(bg);

    let (tw, th) = (target.dx(), target.dy());
    let (sw, sh) = (src.width as i64, src.height as i64);

    // Inscribed rect: scale source to fit within target preserving AR.
    // Compare cross products to avoid floating point: sw/sh <=> tw/th.
    let (mut iw, mut ih);
    if sw * th >= sh * tw {
        // Source is "wider" relative to target; width-limited.
        iw = tw;
        ih = sh * tw / sw;
    } else {
        // Source is "taller" relative to target; height-limited.
        ih = th;
        iw = sw * th / sh;
    }
    if iw < 1 {
        iw = 1;
    }
    if ih < 1 {
        ih = 1;
    }
    let ox = (tw - iw) / 2;
    let oy = (th - ih) / 2;
    let dst = Rect::new(ox, oy, ox + iw, oy + ih);
    catmull_rom_scale(&mut out, dst, src, Op::Over);
    PreparedImage::Rgba(out)
}

/// fit.go:109-154 `coverTo`.
fn cover_to(src: &Arc<SourceImage>, target: Rect, bg: GoColor, anchor: FitAnchor) -> PreparedImage {
    let (tw, th) = (target.dx(), target.dy());
    let (sw, sh) = (src.width as i64, src.height as i64);

    // Circumscribed rect: scale source so it covers target preserving AR.
    let (mut cw, mut ch);
    if sw * th > sh * tw {
        // Width overflows: bind height to target, width grows past target.
        ch = th;
        cw = sw * th / sh;
    } else {
        // Height overflows (or equal): bind width.
        cw = tw;
        ch = sh * tw / sw;
    }
    if cw < 1 {
        cw = 1;
    }
    if ch < 1 {
        ch = 1;
    }
    let (ox, oy) = match anchor {
        FitAnchor::Top => ((tw - cw) / 2, 0),
        FitAnchor::Bottom => ((tw - cw) / 2, th - ch),
        FitAnchor::Left => (0, (th - ch) / 2),
        FitAnchor::Right => (tw - cw, (th - ch) / 2),
        FitAnchor::Center => ((tw - cw) / 2, (th - ch) / 2),
    };
    let dst = Rect::new(ox, oy, ox + cw, oy + ch);
    let mut out = GoRgbaImage::new(tw as usize, th as usize);
    out.fill_uniform_src(bg);
    catmull_rom_scale(&mut out, dst, src, Op::Over);
    PreparedImage::Rgba(out)
}

// ---------------------------------------------------------------------------
// disintegration/imaging — Resize with the Box filter (the only filter
// pixterm invokes: ansimage.go:580 `defaultFilter = imaging.Box`).
// ---------------------------------------------------------------------------

/// Box filter support (resize.go:442-451).
const BOX_SUPPORT: f64 = 0.5;

/// Box kernel (resize.go:444-450).
fn box_kernel(x: f64) -> f64 {
    if x.abs() <= 0.5 { 1.0 } else { 0.0 }
}

/// resize.go:8-11.
struct IndexWeight {
    index: usize,
    weight: f64,
}

/// resize.go:13-55 `precomputeWeights` with the Box filter.
fn precompute_weights(dst_size: usize, src_size: usize) -> Vec<Vec<IndexWeight>> {
    let du = src_size as f64 / dst_size as f64;
    let scale = if du < 1.0 { 1.0 } else { du };
    let ru = (scale * BOX_SUPPORT).ceil();

    let mut out = Vec::with_capacity(dst_size);
    for v in 0..dst_size {
        let fu = (v as f64 + 0.5) * du - 0.5;

        let mut begin = (fu - ru).ceil() as i64;
        if begin < 0 {
            begin = 0;
        }
        let mut end = (fu + ru).floor() as i64;
        if end > src_size as i64 - 1 {
            end = src_size as i64 - 1;
        }

        let mut sum = 0.0;
        let mut tmp: Vec<IndexWeight> = Vec::new();
        for u in begin..=end {
            let w = box_kernel((u as f64 - fu) / scale);
            if w != 0.0 {
                sum += w;
                tmp.push(IndexWeight {
                    index: u as usize,
                    weight: w,
                });
            }
        }
        if sum != 0.0 {
            for iw in &mut tmp {
                iw.weight /= sum;
            }
        }
        out.push(tmp);
    }
    out
}

/// A source the imaging scanner can read (scanner.go:30-285). Only the
/// pixel formats this pipeline produces: `*image.RGBA` (premultiplied —
/// fit.go output) and `*image.NRGBA` (straight — `fillTo` fast path and
/// intermediate resize passes).
enum ScanSrc<'a> {
    Rgba(&'a GoRgbaImage),
    Nrgba {
        width: usize,
        height: usize,
        pix: &'a [u8],
    },
}

impl<'a> ScanSrc<'a> {
    fn from_prepared(img: &'a PreparedImage) -> ScanSrc<'a> {
        match img {
            PreparedImage::Rgba(i) => ScanSrc::Rgba(i),
            PreparedImage::Source(i) => ScanSrc::Nrgba {
                width: i.width,
                height: i.height,
                pix: &i.pix,
            },
        }
    }

    /// scanner.go `scan`: the given rectangular region into straight-alpha
    /// RGBA8 bytes.
    fn scan(&self, x1: usize, y1: usize, x2: usize, y2: usize, dst: &mut [u8]) {
        match *self {
            // scanner.go:71-104 (*image.RGBA): unpremultiply.
            ScanSrc::Rgba(img) => {
                let mut j = 0;
                for y in y1..y2 {
                    let mut i = (y * img.width + x1) * 4;
                    for _ in x1..x2 {
                        let a = img.pix[i + 3];
                        let d = &mut dst[j..j + 4];
                        match a {
                            0 => {
                                d[0] = 0;
                                d[1] = 0;
                                d[2] = 0;
                                d[3] = a;
                            }
                            0xff => {
                                d.copy_from_slice(&img.pix[i..i + 4]);
                            }
                            _ => {
                                let a16 = u32::from(a);
                                d[0] = (u32::from(img.pix[i]) * 0xff / a16) as u8;
                                d[1] = (u32::from(img.pix[i + 1]) * 0xff / a16) as u8;
                                d[2] = (u32::from(img.pix[i + 2]) * 0xff / a16) as u8;
                                d[3] = a;
                            }
                        }
                        j += 4;
                        i += 4;
                    }
                }
            }
            // scanner.go:32-53 (*image.NRGBA): straight copy.
            ScanSrc::Nrgba { width, pix, .. } => {
                let size = (x2 - x1) * 4;
                let mut j = 0;
                for y in y1..y2 {
                    let i = (y * width + x1) * 4;
                    dst[j..j + size].copy_from_slice(&pix[i..i + size]);
                    j += size;
                }
            }
        }
    }

    fn width(&self) -> usize {
        match *self {
            ScanSrc::Rgba(img) => img.width,
            ScanSrc::Nrgba { width, .. } => width,
        }
    }

    fn height(&self) -> usize {
        match *self {
            ScanSrc::Rgba(img) => img.height,
            ScanSrc::Nrgba { height, .. } => height,
        }
    }
}

/// utils.go:48-57 `clamp`: rounds and clamps an f64 into u8.
fn imaging_clamp(x: f64) -> u8 {
    let v = (x + 0.5) as i64;
    if v > 255 {
        255
    } else if v > 0 {
        v as u8
    } else {
        0
    }
}

/// resize.go:57-105 `Resize` with the Box filter. Serial (Go's `parallel`
/// helper is row-independent; output is identical).
fn imaging_resize(img: &PreparedImage, width: i64, height: i64) -> GoNrgbaImage {
    let empty = GoNrgbaImage {
        width: 0,
        height: 0,
        pix: Vec::new(),
    };
    let (mut dst_w, mut dst_h) = (width, height);
    if dst_w < 0 || dst_h < 0 {
        return empty;
    }
    if dst_w == 0 && dst_h == 0 {
        return empty;
    }

    let src_w = img.width() as i64;
    let src_h = img.height() as i64;
    if src_w <= 0 || src_h <= 0 {
        return empty;
    }

    // If new width or height is 0 then preserve aspect ratio, minimum 1px.
    if dst_w == 0 {
        let tmp_w = dst_h as f64 * src_w as f64 / src_h as f64;
        dst_w = 1.0f64.max((tmp_w + 0.5).floor()) as i64;
    }
    if dst_h == 0 {
        let tmp_h = dst_w as f64 * src_h as f64 / src_w as f64;
        dst_h = 1.0f64.max((tmp_h + 0.5).floor()) as i64;
    }

    // Box.Support (0.5) > 0, so imaging's nearest-neighbor special case
    // (resize.go:90-93) is unreachable and not ported.
    let src = ScanSrc::from_prepared(img);
    if src_w != dst_w && src_h != dst_h {
        let horizontal = resize_horizontal(&src, dst_w as usize);
        let hsrc = ScanSrc::Nrgba {
            width: horizontal.width,
            height: horizontal.height,
            pix: &horizontal.pix,
        };
        return resize_vertical(&hsrc, dst_h as usize);
    }
    if src_w != dst_w {
        return resize_horizontal(&src, dst_w as usize);
    }
    if src_h != dst_h {
        return resize_vertical(&src, dst_h as usize);
    }
    imaging_clone(&src)
}

/// resize.go:107-140 `resizeHorizontal`.
fn resize_horizontal(src: &ScanSrc, width: usize) -> GoNrgbaImage {
    let src_w = src.width();
    let src_h = src.height();
    let mut dst = GoNrgbaImage {
        width,
        height: src_h,
        pix: vec![0; width * src_h * 4],
    };
    let weights = precompute_weights(width, src_w);
    let mut scan_line = vec![0u8; src_w * 4];
    for y in 0..src_h {
        src.scan(0, y, src_w, y + 1, &mut scan_line);
        let j0 = y * width * 4;
        for (x, ws) in weights.iter().enumerate() {
            let (mut r, mut g, mut b, mut a) = (0f64, 0f64, 0f64, 0f64);
            for w in ws {
                let i = w.index * 4;
                let s = &scan_line[i..i + 4];
                // PARITY: Go (gc) on arm64 — the oracle platform — rewrites
                // each `acc += x*y` below into FMADDD (`aw` stays a rounded
                // product because it has multiple uses, but every
                // accumulation is fused against the original operands), so
                // the four accumulators must be `f64::mul_add` to stay
                // bit-exact. Fractional Box weights otherwise drift by ±1
                // per channel: e.g. six alphas summing to 735 with weight
                // 1/6 give exactly 122.5 fused (→ clamp 123) but
                // 122.49999999999999 unfused (→ 122). Go on amd64 without
                // GOAMD64>=v3 does NOT fuse and would match the unfused
                // form; this port pins the arm64 behavior. The
                // `imaging_clamp(x * a_inv)` sites below stay unfused —
                // verified: only the accumulators fuse.
                let aw = f64::from(s[3]) * w.weight;
                r = f64::from(s[0]).mul_add(aw, r);
                g = f64::from(s[1]).mul_add(aw, g);
                b = f64::from(s[2]).mul_add(aw, b);
                a = f64::from(s[3]).mul_add(w.weight, a);
            }
            if a != 0.0 {
                let a_inv = 1.0 / a;
                let j = j0 + x * 4;
                dst.pix[j] = imaging_clamp(r * a_inv);
                dst.pix[j + 1] = imaging_clamp(g * a_inv);
                dst.pix[j + 2] = imaging_clamp(b * a_inv);
                dst.pix[j + 3] = imaging_clamp(a);
            }
        }
    }
    dst
}

/// resize.go:142-174 `resizeVertical`.
fn resize_vertical(src: &ScanSrc, height: usize) -> GoNrgbaImage {
    let src_w = src.width();
    let src_h = src.height();
    let mut dst = GoNrgbaImage {
        width: src_w,
        height,
        pix: vec![0; src_w * height * 4],
    };
    let weights = precompute_weights(height, src_h);
    let mut scan_line = vec![0u8; src_h * 4];
    for x in 0..src_w {
        src.scan(x, 0, x + 1, src_h, &mut scan_line);
        for (y, ws) in weights.iter().enumerate() {
            let (mut r, mut g, mut b, mut a) = (0f64, 0f64, 0f64, 0f64);
            for w in ws {
                let i = w.index * 4;
                let s = &scan_line[i..i + 4];
                // PARITY: fused accumulators matching Go-arm64 FMA — see
                // the identical loop in resize_horizontal for the full
                // note.
                let aw = f64::from(s[3]) * w.weight;
                r = f64::from(s[0]).mul_add(aw, r);
                g = f64::from(s[1]).mul_add(aw, g);
                b = f64::from(s[2]).mul_add(aw, b);
                a = f64::from(s[3]).mul_add(w.weight, a);
            }
            if a != 0.0 {
                let a_inv = 1.0 / a;
                let j = (y * src_w + x) * 4;
                dst.pix[j] = imaging_clamp(r * a_inv);
                dst.pix[j + 1] = imaging_clamp(g * a_inv);
                dst.pix[j + 2] = imaging_clamp(b * a_inv);
                dst.pix[j + 3] = imaging_clamp(a);
            }
        }
    }
    dst
}

/// tools.go:29 `Clone` (via the scanner): the whole source as NRGBA.
fn imaging_clone(src: &ScanSrc) -> GoNrgbaImage {
    let (w, h) = (src.width(), src.height());
    let mut pix = vec![0u8; w * h * 4];
    src.scan(0, 0, w, h, &mut pix);
    GoNrgbaImage {
        width: w,
        height: h,
        pix,
    }
}

// ---------------------------------------------------------------------------
// pixterm ansimage — the half-block / dithering rasterizer.
// ---------------------------------------------------------------------------

/// Unicode Block Element character used to represent lower pixel in
/// terminal row (ansimage.go:39).
pub const LOWER_HALF_BLOCK: char = '\u{2584}';

// Unicode Block Element characters used to represent dithering
// (ansimage.go:43-46).
const FULL_BLOCK: &str = "\u{2588}";
const DARK_SHADE_BLOCK: &str = "\u{2593}";
const MEDIUM_SHADE_BLOCK: &str = "\u{2592}";
const LIGHT_SHADE_BLOCK: &str = "\u{2591}";

/// ANSImage dithering modes (ansimage.go:58-66). leet only reaches
/// `NoDithering` (picture.go:539); the others are ported for completeness.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DitheringMode {
    NoDithering,
    DitheringWithBlocks,
    DitheringWithChars,
}

/// ANSImage block size in pixels, dithering mode (ansimage.go:69-72).
pub const BLOCK_SIZE_Y: usize = 8;
pub const BLOCK_SIZE_X: usize = 4;

/// ansimage.go:108-111.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
struct AnsiPixelData {
    brightness: u8,
    r: u8,
    g: u8,
    b: u8,
}

/// ansimage.go:74-92 error subset reachable from this port.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AnsImageError {
    /// `ErrHeightNonMoT`: height must be a multiple of two.
    HeightNonMoT,
    /// `ErrInvalidBoundsMoT`: height or width must be >= 2.
    InvalidBoundsMoT,
}

/// ANSImage represents an image encoded as terminal cells
/// (ansimage.go:113-122; `maxprocs` is not ported — rendering here is
/// deterministic and serial).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct AnsImage {
    h: usize,
    w: usize,
    bg_r: u8,
    bg_g: u8,
    bg_b: u8,
    dithering: DitheringMode,
    pixmap: Vec<AnsiPixelData>,
}

/// ansimage.go:550-571 `New`.
fn ansimage_new(
    h: usize,
    w: usize,
    bg: GoColor,
    dm: DitheringMode,
) -> Result<AnsImage, AnsImageError> {
    if dm == DitheringMode::NoDithering && !h.is_multiple_of(2) {
        return Err(AnsImageError::HeightNonMoT);
    }
    if h < 2 || w < 2 {
        return Err(AnsImageError::InvalidBoundsMoT);
    }
    // PARITY: Go truncates the 16-bit RGBA() channels with uint8(r) — the
    // LOW byte, not r>>8 (ansimage.go:559-565). 0xffff → 0xff, but e.g.
    // 0x1234 → 0x34. Port the truncation.
    Ok(AnsImage {
        h,
        w,
        bg_r: bg.r as u8,
        bg_g: bg.g as u8,
        bg_b: bg.b as u8,
        dithering: dm,
        pixmap: vec![AnsiPixelData::default(); h * w],
    })
}

/// ansimage.go:582-598 `NewScaledFromImage`, `ScaleModeResize` only — the
/// only mode picture.go reaches (picture.go:538). `y` is the pixel height
/// (`rows*2`), `x` the pixel width (`cols`).
pub fn ansimage_new_scaled_from_image(
    img: &PreparedImage,
    y: i64,
    x: i64,
    bg: GoColor,
    dm: DitheringMode,
) -> Result<AnsImage, AnsImageError> {
    let resized = imaging_resize(img, x, y);
    create_ansimage(&resized, bg, dm)
}

/// ansimage.go:255-267 `rgbaComponent`: un-premultiplies one channel.
fn rgba_component(c: u8, a: u8) -> u8 {
    if a == 0 || c == 0 {
        return 0;
    }
    if a == 0xff {
        return c;
    }
    let v = u32::from(c) * 0xff / u32::from(a);
    if v > 0xff { 0xff } else { v as u8 }
}

/// ansimage.go:269-274 `luminance`: ITU-R BT.601 luma.
fn luminance(r: u8, g: u8, b: u8) -> u8 {
    ((299 * u32::from(r) + 587 * u32::from(g) + 114 * u32::from(b)) / 1000) as u8
}

/// ansimage.go:174-215 `ditherBlock`.
fn dither_block(brightness: u8, mode: DitheringMode) -> &'static str {
    match mode {
        DitheringMode::DitheringWithBlocks => match brightness {
            b if b > 204 => FULL_BLOCK,
            b if b > 152 => DARK_SHADE_BLOCK,
            b if b > 100 => MEDIUM_SHADE_BLOCK,
            b if b > 48 => LIGHT_SHADE_BLOCK,
            _ => " ",
        },
        DitheringMode::DitheringWithChars => match brightness {
            b if b > 230 => "#",
            b if b > 207 => "&",
            b if b > 184 => "$",
            b if b > 161 => "X",
            b if b > 138 => "x",
            b if b > 115 => "=",
            b if b > 92 => "+",
            b if b > 69 => ";",
            b if b > 46 => ":",
            b if b > 23 => ".",
            _ => " ",
        },
        // Go panics on NoDithering here; unreachable by construction (the
        // render path never calls ditherBlock in NoDithering mode).
        DitheringMode::NoDithering => unreachable!("ditherBlock in NoDithering mode"),
    }
}

/// ansimage.go:695-817 `createANSImage`. The input is always the
/// `*image.NRGBA` produced by `imaging.Resize` (ansimage.go:588).
fn create_ansimage(
    img: &GoNrgbaImage,
    bg: GoColor,
    dm: DitheringMode,
) -> Result<AnsImage, AnsImageError> {
    // Compositing (ansimage.go:710-721): only if background color has no
    // transparency. Either way the pixel buffer becomes premultiplied
    // `*image.RGBA` bytes via image/draw's NRGBA fast paths.
    let mut rgba_out = vec![0u8; img.pix.len()];
    // Go compares the uint32 RGBA() alpha with `>= 0xffff`
    // (ansimage.go:710); with 16-bit channels that is equality.
    if bg.a == 0xffff {
        // draw.Draw(rgbaOut, bounds, uniform(bg), Src) then
        // draw.Draw(rgbaOut, bounds, img, Over) — drawNRGBAOver math.
        let bpx = [
            (bg.r >> 8) as u8,
            (bg.g >> 8) as u8,
            (bg.b >> 8) as u8,
            (bg.a >> 8) as u8,
        ];
        for (d, s) in rgba_out.chunks_exact_mut(4).zip(img.pix.chunks_exact(4)) {
            d.copy_from_slice(&bpx);
            let sa = u32::from(s[3]) * 0x101;
            let sr = u32::from(s[0]) * sa / 0xff;
            let sg = u32::from(s[1]) * sa / 0xff;
            let sb = u32::from(s[2]) * sa / 0xff;
            let a1 = (0xffff - sa) * 0x101;
            d[0] = ((u32::from(d[0]) * a1 / 0xffff + sr) >> 8) as u8;
            d[1] = ((u32::from(d[1]) * a1 / 0xffff + sg) >> 8) as u8;
            d[2] = ((u32::from(d[2]) * a1 / 0xffff + sb) >> 8) as u8;
            d[3] = ((u32::from(d[3]) * a1 / 0xffff + sa) >> 8) as u8;
        }
    } else {
        // draw.Draw(rgbaOut, bounds, img, Src) — drawNRGBASrc premultiply.
        for (d, s) in rgba_out.chunks_exact_mut(4).zip(img.pix.chunks_exact(4)) {
            let sa = u32::from(s[3]) * 0x101;
            d[0] = ((u32::from(s[0]) * sa / 0xff) >> 8) as u8;
            d[1] = ((u32::from(s[1]) * sa / 0xff) >> 8) as u8;
            d[2] = ((u32::from(s[2]) * sa / 0xff) >> 8) as u8;
            d[3] = (sa >> 8) as u8;
        }
    }

    let src_w = img.width;
    let src_h = img.height;
    let (h, w);
    if dm == DitheringMode::NoDithering {
        // round up to even number of rows to avoid truncation.
        h = (src_h + 1) & !1;
        w = src_w;
    } else {
        h = src_h / BLOCK_SIZE_Y; // always sets 1 ANSIPixel block...
        w = src_w / BLOCK_SIZE_X; // per 8x4 real pixels --> with dithering
    }

    let mut ansimage = ansimage_new(h, w, bg, dm)?;

    if dm == DitheringMode::NoDithering {
        for y in 0..h {
            let dst_offset = y * w;
            if y < src_h {
                let mut src_offset = y * src_w * 4;
                for x in 0..w {
                    ansimage.pixmap[dst_offset + x] = AnsiPixelData {
                        brightness: 0,
                        r: rgba_out[src_offset],
                        g: rgba_out[src_offset + 1],
                        b: rgba_out[src_offset + 2],
                    };
                    src_offset += 4;
                }
            } else {
                // Pad with background color.
                for x in 0..w {
                    ansimage.pixmap[dst_offset + x] = AnsiPixelData {
                        brightness: 0,
                        r: ansimage.bg_r,
                        g: ansimage.bg_g,
                        b: ansimage.bg_b,
                    };
                }
            }
        }
    } else {
        const PIXEL_COUNT: u32 = (BLOCK_SIZE_Y * BLOCK_SIZE_X) as u32;

        for y in 0..h {
            for x in 0..w {
                let (mut sum_r, mut sum_g, mut sum_b, mut sum_bri) = (0u32, 0u32, 0u32, 0u32);
                for dy in 0..BLOCK_SIZE_Y {
                    let py = BLOCK_SIZE_Y * y + dy;
                    let mut offset = (py * src_w + BLOCK_SIZE_X * x) * 4;

                    for _ in 0..BLOCK_SIZE_X {
                        let mut r = rgba_out[offset];
                        let mut g = rgba_out[offset + 1];
                        let mut b = rgba_out[offset + 2];
                        let a = rgba_out[offset + 3];
                        offset += 4;

                        if a != 0xff {
                            r = rgba_component(r, a);
                            g = rgba_component(g, a);
                            b = rgba_component(b, a);
                        }

                        sum_r += u32::from(r);
                        sum_g += u32::from(g);
                        sum_b += u32::from(b);
                        sum_bri += u32::from(luminance(r, g, b));
                    }
                }

                ansimage.pixmap[y * w + x] = AnsiPixelData {
                    brightness: ((sum_bri + PIXEL_COUNT / 2) / PIXEL_COUNT) as u8,
                    r: ((sum_r + PIXEL_COUNT / 2) / PIXEL_COUNT) as u8,
                    g: ((sum_g + PIXEL_COUNT / 2) / PIXEL_COUNT) as u8,
                    b: ((sum_b + PIXEL_COUNT / 2) / PIXEL_COUNT) as u8,
                };
            }
        }
    }

    Ok(ansimage)
}

impl AnsImage {
    /// ansimage.go:277-279.
    pub fn height(&self) -> usize {
        self.h
    }

    /// ansimage.go:282-284.
    pub fn width(&self) -> usize {
        self.w
    }

    /// `RenderExt(false, false)` (ansimage.go:362-380) as styled lines: one
    /// [`Line`] per output cell row.
    ///
    /// PARITY: Go emits per-row SGR sequences deduplicated against the
    /// previous cell and a trailing `[0m\n` (ansimage.go:483-535); the span
    /// model's equivalent is one span per run of identical (bg, fg). The
    /// per-row trailing newline (stripped again by picture.go:548) has no
    /// span equivalent.
    pub fn render_text(&self) -> Text<'static> {
        // nRows is the number of output cell rows; for NoDithering each
        // cell row consumes two pixmap rows (upper + lower).
        let n_rows = if self.dithering == DitheringMode::NoDithering {
            self.h / 2
        } else {
            self.h
        };
        let mut lines = Vec::with_capacity(n_rows);
        for r in 0..n_rows {
            if self.dithering == DitheringMode::NoDithering {
                lines.push(self.no_dithering_row(r));
            } else {
                lines.push(self.dithering_row(r));
            }
        }
        Text::from(lines)
    }

    /// ansimage.go:483-509 `appendNoDitheringRow`: upper pixel → bg SGR,
    /// lower pixel → fg SGR, `▄` per cell.
    fn no_dithering_row(&self, r: usize) -> Line<'static> {
        let py = 2 * r;
        let upper_row = py * self.w;
        let lower_row = (py + 1) * self.w;

        let mut spans: Vec<Span<'static>> = Vec::new();
        let mut run = String::new();
        let mut run_style: Option<Style> = None;
        for x in 0..self.w {
            let u = self.pixmap[upper_row + x];
            let l = self.pixmap[lower_row + x];
            let style = Style::default()
                .bg(Color::Rgb(u.r, u.g, u.b))
                .fg(Color::Rgb(l.r, l.g, l.b));
            if run_style != Some(style) {
                if let Some(s) = run_style {
                    spans.push(Span::styled(std::mem::take(&mut run), s));
                }
                run_style = Some(style);
            }
            run.push(LOWER_HALF_BLOCK);
        }
        if let Some(s) = run_style {
            spans.push(Span::styled(run, s));
        }
        Line::from(spans)
    }

    /// ansimage.go:515-535 `appendDitheringRow` (disableBgColor=false — the
    /// only form picture.View reaches): constant bg, per-pixel fg, glyph
    /// from `ditherBlock`.
    fn dithering_row(&self, r: usize) -> Line<'static> {
        let row = r * self.w;
        let bg = Color::Rgb(self.bg_r, self.bg_g, self.bg_b);

        let mut spans: Vec<Span<'static>> = Vec::new();
        let mut run = String::new();
        let mut run_style: Option<Style> = None;
        for x in 0..self.w {
            let p = self.pixmap[row + x];
            let style = Style::default().bg(bg).fg(Color::Rgb(p.r, p.g, p.b));
            if run_style != Some(style) {
                if let Some(s) = run_style {
                    spans.push(Span::styled(std::mem::take(&mut run), s));
                }
                run_style = Some(style);
            }
            run.push_str(dither_block(p.brightness, self.dithering));
        }
        if let Some(s) = run_style {
            spans.push(Span::styled(run, s));
        }
        Line::from(spans)
    }
}

// ---------------------------------------------------------------------------
// picture/kitty_capability.go — process-wide Kitty capability state.
// The terminal probe (QueryKittySupport) is NOT ported here; see the module
// header. mediapane's `ensureKittyGraphicsEnabled` (mediapane.go:1223-1231)
// honors an affirmative probe result first, then falls back to its own env
// heuristic `terminalSignalsKittyGraphics` (mediapane.go:1234-1252 — NOT
// the same set as picture's `kittyEnvSignal`: only mediapane's checks
// GHOSTTY_BIN_DIR and lowercases TERM_PROGRAM/TERM) and calls
// [`force_kitty_capability`]; those port with media_pane, the probe with
// the Phase-5 app shell. All three are required — see the module header
// and PARITY.md §2.6/MED-03.
// ---------------------------------------------------------------------------

/// Kitty graphics capability of the host terminal
/// (kitty_capability.go:19-38). Process-wide: a property of the tty, not of
/// any individual [`Model`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(i32)]
pub enum KittyCapability {
    /// Before any probe/force: Toggle into Kitty is BLOCKED.
    Unknown = 0,
    /// The terminal speaks the protocol.
    Supported = 1,
    /// Probe timed out / no positive signal.
    Unsupported = 2,
}

/// kitty_capability.go:52 `kittyCap` — CONCURRENCY.md §2.6 keeps
/// package-global atomics as statics (Relaxed).
static KITTY_CAP: AtomicI32 = AtomicI32::new(0);

/// kitty_capability.go:70-72 `KittySupported`.
pub fn kitty_supported() -> KittyCapability {
    match KITTY_CAP.load(Ordering::Relaxed) {
        1 => KittyCapability::Supported,
        2 => KittyCapability::Unsupported,
        _ => KittyCapability::Unknown,
    }
}

/// kitty_capability.go:80-82 `ForceKittyCapability`.
pub fn force_kitty_capability(c: KittyCapability) {
    KITTY_CAP.store(c as i32, Ordering::Relaxed);
}

// ---------------------------------------------------------------------------
// Kitty graphics APC encoder.
// Port of picture/kitty.go + charmbracelet/x/ansi/kitty
// {options,writer,graphics,encoder}.go — pure byte-string generation.
// ---------------------------------------------------------------------------

/// kitty/graphics.go:9 — maximum chunk size for the (base64) image data.
pub const MAX_CHUNK_SIZE: usize = 1024 * 4;

/// kitty/graphics.go:13 — Unicode placeholder for virtual placements.
pub const PLACEHOLDER: char = '\u{10EEEE}';

// Graphics image formats (kitty/graphics.go:16-25).
const FORMAT_RGBA: i64 = 32;
const FORMAT_PNG: i64 = 100;

// Transmission types (kitty/graphics.go:33-47).
const TRANSMISSION_DIRECT: u8 = b'd';
const TRANSMISSION_FILE: u8 = b'f';

// Action types (kitty/graphics.go:50-67).
const ACTION_TRANSMIT: u8 = b't';
const ACTION_TRANSMIT_AND_PUT: u8 = b'T';
const ACTION_FRAME: u8 = b'f';

// Delete types (kitty/graphics.go:70-103).
const DELETE_ALL: u8 = b'a';

// Compression (kitty/graphics.go:28-30).
const COMPRESSION_ZLIB: u8 = b'z';

/// Kitty Graphics Protocol options (kitty/options.go:18-147). Fields keep
/// Go's zero-value defaulting: `options()` fills format/action/delete/
/// transmission when zero.
#[derive(Debug, Clone, Default)]
pub struct KittyOptions {
    pub action: u8,
    pub quite: u8,
    pub id: i64,
    pub placement_id: i64,
    pub number: i64,
    pub format: i64,
    pub image_width: i64,
    pub image_height: i64,
    pub compression: u8,
    pub transmission: u8,
    pub file: String,
    pub size: i64,
    pub offset: i64,
    pub chunk: bool,
    pub x: i64,
    pub y: i64,
    pub z: i64,
    pub width: i64,
    pub height: i64,
    pub offset_x: i64,
    pub offset_y: i64,
    pub columns: i64,
    pub rows: i64,
    pub virtual_placement: bool,
    pub do_not_move_cursor: bool,
    pub parent_id: i64,
    pub parent_placement_id: i64,
    pub delete: u8,
    pub delete_resources: bool,
}

impl KittyOptions {
    /// kitty/options.go:150-282 `Options`: the ordered key=value list.
    /// (Go mutates the receiver's zero fields to defaults; this port
    /// applies the defaults to locals — same emitted list.)
    pub fn options(&self) -> Vec<String> {
        let format = if self.format == 0 {
            FORMAT_RGBA
        } else {
            self.format
        };
        let action = if self.action == 0 {
            ACTION_TRANSMIT
        } else {
            self.action
        };
        let delete = if self.delete == 0 {
            DELETE_ALL
        } else {
            self.delete
        };
        let transmission = if self.transmission == 0 {
            if !self.file.is_empty() {
                TRANSMISSION_FILE
            } else {
                TRANSMISSION_DIRECT
            }
        } else {
            self.transmission
        };

        let mut opts: Vec<String> = Vec::new();
        if format != FORMAT_RGBA {
            opts.push(format!("f={format}"));
        }
        if self.quite > 0 {
            opts.push(format!("q={}", self.quite));
        }
        if self.id > 0 {
            opts.push(format!("i={}", self.id));
        }
        if self.placement_id > 0 {
            opts.push(format!("p={}", self.placement_id));
        }
        if self.number > 0 {
            opts.push(format!("I={}", self.number));
        }
        if self.image_width > 0 {
            opts.push(format!("s={}", self.image_width));
        }
        if self.image_height > 0 {
            opts.push(format!("v={}", self.image_height));
        }
        if transmission != TRANSMISSION_DIRECT {
            opts.push(format!("t={}", transmission as char));
        }
        if self.size > 0 {
            opts.push(format!("S={}", self.size));
        }
        if self.offset > 0 {
            opts.push(format!("O={}", self.offset));
        }
        if self.compression == COMPRESSION_ZLIB {
            opts.push(format!("o={}", self.compression as char));
        }
        if self.virtual_placement {
            opts.push("U=1".to_string());
        }
        if self.do_not_move_cursor {
            opts.push("C=1".to_string());
        }
        if self.parent_id > 0 {
            opts.push(format!("P={}", self.parent_id));
        }
        if self.parent_placement_id > 0 {
            opts.push(format!("Q={}", self.parent_placement_id));
        }
        if self.x > 0 {
            opts.push(format!("x={}", self.x));
        }
        if self.y > 0 {
            opts.push(format!("y={}", self.y));
        }
        if self.z > 0 {
            opts.push(format!("z={}", self.z));
        }
        if self.width > 0 {
            opts.push(format!("w={}", self.width));
        }
        if self.height > 0 {
            opts.push(format!("h={}", self.height));
        }
        if self.offset_x > 0 {
            opts.push(format!("X={}", self.offset_x));
        }
        if self.offset_y > 0 {
            opts.push(format!("Y={}", self.offset_y));
        }
        if self.columns > 0 {
            opts.push(format!("c={}", self.columns));
        }
        if self.rows > 0 {
            opts.push(format!("r={}", self.rows));
        }
        if delete != DELETE_ALL || self.delete_resources {
            let mut da = delete;
            if self.delete_resources {
                da -= b' '; // to uppercase
            }
            opts.push(format!("d={}", da as char));
        }
        if action != ACTION_TRANSMIT {
            opts.push(format!("a={}", action as char));
        }
        opts
    }
}

/// x/ansi graphics.go:52-62 `KittyGraphics`: `ESC _ G <opts> [; payload]
/// ESC \`.
fn kitty_graphics(payload: &str, opts: &[String]) -> String {
    let mut buf = String::from("\x1b_G");
    buf.push_str(&opts.join(","));
    if !payload.is_empty() {
        buf.push(';');
        buf.push_str(payload);
    }
    buf.push_str("\x1b\\");
    buf
}

/// kitty/writer.go:164-187 `buildChunkOptions`.
fn build_chunk_options(o: &KittyOptions, is_first_chunk: bool, is_last_chunk: bool) -> Vec<String> {
    let mut opts = if is_first_chunk {
        o.options()
    } else {
        // These options are allowed in subsequent chunks.
        let mut v = Vec::new();
        if o.quite > 0 {
            v.push(format!("q={}", o.quite));
        }
        if o.action == ACTION_FRAME {
            v.push("a=f".to_string());
        }
        v
    };

    if !is_first_chunk || !is_last_chunk {
        // We don't need to encode the (m=) option when we only have one
        // chunk.
        if is_last_chunk {
            opts.push("m=0".to_string());
        } else {
            opts.push("m=1".to_string());
        }
    }
    opts
}

/// The chunking loop of kitty/writer.go:119-160 `EncodeGraphics` over an
/// already base64-encoded payload, `o.chunk` respected.
///
/// PARITY: Go reads MaxChunkSize bytes with io.ReadFull; a payload that is
/// an exact multiple of the chunk size therefore emits a trailing EMPTY
/// `m=0` chunk (`ESC _ G q=2,m=0 ESC \` with no `;`) — ported as-is.
pub fn encode_graphics_chunks(payload: &str, o: &KittyOptions) -> String {
    // If not chunking, write all at once (writer.go:120-123).
    if !o.chunk {
        return kitty_graphics(payload, &o.options());
    }

    let bytes = payload.as_bytes();
    let mut out = String::new();
    let mut off = 0usize;
    let mut is_first_chunk = true;
    // Full chunks (io.ReadFull succeeds only when MaxChunkSize bytes
    // remain).
    while bytes.len() - off >= MAX_CHUNK_SIZE {
        let chunk = &payload[off..off + MAX_CHUNK_SIZE];
        let opts = build_chunk_options(o, is_first_chunk, false);
        out.push_str(&kitty_graphics(chunk, &opts));
        is_first_chunk = false;
        off += MAX_CHUNK_SIZE;
    }
    // Write the last chunk (possibly empty).
    let opts = build_chunk_options(o, is_first_chunk, true);
    out.push_str(&kitty_graphics(&payload[off..], &opts));
    out
}

/// Standard base64 with padding (Go `encoding/base64.StdEncoding`).
/// Hand-rolled: the workspace takes no base64 crate dependency.
fn base64_std(data: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    let mut chunks = data.chunks_exact(3);
    for c in &mut chunks {
        let n = (u32::from(c[0]) << 16) | (u32::from(c[1]) << 8) | u32::from(c[2]);
        out.push(ALPHABET[(n >> 18) as usize & 63] as char);
        out.push(ALPHABET[(n >> 12) as usize & 63] as char);
        out.push(ALPHABET[(n >> 6) as usize & 63] as char);
        out.push(ALPHABET[n as usize & 63] as char);
    }
    match chunks.remainder() {
        [a] => {
            let n = u32::from(*a) << 16;
            out.push(ALPHABET[(n >> 18) as usize & 63] as char);
            out.push(ALPHABET[(n >> 12) as usize & 63] as char);
            out.push_str("==");
        }
        [a, b] => {
            let n = (u32::from(*a) << 16) | (u32::from(*b) << 8);
            out.push(ALPHABET[(n >> 18) as usize & 63] as char);
            out.push(ALPHABET[(n >> 12) as usize & 63] as char);
            out.push(ALPHABET[(n >> 6) as usize & 63] as char);
            out.push('=');
        }
        _ => {}
    }
    out
}

/// PNG-encodes a prepared image with straight-alpha pixel content matching
/// Go's `png.Encode` of the same image.
///
/// PARITY: the PNG *byte stream* differs from Go's encoder (deflate
/// implementation details); the decoded pixel content is identical — Go's
/// encoder unpremultiplies `*image.RGBA` through `color.NRGBAModel`,
/// mirrored here. The Phase-7 protocol test compares decoded pixels.
/// The compression *class* must match though: Go's `png.Encode` uses
/// default-level deflate with adaptive per-row filtering, while this
/// crate's `PngEncoder::new` default is `CompressionType::Fast` — 4-7x
/// larger payloads for the same pixels (measured on the 555x320 media
/// fixture frames under a scripted kitty PTY: Go 12,913/20,716 bytes vs
/// fast-mode 86,817/88,514), retransmitted on every Kitty prepare and
/// paid again over ssh/leet-remote. `Default`+`Adaptive` restores Go's
/// wire cost.
fn png_encode_prepared(img: &PreparedImage) -> Option<Vec<u8>> {
    let (w, h) = (img.width(), img.height());
    if w == 0 || h == 0 {
        return None;
    }
    let pix: Vec<u8> = match img {
        PreparedImage::Source(s) => s.pix.clone(),
        PreparedImage::Rgba(r) => {
            // color.NRGBAModel over RGBA() values (image/color/color.go):
            // straight = premul16 * 0xffff / alpha16, then >> 8.
            let mut out = Vec::with_capacity(r.pix.len());
            for p in r.pix.chunks_exact(4) {
                let a = p[3];
                match a {
                    0xff => out.extend_from_slice(p),
                    0 => out.extend_from_slice(&[0, 0, 0, 0]),
                    _ => {
                        let a16 = u32::from(a) * 0x101;
                        for &c in &p[..3] {
                            let c16 = u32::from(c) * 0x101;
                            out.push(((c16 * 0xffff / a16) >> 8) as u8);
                        }
                        out.push(a);
                    }
                }
            }
            out
        }
    };
    let mut buf = Vec::new();
    PngEncoder::new_with_quality(&mut buf, CompressionType::Default, FilterType::Adaptive)
        .write_image(&pix, w as u32, h as u32, ExtendedColorType::Rgba8)
        .ok()?;
    Some(buf)
}

/// picture/kitty.go:17-34 `buildKittyAPC`: encodes img as a Kitty graphics
/// APC sequence at the given (cols, rows) cell rectangle. The caller is
/// responsible for sizing img to `(cols*cellPixelW × rows*cellPixelH)` —
/// do that via [`prepare_source`]. Returns `""` on encode failure, as Go.
pub fn build_kitty_apc(img: &PreparedImage, id: i64, cols: i64, rows: i64) -> String {
    let Some(png) = png_encode_prepared(img) else {
        return String::new();
    };
    let opts = KittyOptions {
        action: ACTION_TRANSMIT_AND_PUT,
        transmission: TRANSMISSION_DIRECT,
        format: FORMAT_PNG,
        id,
        columns: cols,
        rows,
        virtual_placement: true,
        quite: 2,
        chunk: true,
        ..KittyOptions::default()
    };
    encode_graphics_chunks(&base64_std(&png), &opts)
}

/// picture/kitty.go:36-60 `buildKittyGrid`: the Unicode-placeholder grid
/// that resolves to the virtual placement at `image_id`. A pure function of
/// (cols, rows, image_id).
///
/// PARITY: Go emits `ESC[38;2;r;g;bm` + placeholders + `ESC[39m` per row,
/// newline-separated; here each row is a [`Line`] with one fg-styled span
/// (the reset is implicit in the span model).
pub fn build_kitty_grid(cols: i64, rows: i64, image_id: i64) -> Text<'static> {
    let r = ((image_id >> 16) & 0xff) as u8;
    let g = ((image_id >> 8) & 0xff) as u8;
    let b = (image_id & 0xff) as u8;
    let style = Style::default().fg(Color::Rgb(r, g, b));

    let mut lines = Vec::with_capacity(rows.max(0) as usize);
    for y in 0..rows {
        let row_dia = diacritic(y);
        let mut content = String::new();
        for x in 0..cols {
            content.push(PLACEHOLDER);
            content.push(row_dia);
            content.push(diacritic(x));
        }
        lines.push(Line::from(Span::styled(content, style)));
    }
    Text::from(lines)
}

/// picture/kitty.go:62-64 `kittyDeleteImage`.
pub fn kitty_delete_image(id: i64) -> String {
    format!("\x1b_Ga=d,d=I,i={id},q=2\x1b\\")
}

/// kitty/graphics.go:105-112 `Diacritic`: the diacritic rune at the given
/// index; out-of-bounds returns the first.
pub fn diacritic(i: i64) -> char {
    if i < 0 || i >= DIACRITICS.len() as i64 {
        return DIACRITICS[0];
    }
    DIACRITICS[i as usize]
}

/// kitty/graphics.go:114-414 — the row/column diacritics table from the
/// Kitty graphics protocol (297 entries).
const DIACRITICS: [char; 297] = [
    '\u{0305}',
    '\u{030D}',
    '\u{030E}',
    '\u{0310}',
    '\u{0312}',
    '\u{033D}',
    '\u{033E}',
    '\u{033F}',
    '\u{0346}',
    '\u{034A}',
    '\u{034B}',
    '\u{034C}',
    '\u{0350}',
    '\u{0351}',
    '\u{0352}',
    '\u{0357}',
    '\u{035B}',
    '\u{0363}',
    '\u{0364}',
    '\u{0365}',
    '\u{0366}',
    '\u{0367}',
    '\u{0368}',
    '\u{0369}',
    '\u{036A}',
    '\u{036B}',
    '\u{036C}',
    '\u{036D}',
    '\u{036E}',
    '\u{036F}',
    '\u{0483}',
    '\u{0484}',
    '\u{0485}',
    '\u{0486}',
    '\u{0487}',
    '\u{0592}',
    '\u{0593}',
    '\u{0594}',
    '\u{0595}',
    '\u{0597}',
    '\u{0598}',
    '\u{0599}',
    '\u{059C}',
    '\u{059D}',
    '\u{059E}',
    '\u{059F}',
    '\u{05A0}',
    '\u{05A1}',
    '\u{05A8}',
    '\u{05A9}',
    '\u{05AB}',
    '\u{05AC}',
    '\u{05AF}',
    '\u{05C4}',
    '\u{0610}',
    '\u{0611}',
    '\u{0612}',
    '\u{0613}',
    '\u{0614}',
    '\u{0615}',
    '\u{0616}',
    '\u{0617}',
    '\u{0657}',
    '\u{0658}',
    '\u{0659}',
    '\u{065A}',
    '\u{065B}',
    '\u{065D}',
    '\u{065E}',
    '\u{06D6}',
    '\u{06D7}',
    '\u{06D8}',
    '\u{06D9}',
    '\u{06DA}',
    '\u{06DB}',
    '\u{06DC}',
    '\u{06DF}',
    '\u{06E0}',
    '\u{06E1}',
    '\u{06E2}',
    '\u{06E4}',
    '\u{06E7}',
    '\u{06E8}',
    '\u{06EB}',
    '\u{06EC}',
    '\u{0730}',
    '\u{0732}',
    '\u{0733}',
    '\u{0735}',
    '\u{0736}',
    '\u{073A}',
    '\u{073D}',
    '\u{073F}',
    '\u{0740}',
    '\u{0741}',
    '\u{0743}',
    '\u{0745}',
    '\u{0747}',
    '\u{0749}',
    '\u{074A}',
    '\u{07EB}',
    '\u{07EC}',
    '\u{07ED}',
    '\u{07EE}',
    '\u{07EF}',
    '\u{07F0}',
    '\u{07F1}',
    '\u{07F3}',
    '\u{0816}',
    '\u{0817}',
    '\u{0818}',
    '\u{0819}',
    '\u{081B}',
    '\u{081C}',
    '\u{081D}',
    '\u{081E}',
    '\u{081F}',
    '\u{0820}',
    '\u{0821}',
    '\u{0822}',
    '\u{0823}',
    '\u{0825}',
    '\u{0826}',
    '\u{0827}',
    '\u{0829}',
    '\u{082A}',
    '\u{082B}',
    '\u{082C}',
    '\u{082D}',
    '\u{0951}',
    '\u{0953}',
    '\u{0954}',
    '\u{0F82}',
    '\u{0F83}',
    '\u{0F86}',
    '\u{0F87}',
    '\u{135D}',
    '\u{135E}',
    '\u{135F}',
    '\u{17DD}',
    '\u{193A}',
    '\u{1A17}',
    '\u{1A75}',
    '\u{1A76}',
    '\u{1A77}',
    '\u{1A78}',
    '\u{1A79}',
    '\u{1A7A}',
    '\u{1A7B}',
    '\u{1A7C}',
    '\u{1B6B}',
    '\u{1B6D}',
    '\u{1B6E}',
    '\u{1B6F}',
    '\u{1B70}',
    '\u{1B71}',
    '\u{1B72}',
    '\u{1B73}',
    '\u{1CD0}',
    '\u{1CD1}',
    '\u{1CD2}',
    '\u{1CDA}',
    '\u{1CDB}',
    '\u{1CE0}',
    '\u{1DC0}',
    '\u{1DC1}',
    '\u{1DC3}',
    '\u{1DC4}',
    '\u{1DC5}',
    '\u{1DC6}',
    '\u{1DC7}',
    '\u{1DC8}',
    '\u{1DC9}',
    '\u{1DCB}',
    '\u{1DCC}',
    '\u{1DD1}',
    '\u{1DD2}',
    '\u{1DD3}',
    '\u{1DD4}',
    '\u{1DD5}',
    '\u{1DD6}',
    '\u{1DD7}',
    '\u{1DD8}',
    '\u{1DD9}',
    '\u{1DDA}',
    '\u{1DDB}',
    '\u{1DDC}',
    '\u{1DDD}',
    '\u{1DDE}',
    '\u{1DDF}',
    '\u{1DE0}',
    '\u{1DE1}',
    '\u{1DE2}',
    '\u{1DE3}',
    '\u{1DE4}',
    '\u{1DE5}',
    '\u{1DE6}',
    '\u{1DFE}',
    '\u{20D0}',
    '\u{20D1}',
    '\u{20D4}',
    '\u{20D5}',
    '\u{20D6}',
    '\u{20D7}',
    '\u{20DB}',
    '\u{20DC}',
    '\u{20E1}',
    '\u{20E7}',
    '\u{20E9}',
    '\u{20F0}',
    '\u{2CEF}',
    '\u{2CF0}',
    '\u{2CF1}',
    '\u{2DE0}',
    '\u{2DE1}',
    '\u{2DE2}',
    '\u{2DE3}',
    '\u{2DE4}',
    '\u{2DE5}',
    '\u{2DE6}',
    '\u{2DE7}',
    '\u{2DE8}',
    '\u{2DE9}',
    '\u{2DEA}',
    '\u{2DEB}',
    '\u{2DEC}',
    '\u{2DED}',
    '\u{2DEE}',
    '\u{2DEF}',
    '\u{2DF0}',
    '\u{2DF1}',
    '\u{2DF2}',
    '\u{2DF3}',
    '\u{2DF4}',
    '\u{2DF5}',
    '\u{2DF6}',
    '\u{2DF7}',
    '\u{2DF8}',
    '\u{2DF9}',
    '\u{2DFA}',
    '\u{2DFB}',
    '\u{2DFC}',
    '\u{2DFD}',
    '\u{2DFE}',
    '\u{2DFF}',
    '\u{A66F}',
    '\u{A67C}',
    '\u{A67D}',
    '\u{A6F0}',
    '\u{A6F1}',
    '\u{A8E0}',
    '\u{A8E1}',
    '\u{A8E2}',
    '\u{A8E3}',
    '\u{A8E4}',
    '\u{A8E5}',
    '\u{A8E6}',
    '\u{A8E7}',
    '\u{A8E8}',
    '\u{A8E9}',
    '\u{A8EA}',
    '\u{A8EB}',
    '\u{A8EC}',
    '\u{A8ED}',
    '\u{A8EE}',
    '\u{A8EF}',
    '\u{A8F0}',
    '\u{A8F1}',
    '\u{AAB0}',
    '\u{AAB2}',
    '\u{AAB3}',
    '\u{AAB7}',
    '\u{AAB8}',
    '\u{AABE}',
    '\u{AABF}',
    '\u{AAC1}',
    '\u{FE20}',
    '\u{FE21}',
    '\u{FE22}',
    '\u{FE23}',
    '\u{FE24}',
    '\u{FE25}',
    '\u{FE26}',
    '\u{10A0F}',
    '\u{10A38}',
    '\u{1D185}',
    '\u{1D186}',
    '\u{1D187}',
    '\u{1D188}',
    '\u{1D189}',
    '\u{1D1AA}',
    '\u{1D1AB}',
    '\u{1D1AC}',
    '\u{1D1AD}',
    '\u{1D242}',
    '\u{1D243}',
    '\u{1D244}',
];

// ---------------------------------------------------------------------------
// Media Kitty image ID allocation (mediapane.go:44-58).
// ---------------------------------------------------------------------------

/// Kitty graphics image IDs live in a terminal-wide namespace. Media
/// panes allocate from a process-wide counter starting well above
/// ntcharts' default ID so picture models never overwrite each other
/// (mediapane.go:47-52).
pub const MEDIA_KITTY_ID_BASE: i64 = 10_000;

/// mediapane.go:55 `mediaKittyIDCounter` — kept as a static atomic
/// (CONCURRENCY.md S14).
static MEDIA_KITTY_ID_COUNTER: AtomicI64 = AtomicI64::new(0);

/// mediapane.go:57-59 `nextMediaKittyID` (Go `Add(1)` returns the new
/// value; the first ID is 10001).
pub fn next_media_kitty_id() -> i64 {
    MEDIA_KITTY_ID_BASE + (MEDIA_KITTY_ID_COUNTER.fetch_add(1, Ordering::Relaxed) + 1)
}

// ---------------------------------------------------------------------------
// picture.Model (picture/picture.go).
// ---------------------------------------------------------------------------

/// PictureMode selects how images are rendered (picture.go:27-33).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub enum PictureMode {
    /// Universal half-block ANSI.
    #[default]
    Glyph,
    /// High-res Kitty graphics protocol.
    Kitty,
}

/// picture.go:58.
pub const DEFAULT_KITTY_ID: i64 = 43;

// Sensible defaults for terminal cell pixel size (picture.go:64-67).
const DEFAULT_CELL_PIXEL_W: i64 = 8;
const DEFAULT_CELL_PIXEL_H: i64 = 16;

/// Config configures a [`Model`] at construction (picture.go:69-105).
/// Zero-value fields are filled with defaults by [`Model::new_with_config`]
/// (Go `nil` Background ≙ the [`TRANSPARENT`] default here).
#[derive(Debug, Clone, Default)]
pub struct Config {
    /// Default 43.
    pub kitty_id: i64,
    /// Default transparent (no compositing).
    pub background: GoColor,
    /// How the source maps onto the cell rectangle. Zero value FitContain.
    pub fit: FitMode,
    /// Which edge survives a crop; only FitCover consults it.
    pub anchor: FitAnchor,
    /// Terminal cell pixel dimensions, used in Kitty mode to pre-scale the
    /// source to the c×r cell rectangle. Default 8×16.
    pub cell_pixel_width: i64,
    pub cell_pixel_height: i64,
    /// Scales the encoded Kitty image's per-cell pixel resolution; (0, 1]
    /// shrink the transmitted bitmap. Out-of-range clamps to 1.0.
    pub kitty_resolution_factor: f64,
}

/// The five-tuple of "what dimensions and fit mode does the Kitty image
/// currently on screen occupy" (picture.go:146-155). Zero value means "no
/// image currently placed at this Model's kittyID".
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct KittyGeom {
    cols: i64,
    rows: i64,
    cell_pixel_w: i64,
    cell_pixel_h: i64,
    fit: FitMode,
    anchor: FitAnchor,
}

/// picture.go:157 `nextModelID`.
static NEXT_MODEL_ID: AtomicU64 = AtomicU64::new(0);

/// KittyFrameMsg carries the result of building a Kitty APC payload + grid
/// for a specific generation of the Model (picture/messages.go:1-17).
// PartialEq/Default: carried by `Event::KittyFrame` (event.rs), whose enum
// derives PartialEq and whose tests need a zero-value sample.
#[derive(Debug, Clone, Default, PartialEq)]
pub struct KittyFrameMsg {
    model_id: u64,
    pub id: i64,
    pub seq: u64,
    pub apc: String,
    pub grid: Text<'static>,
}

/// applyKittyGridMsg (picture.go:392-410): the second half of the
/// KittyFrameMsg pipeline — the grid is applied only after the APC bytes
/// are on the wire, so placeholder cells never resolve to the previous
/// image.
#[derive(Debug, Clone)]
pub struct ApplyKittyGridMsg {
    model_id: u64,
    cols: i64,
    rows: i64,
    kitty_id: i64,
    grid: Text<'static>,
}

/// The `tea.Cmd`s the Go Model returns, as data (CONCURRENCY.md §2.7: the
/// media pane maps these onto app `Command`s).
#[derive(Debug, Clone)]
pub enum PictureCmd {
    /// `tea.Raw(...)`: raw bytes for the terminal (Kitty delete
    /// sequences).
    Raw(String),
    /// `renderCmd`'s deferred closure (picture.go:563-608): run
    /// [`KittyRenderRequest::run`] on an effect thread and feed the
    /// resulting frame back through [`Model::on_kitty_frame`].
    Render(KittyRenderRequest),
}

/// The by-value captures of Go's renderCmd closure (picture.go:571-587).
#[derive(Debug, Clone)]
pub struct KittyRenderRequest {
    img: Arc<SourceImage>,
    bg: GoColor,
    model_id: u64,
    id: i64,
    cols: i64,
    rows: i64,
    seq: u64,
    fit: FitMode,
    anchor: FitAnchor,
    cpw: i64,
    cph: i64,
    prev_geom: KittyGeom,
}

impl KittyRenderRequest {
    /// The closure body (picture.go:588-607) minus `yieldToJS` (WASM
    /// only). Returns `None` when prepareSource fails, as Go returns nil.
    pub fn run(&self) -> Option<KittyFrameMsg> {
        let prepared = prepare_source(
            &self.img,
            self.fit,
            self.cols,
            self.rows,
            self.cpw,
            self.cph,
            self.bg,
            self.anchor,
        )?;
        let mut apc = build_kitty_apc(&prepared, self.id, self.cols, self.rows);
        let curr_geom = KittyGeom {
            cols: self.cols,
            rows: self.rows,
            cell_pixel_w: self.cpw,
            cell_pixel_h: self.cph,
            fit: self.fit,
            anchor: self.anchor,
        };
        if self.prev_geom != KittyGeom::default() && self.prev_geom != curr_geom {
            apc = format!("{}{}", kitty_delete_image(self.id), apc);
        }
        let grid = build_kitty_grid(self.cols, self.rows, self.id);
        Some(KittyFrameMsg {
            model_id: self.model_id,
            id: self.id,
            seq: self.seq,
            apc,
            grid,
        })
    }
}

/// Model renders an image as half-blocks or Kitty graphics
/// (picture.go:107-144). The Model has no notion of where images come
/// from; callers feed it via [`Model::set_image`].
#[derive(Debug, Clone)]
pub struct Model {
    model_id: u64,
    mode: PictureMode,
    cols: i64,
    rows: i64,

    img: Option<Arc<SourceImage>>,
    seq: u64,

    glyph_cache: Option<Text<'static>>,
    glyph_key: String,

    kitty_grid: Option<Text<'static>>,

    kitty_id: i64,
    background: GoColor,
    fit: FitMode,
    anchor: FitAnchor,

    cell_pixel_w: i64,
    cell_pixel_h: i64,

    kitty_resolution_factor: f64,

    /// The geometry of the most recently *applied* KittyFrame — see
    /// picture.go:134-143 (some terminals don't honor a c/r change for an
    /// on-screen virtual placement, so renderCmd prepends a delete when
    /// this differs).
    last_rendered_geom: KittyGeom,
}

impl Default for Model {
    fn default() -> Self {
        Model::new()
    }
}

impl Model {
    /// picture.go:159-162 `New`: a Model with default Config — the exact
    /// construction `renderPictureGlyph` uses (mediapane.go:1473).
    pub fn new() -> Model {
        Model::new_with_config(Config::default())
    }

    /// picture.go:164-193 `NewWithConfig` — the construction
    /// `preparePictureLocked` uses (mediapane.go:1425-1429).
    pub fn new_with_config(cfg: Config) -> Model {
        let kitty_id = if cfg.kitty_id <= 0 {
            DEFAULT_KITTY_ID
        } else {
            cfg.kitty_id
        };
        let cell_pixel_w = if cfg.cell_pixel_width <= 0 {
            DEFAULT_CELL_PIXEL_W
        } else {
            cfg.cell_pixel_width
        };
        let cell_pixel_h = if cfg.cell_pixel_height <= 0 {
            DEFAULT_CELL_PIXEL_H
        } else {
            cfg.cell_pixel_height
        };
        let kitty_resolution_factor =
            if cfg.kitty_resolution_factor <= 0.0 || cfg.kitty_resolution_factor > 1.0 {
                1.0
            } else {
                cfg.kitty_resolution_factor
            };
        Model {
            model_id: NEXT_MODEL_ID.fetch_add(1, Ordering::Relaxed) + 1,
            mode: PictureMode::Glyph,
            cols: 0,
            rows: 0,
            img: None,
            seq: 0,
            glyph_cache: None,
            glyph_key: String::new(),
            kitty_grid: None,
            kitty_id,
            background: cfg.background,
            fit: cfg.fit,
            anchor: cfg.anchor,
            cell_pixel_w,
            cell_pixel_h,
            kitty_resolution_factor,
            last_rendered_geom: KittyGeom::default(),
        }
    }

    /// picture.go:205-223 `SetImage`. Pass `None` to clear.
    pub fn set_image(&mut self, img: Option<Arc<SourceImage>>) -> Option<PictureCmd> {
        let prev = self.img.take();
        self.img = img;
        self.seq += 1;
        self.invalidate_glyph();

        if self.img.is_none() {
            self.invalidate_kitty();
            if self.mode == PictureMode::Kitty && prev.is_some() {
                // Image gone from the terminal: clear the geom snapshot so
                // the next render is treated as a fresh placement.
                self.last_rendered_geom = KittyGeom::default();
                return Some(PictureCmd::Raw(kitty_delete_image(self.kitty_id)));
            }
            return None;
        }
        self.render_cmd()
    }

    /// picture.go:230-246 `SetSize`: rendering dimensions in terminal
    /// cells; negatives clamp to 0.
    pub fn set_size(&mut self, cols: i64, rows: i64) -> Option<PictureCmd> {
        let cols = cols.max(0);
        let rows = rows.max(0);
        if cols == self.cols && rows == self.rows {
            return None;
        }
        self.cols = cols;
        self.rows = rows;
        self.seq += 1;
        self.invalidate_glyph();
        self.invalidate_kitty();
        self.render_cmd()
    }

    /// picture.go:257-287 `Toggle`. Entering Kitty requires the
    /// process-wide capability to be affirmatively Supported; both Unknown
    /// and Unsupported block.
    pub fn toggle(&mut self) -> Option<PictureCmd> {
        let prev = self.mode;
        if self.mode == PictureMode::Glyph {
            if kitty_supported() != KittyCapability::Supported {
                return None;
            }
            self.mode = PictureMode::Kitty;
        } else {
            self.mode = PictureMode::Glyph;
        }
        self.seq += 1;

        if prev == PictureMode::Kitty && self.img.is_some() {
            // Leaving Kitty: the placeholder grid would resolve to nothing
            // now; clear it and the geom snapshot.
            self.invalidate_kitty();
            self.last_rendered_geom = KittyGeom::default();
            return Some(PictureCmd::Raw(kitty_delete_image(self.kitty_id)));
        }
        self.render_cmd()
    }

    /// picture.go:290.
    pub fn mode(&self) -> PictureMode {
        self.mode
    }

    /// picture.go:293.
    pub fn fit(&self) -> FitMode {
        self.fit
    }

    /// picture.go:296.
    pub fn anchor(&self) -> FitAnchor {
        self.anchor
    }

    /// The Model's Kitty image ID.
    pub fn kitty_id(&self) -> i64 {
        self.kitty_id
    }

    /// picture.go:301-310 `SetFit`.
    pub fn set_fit(&mut self, fit: FitMode) -> Option<PictureCmd> {
        if fit == self.fit {
            return None;
        }
        self.fit = fit;
        self.seq += 1;
        self.invalidate_glyph();
        self.invalidate_kitty();
        self.render_cmd()
    }

    /// picture.go:316-325 `SetAnchor`.
    pub fn set_anchor(&mut self, anchor: FitAnchor) -> Option<PictureCmd> {
        if anchor == self.anchor {
            return None;
        }
        self.anchor = anchor;
        self.seq += 1;
        self.invalidate_glyph();
        self.invalidate_kitty();
        self.render_cmd()
    }

    // PARITY: Go `Init` (picture.go:332-334) batches RequestCellSize (CSI
    // 16 t) + QueryKittySupport — terminal queries, suppressed in test mode
    // (testmode.go:20-21) and wired by the app shell in Phase 5. Not ported
    // here.

    /// picture.go:342-344 `CellPixelSize`.
    pub fn cell_pixel_size(&self) -> (i64, i64) {
        (self.cell_pixel_w, self.cell_pixel_h)
    }

    /// picture.go:350-365 `SetCellPixelSize`: non-positive values clamp
    /// to 1. This is the `uv.CellSizeEvent` half of Go's `Update`
    /// (picture.go:473-474).
    pub fn set_cell_pixel_size(&mut self, w: i64, h: i64) -> Option<PictureCmd> {
        let w = w.max(1);
        let h = h.max(1);
        if w == self.cell_pixel_w && h == self.cell_pixel_h {
            return None;
        }
        self.cell_pixel_w = w;
        self.cell_pixel_h = h;
        self.seq += 1;
        self.invalidate_kitty();
        self.render_cmd()
    }

    /// picture.go:369.
    pub fn kitty_resolution_factor(&self) -> f64 {
        self.kitty_resolution_factor
    }

    /// picture.go:376-387 `SetKittyResolutionFactor`.
    pub fn set_kitty_resolution_factor(&mut self, f: f64) -> Option<PictureCmd> {
        let f = if f <= 0.0 || f > 1.0 { 1.0 } else { f };
        if f == self.kitty_resolution_factor {
            return None;
        }
        self.kitty_resolution_factor = f;
        self.seq += 1;
        self.invalidate_kitty();
        self.render_cmd()
    }

    /// The `KittyFrameMsg` half of Go's `Update` (picture.go:437-460).
    /// Returns the APC bytes to write and the deferred grid application;
    /// Go sequences them via `tea.Sequence(tea.Raw(APC), applyKittyGrid)` —
    /// the caller MUST write the APC before feeding the grid msg back
    /// through [`Model::on_apply_kitty_grid`], or placeholder cells resolve
    /// to the previous image for one frame.
    pub fn on_kitty_frame(&mut self, msg: &KittyFrameMsg) -> Option<(String, ApplyKittyGridMsg)> {
        if msg.model_id != self.model_id || msg.seq != self.seq {
            return None;
        }
        // Record the geometry now: lastRenderedGeom is consumed by the next
        // renderCmd, and any SetSize that arrives between the APC emission
        // and the deferred grid apply must see this snapshot.
        self.last_rendered_geom = KittyGeom {
            cols: self.cols,
            rows: self.rows,
            cell_pixel_w: self.cell_pixel_w,
            cell_pixel_h: self.cell_pixel_h,
            fit: self.fit,
            anchor: self.anchor,
        };
        Some((
            msg.apc.clone(),
            ApplyKittyGridMsg {
                model_id: self.model_id,
                cols: self.cols,
                rows: self.rows,
                kitty_id: self.kitty_id,
                grid: msg.grid.clone(),
            },
        ))
    }

    /// The `applyKittyGridMsg` half of Go's `Update` (picture.go:461-472).
    /// Geometry-based staleness: SetImage bumps seq but doesn't change
    /// (cols, rows, kittyID), so an in-flight grid stays valid across
    /// SetImage; SetSize / kittyID changes invalidate.
    pub fn on_apply_kitty_grid(&mut self, msg: ApplyKittyGridMsg) {
        if msg.model_id != self.model_id {
            return;
        }
        if msg.cols != self.cols || msg.rows != self.rows || msg.kitty_id != self.kitty_id {
            return;
        }
        self.kitty_grid = Some(msg.grid);
    }

    /// picture.go:503-552 `View`: the rendered image as styled lines, or a
    /// zero-line [`Text`] if there is no image or no size (Go's `""`). In
    /// Kitty mode the placeholder grid is returned; if it hasn't been
    /// computed yet, falls through to Glyph half-blocks as a transitional
    /// fallback.
    pub fn view(&mut self) -> Text<'static> {
        if self.img.is_none() || self.cols <= 0 || self.rows <= 0 {
            return Text::default();
        }

        if self.mode == PictureMode::Kitty
            && let Some(grid) = &self.kitty_grid
        {
            return grid.clone();
        }
        // Falls through here in two cases: Glyph mode, or Kitty mode with
        // the grid not yet computed (transitional fallback during a
        // Glyph→Kitty toggle).

        let key = format!(
            "{}|{}|{}|{}|{}",
            self.seq, self.cols, self.rows, self.fit as i8, self.anchor as i8
        );
        if self.glyph_key == key
            && let Some(cache) = &self.glyph_cache
        {
            return cache.clone();
        }

        let img = self.img.as_ref().expect("checked above");
        let Some(rendered) = prepare_source(
            img,
            self.fit,
            self.cols,
            self.rows,
            self.cell_pixel_w,
            self.cell_pixel_h,
            self.background,
            self.anchor,
        ) else {
            return Text::default();
        };
        // ScaleModeResize (not Fit): prepareSource already applied the
        // chosen FitMode against the actual cell pixel dimensions,
        // producing a bitmap whose AR matches the cell rect; pixterm's own
        // AR handling would letterbox again on non-1:2 cells
        // (picture.go:525-532).
        let Ok(ascii) = ansimage_new_scaled_from_image(
            &rendered,
            self.rows * 2,
            self.cols,
            self.background,
            DitheringMode::NoDithering,
        ) else {
            return Text::default();
        };

        // PARITY: Go strips pixterm's per-row trailing "\n"
        // (picture.go:545-548); render_text yields exactly rows lines.
        let out = ascii.render_text();
        self.glyph_cache = Some(out.clone());
        self.glyph_key = key;
        out
    }

    /// picture.go:554-557.
    fn invalidate_glyph(&mut self) {
        self.glyph_cache = None;
        self.glyph_key = String::new();
    }

    /// picture.go:559-561.
    fn invalidate_kitty(&mut self) {
        self.kitty_grid = None;
    }

    /// picture.go:563-608 `renderCmd`: the heavy work (CatmullRom scale +
    /// PNG encode) is deferred into [`KittyRenderRequest`] so setters
    /// return immediately; the effect runner executes it off the main
    /// thread (CONCURRENCY.md §2.7).
    fn render_cmd(&self) -> Option<PictureCmd> {
        if self.mode != PictureMode::Kitty || self.cols <= 0 || self.rows <= 0 {
            return None;
        }
        let img = self.img.as_ref()?;
        // Apply kittyResolutionFactor to the cell-pixel dims used for the
        // transmitted image; the placement rectangle is unchanged.
        let mut cpw = (self.cell_pixel_w as f64 * self.kitty_resolution_factor) as i64;
        let mut cph = (self.cell_pixel_h as f64 * self.kitty_resolution_factor) as i64;
        if cpw < 1 {
            cpw = 1;
        }
        if cph < 1 {
            cph = 1;
        }
        Some(PictureCmd::Render(KittyRenderRequest {
            img: img.clone(),
            bg: self.background,
            model_id: self.model_id,
            id: self.kitty_id,
            cols: self.cols,
            rows: self.rows,
            seq: self.seq,
            fit: self.fit,
            anchor: self.anchor,
            cpw,
            cph,
            prev_geom: self.last_rendered_geom,
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use pretty_assertions::assert_eq;

    /// A cols×rows-cell picture Model with the given image, sized —
    /// mirrors `renderPictureGlyph` (mediapane.go:1465-1481).
    fn glyph_model(img: Arc<SourceImage>, cols: i64, rows: i64) -> Model {
        let mut m = Model::new();
        m.set_size(cols, rows);
        m.set_image(Some(img));
        m
    }

    /// Builds an opaque single-color image.
    fn uniform(width: usize, height: usize, rgb: [u8; 3]) -> Arc<SourceImage> {
        let mut pix = Vec::with_capacity(width * height * 4);
        for _ in 0..width * height {
            pix.extend_from_slice(&[rgb[0], rgb[1], rgb[2], 0xff]);
        }
        Arc::new(SourceImage::from_nrgba(width, height, pix))
    }

    /// One rendered span: (content, fg, bg).
    type SpanColors = (String, Option<Color>, Option<Color>);

    /// Collects (content, fg, bg) triples per line for assertions.
    fn spans_of(t: &Text<'_>) -> Vec<Vec<SpanColors>> {
        t.lines
            .iter()
            .map(|l| {
                l.spans
                    .iter()
                    .map(|s| (s.content.to_string(), s.style.fg, s.style.bg))
                    .collect()
            })
            .collect()
    }

    // -- CatmullRom kernel + distrib ------------------------------------

    #[test]
    fn catmull_rom_kernel_values() {
        // Hand-traced from scale.go:183-188.
        assert_eq!(catmull_rom_kernel(0.0), 1.0);
        assert_eq!(catmull_rom_kernel(0.5), 0.5625);
        assert_eq!(catmull_rom_kernel(1.0), 0.0);
        assert_eq!(catmull_rom_kernel(1.5), -0.0625);
    }

    #[test]
    fn new_distrib_identity_at_scale_one() {
        // dw == sw → each destination column has exactly one contrib at
        // its own coordinate with weight 1 (kernel(0)=1, kernel(1)=0).
        let d = new_distrib(4, 4);
        assert_eq!(d.sources.len(), 4);
        for (x, s) in d.sources.iter().enumerate() {
            let c: Vec<_> = d.contribs[s.i..s.j].iter().collect();
            assert_eq!(c.len(), 1, "column {x}");
            assert_eq!(c[0].coord, x as i64);
            assert_eq!(c[0].weight, 1.0);
            assert_eq!(s.inv_total_weight, 1.0);
        }
    }

    // -- imaging Box weights --------------------------------------------

    #[test]
    fn box_weights_exact_eight_pixel_average() {
        // 16 → 2 with Box: each output is the mean of its 8 source pixels
        // (hand trace: du=8, ru=4; v=0 → fu=3.5, indices 0..=7, kernel 1
        // each, normalized 1/8).
        let w = precompute_weights(2, 16);
        assert_eq!(w.len(), 2);
        let idx0: Vec<usize> = w[0].iter().map(|iw| iw.index).collect();
        assert_eq!(idx0, vec![0, 1, 2, 3, 4, 5, 6, 7]);
        for iw in &w[0] {
            assert_eq!(iw.weight, 0.125);
        }
        let idx1: Vec<usize> = w[1].iter().map(|iw| iw.index).collect();
        assert_eq!(idx1, vec![8, 9, 10, 11, 12, 13, 14, 15]);
    }

    #[test]
    fn box_resize_accumulators_fuse_like_go_arm64() {
        // PARITY pin for the FMA accumulators (see resize_horizontal):
        // six alphas summing to 735 averaged with Box weight 1/6. Go
        // (gc, arm64) fuses `acc += x*y` into FMADDD and lands on
        // exactly 122.5 → imaging_clamp → 123; unfused accumulation
        // gives 122.49999999999999 → 122.
        let alphas: [u8; 6] = [161, 146, 135, 133, 132, 28];
        let mut pix = Vec::new();
        for a in alphas {
            pix.extend_from_slice(&[255, 255, 255, a]);
        }

        // Vertical pass: 1×6 → 1×1.
        let src = ScanSrc::Nrgba {
            width: 1,
            height: 6,
            pix: &pix,
        };
        let out = resize_vertical(&src, 1);
        assert_eq!(out.pix, vec![255, 255, 255, 123]);

        // Horizontal pass: 6×1 → 1×1, same accumulation.
        let src = ScanSrc::Nrgba {
            width: 6,
            height: 1,
            pix: &pix,
        };
        let out = resize_horizontal(&src, 1);
        assert_eq!(out.pix, vec![255, 255, 255, 123]);
    }

    #[test]
    fn imaging_resize_same_dims_clones() {
        let img = uniform(4, 4, [10, 20, 30]);
        let out = imaging_resize(&PreparedImage::Source(img.clone()), 4, 4);
        assert_eq!(out.width, 4);
        assert_eq!(out.height, 4);
        assert_eq!(out.pix, img.pix);
    }

    #[test]
    fn scanner_unpremultiplies_rgba() {
        // scanner.go:71-104: premultiplied (128,128,128,128) scans to
        // straight (255,255,255,128) via c*0xff/a.
        let img = GoRgbaImage {
            width: 1,
            height: 1,
            pix: vec![128, 128, 128, 128],
        };
        let src = ScanSrc::Rgba(&img);
        let mut dst = [0u8; 4];
        src.scan(0, 0, 1, 1, &mut dst);
        assert_eq!(dst, [255, 255, 255, 128]);
    }

    // -- prepare_source (fit.go) ----------------------------------------

    #[test]
    fn contain_letterboxes_wide_source() {
        // 2×1 opaque white into 2 cols × 2 rows at default 8×16 px cells:
        // target 16×32, inscribed rect 16×8 at y∈[12,20) (integer math
        // fit.go:83-99), bars transparent black.
        let img = uniform(2, 1, [255, 255, 255]);
        let Some(PreparedImage::Rgba(out)) = prepare_source(
            &img,
            FitMode::Contain,
            2,
            2,
            8,
            16,
            TRANSPARENT,
            FitAnchor::Center,
        ) else {
            panic!("expected Rgba prepared image");
        };
        assert_eq!((out.width, out.height), (16, 32));
        let px = |x: usize, y: usize| {
            let i = (y * out.width + x) * 4;
            [out.pix[i], out.pix[i + 1], out.pix[i + 2], out.pix[i + 3]]
        };
        assert_eq!(px(0, 0), [0, 0, 0, 0], "letterbox bar is transparent");
        assert_eq!(px(8, 11), [0, 0, 0, 0], "row above inscribed rect");
        assert_eq!(px(8, 12), [255, 255, 255, 255], "inscribed rect top");
        assert_eq!(px(15, 19), [255, 255, 255, 255], "inscribed rect bottom");
        assert_eq!(px(8, 20), [0, 0, 0, 0], "row below inscribed rect");
    }

    #[test]
    fn fill_fast_path_returns_source() {
        // fit.go:61-63: transparent bg + exact size → the source itself.
        let img = uniform(16, 32, [1, 2, 3]);
        let out = prepare_source(
            &img,
            FitMode::Fill,
            2,
            2,
            8,
            16,
            TRANSPARENT,
            FitAnchor::Center,
        )
        .unwrap();
        match out {
            PreparedImage::Source(s) => assert!(Arc::ptr_eq(&s, &img)),
            PreparedImage::Rgba(_) => panic!("expected fast-path Source"),
        }
    }

    #[test]
    fn prepare_source_rejects_non_positive_dims() {
        let img = uniform(2, 2, [0, 0, 0]);
        assert!(
            prepare_source(
                &img,
                FitMode::Contain,
                0,
                1,
                8,
                16,
                TRANSPARENT,
                FitAnchor::Center
            )
            .is_none()
        );
        assert!(
            prepare_source(
                &img,
                FitMode::Contain,
                1,
                -1,
                8,
                16,
                TRANSPARENT,
                FitAnchor::Center
            )
            .is_none()
        );
    }

    // -- Glyph rendering end-to-end (Model::view) ------------------------

    #[test]
    fn view_uniform_color_renders_uniform_half_blocks() {
        // Test A: 2×2 red → 2 cols × 1 row: one line, one merged span
        // "▄▄" with fg == bg == red.
        let mut m = glyph_model(uniform(2, 2, [255, 0, 0]), 2, 1);
        let view = m.view();
        let red = Some(Color::Rgb(255, 0, 0));
        assert_eq!(spans_of(&view), vec![vec![("▄▄".to_string(), red, red)]],);
    }

    #[test]
    fn view_quadrants_map_to_upper_bg_lower_fg() {
        // Test B: a 16×16 source (CatmullRom is identity at 1:1; Box then
        // averages uniform 8×8 quadrants exactly): TL red, TR green,
        // BL blue, BR white → cell(0): bg red / fg blue, cell(1): bg
        // green / fg white.
        let (w, h) = (16usize, 16usize);
        let mut pix = vec![0u8; w * h * 4];
        for y in 0..h {
            for x in 0..w {
                let rgb: [u8; 3] = match (x < 8, y < 8) {
                    (true, true) => [255, 0, 0],
                    (false, true) => [0, 255, 0],
                    (true, false) => [0, 0, 255],
                    (false, false) => [255, 255, 255],
                };
                let i = (y * w + x) * 4;
                pix[i..i + 3].copy_from_slice(&rgb);
                pix[i + 3] = 0xff;
            }
        }
        let mut m = glyph_model(Arc::new(SourceImage::from_nrgba(w, h, pix)), 2, 1);
        let view = m.view();
        assert_eq!(
            spans_of(&view),
            vec![vec![
                (
                    "▄".to_string(),
                    Some(Color::Rgb(0, 0, 255)), // fg: lower = blue
                    Some(Color::Rgb(255, 0, 0)), // bg: upper = red
                ),
                (
                    "▄".to_string(),
                    Some(Color::Rgb(255, 255, 255)), // fg: lower = white
                    Some(Color::Rgb(0, 255, 0)),     // bg: upper = green
                ),
            ]],
        );
    }

    #[test]
    fn view_letterbox_renders_black_bars_and_alpha_averaged_edges() {
        // Test C (hand-traced through the full Go chain): 2×1 white into
        // 2×2 cells. prepareSource letterboxes white into pixel rows
        // 12..20 of a 16×32 transparent target; Box resize to 2×4 makes
        // row 0 transparent (→ black), rows 1-2 half-covered
        // (premultiplied avg → NRGBA (255,255,255,128) → RGBA
        // (128,128,128)), row 3 transparent. Cell rows: (bg black, fg
        // gray), (bg gray, fg black).
        let mut m = glyph_model(uniform(2, 1, [255, 255, 255]), 2, 2);
        let view = m.view();
        let black = Some(Color::Rgb(0, 0, 0));
        let gray = Some(Color::Rgb(128, 128, 128));
        assert_eq!(
            spans_of(&view),
            vec![
                vec![("▄▄".to_string(), gray, black)],
                vec![("▄▄".to_string(), black, gray)],
            ],
        );
    }

    #[test]
    fn view_empty_without_image_or_size() {
        let mut m = Model::new();
        assert!(m.view().lines.is_empty(), "no image, no size");
        m.set_size(2, 1);
        assert!(m.view().lines.is_empty(), "no image");
        m.set_image(Some(uniform(2, 2, [1, 1, 1])));
        m.set_size(0, 0);
        assert!(m.view().lines.is_empty(), "zero size");
    }

    #[test]
    fn view_single_column_hits_ansimage_bounds_error() {
        // ansimage.New requires w >= 2 (ansimage.go:555-557); a 1-column
        // picture renders as Go's "" → zero-line Text (the media pane
        // shows its placeholder).
        let mut m = glyph_model(uniform(4, 4, [9, 9, 9]), 1, 1);
        assert!(m.view().lines.is_empty());
    }

    #[test]
    fn view_caches_by_key_and_invalidates_on_set_image() {
        let img = uniform(2, 2, [7, 7, 7]);
        let mut m = glyph_model(img.clone(), 2, 1);
        let first = m.view();
        let second = m.view();
        assert_eq!(first, second);
        // Cache key includes seq: SetImage bumps it and re-renders.
        m.set_image(Some(uniform(2, 2, [200, 0, 0])));
        let third = m.view();
        assert_ne!(first, third);
    }

    #[test]
    fn set_size_clamps_negatives_to_zero() {
        // picture.go:230-235.
        let mut m = Model::new();
        m.set_size(-3, -4);
        assert_eq!((m.cols, m.rows), (0, 0));
    }

    // -- ansimage direct ------------------------------------------------

    #[test]
    fn create_ansimage_pads_odd_height_with_background() {
        // Test E: 2×3 opaque white over opaque red bg → h rounds to 4;
        // row 3 is bg-padded (truncated 16-bit bg: 0xffff → 0xff).
        let img = GoNrgbaImage {
            width: 2,
            height: 3,
            pix: vec![255u8; 2 * 3 * 4],
        };
        let bg = GoColor {
            r: 0xffff,
            g: 0,
            b: 0,
            a: 0xffff,
        };
        let ai = create_ansimage(&img, bg, DitheringMode::NoDithering).unwrap();
        assert_eq!((ai.height(), ai.width()), (4, 2));
        let text = ai.render_text();
        let white = Some(Color::Rgb(255, 255, 255));
        let red = Some(Color::Rgb(255, 0, 0));
        assert_eq!(
            spans_of(&text),
            vec![
                vec![("▄▄".to_string(), white, white)],
                // Upper = data row 2 (white), lower = pad row (bg red).
                vec![("▄▄".to_string(), red, white)],
            ],
        );
    }

    #[test]
    fn create_ansimage_rejects_small_bounds() {
        let img = GoNrgbaImage {
            width: 1,
            height: 2,
            pix: vec![0u8; 8],
        };
        assert_eq!(
            create_ansimage(&img, TRANSPARENT, DitheringMode::NoDithering),
            Err(AnsImageError::InvalidBoundsMoT)
        );
    }

    #[test]
    fn dithering_blocks_average_and_glyphs() {
        // Test F: 8×16 image, left 4 columns white, right 4 columns gray
        // 128 → 2×2 cells of 8×4 px blocks. luminance(white)=255 → '█',
        // luminance(gray128)=128 → '▒' (ansimage.go:174-187).
        let (w, h) = (8usize, 16usize);
        let mut pix = vec![0u8; w * h * 4];
        for y in 0..h {
            for x in 0..w {
                let c: u8 = if x < 4 { 255 } else { 128 };
                let i = (y * w + x) * 4;
                pix[i..i + 3].fill(c);
                pix[i + 3] = 0xff;
            }
        }
        let img = GoNrgbaImage {
            width: w,
            height: h,
            pix,
        };
        let ai = create_ansimage(&img, TRANSPARENT, DitheringMode::DitheringWithBlocks).unwrap();
        assert_eq!((ai.height(), ai.width()), (2, 2));
        let text = ai.render_text();
        let bg = Some(Color::Rgb(0, 0, 0));
        let row = vec![
            ("█".to_string(), Some(Color::Rgb(255, 255, 255)), bg),
            ("▒".to_string(), Some(Color::Rgb(128, 128, 128)), bg),
        ];
        assert_eq!(spans_of(&text), vec![row.clone(), row]);
    }

    #[test]
    fn dither_block_thresholds() {
        // ansimage.go:174-215 boundary values.
        assert_eq!(dither_block(205, DitheringMode::DitheringWithBlocks), "█");
        assert_eq!(dither_block(204, DitheringMode::DitheringWithBlocks), "▓");
        assert_eq!(dither_block(101, DitheringMode::DitheringWithBlocks), "▒");
        assert_eq!(dither_block(49, DitheringMode::DitheringWithBlocks), "░");
        assert_eq!(dither_block(48, DitheringMode::DitheringWithBlocks), " ");
        assert_eq!(dither_block(231, DitheringMode::DitheringWithChars), "#");
        assert_eq!(dither_block(24, DitheringMode::DitheringWithChars), ".");
        assert_eq!(dither_block(23, DitheringMode::DitheringWithChars), " ");
    }

    #[test]
    fn luminance_and_rgba_component() {
        assert_eq!(luminance(255, 255, 255), 255);
        assert_eq!(luminance(0, 0, 0), 0);
        assert_eq!(luminance(128, 128, 128), 128);
        // 299*255/1000 = 76.245 → 76.
        assert_eq!(luminance(255, 0, 0), 76);
        assert_eq!(rgba_component(128, 128), 255);
        assert_eq!(rgba_component(0, 128), 0);
        assert_eq!(rgba_component(64, 0xff), 64);
        assert_eq!(rgba_component(64, 0), 0);
    }

    // -- Kitty capability + toggle + frame flow -------------------------

    #[test]
    fn kitty_capability_gates_toggle_and_frame_flow_applies_grid() {
        // Single test for everything that touches the process-wide
        // capability static, to keep test-order independence.
        let mut m = Model::new_with_config(Config {
            kitty_id: 777,
            ..Config::default()
        });
        m.set_size(2, 1);
        m.set_image(Some(uniform(2, 2, [10, 20, 30])));

        // Unknown blocks Toggle (picture.go:268-270).
        assert_eq!(kitty_supported(), KittyCapability::Unknown);
        assert!(m.toggle().is_none());
        assert_eq!(m.mode(), PictureMode::Glyph);

        force_kitty_capability(KittyCapability::Supported);
        let cmd = m.toggle();
        assert_eq!(m.mode(), PictureMode::Kitty);
        let Some(PictureCmd::Render(req)) = cmd else {
            panic!("expected render request, got {cmd:?}");
        };

        // Kitty grid not yet applied → View falls back to Glyph.
        let fallback = m.view();
        assert_eq!(fallback.lines.len(), 1);
        assert_eq!(fallback.lines[0].spans[0].content.chars().next(), Some('▄'));

        // Run the deferred render; the frame carries APC + grid.
        let frame = req.run().expect("frame");
        assert_eq!(frame.id, 777);
        assert!(
            frame
                .apc
                .starts_with("\x1b_Gf=100,q=2,i=777,U=1,c=2,r=1,a=T")
        );
        assert!(!frame.apc.starts_with(&kitty_delete_image(777)));

        let (apc, grid_msg) = m.on_kitty_frame(&frame).expect("fresh frame accepted");
        assert_eq!(apc, frame.apc);
        m.on_apply_kitty_grid(grid_msg);

        // View now returns the placeholder grid.
        let view = m.view();
        assert_eq!(view.lines.len(), 1);
        let content: Vec<char> = view.lines[0].spans[0].content.chars().collect();
        assert_eq!(
            content,
            vec![
                PLACEHOLDER,
                diacritic(0),
                diacritic(0),
                PLACEHOLDER,
                diacritic(0),
                diacritic(1),
            ]
        );
        // 777 = 0x309 → fg (0, 3, 9).
        assert_eq!(view.lines[0].spans[0].style.fg, Some(Color::Rgb(0, 3, 9)));

        // A geometry change: the next render request prepends the delete
        // sequence (picture.go:601-604).
        let Some(PictureCmd::Render(req2)) = m.set_size(3, 1) else {
            panic!("expected render request after resize");
        };
        let frame2 = req2.run().expect("frame2");
        assert!(frame2.apc.starts_with(&kitty_delete_image(777)));

        // A stale frame (old seq) is dropped (picture.go:438-440).
        assert!(m.on_kitty_frame(&frame).is_none());

        // Clearing the image in Kitty mode emits the delete sequence
        // (picture.go:211-221).
        let cmd = m.set_image(None);
        match cmd {
            Some(PictureCmd::Raw(raw)) => assert_eq!(raw, kitty_delete_image(777)),
            other => panic!("expected Raw delete, got {other:?}"),
        }

        force_kitty_capability(KittyCapability::Unknown);
    }

    #[test]
    fn apply_kitty_grid_rejects_stale_geometry() {
        let mut m = Model::new_with_config(Config {
            kitty_id: 5,
            ..Config::default()
        });
        m.set_size(2, 2);
        let msg = ApplyKittyGridMsg {
            model_id: m.model_id,
            cols: 2,
            rows: 1, // stale: model is 2×2
            kitty_id: 5,
            grid: build_kitty_grid(2, 1, 5),
        };
        m.on_apply_kitty_grid(msg);
        assert!(m.kitty_grid.is_none());
    }

    // -- Kitty APC encoder ----------------------------------------------

    #[test]
    fn base64_std_vectors() {
        assert_eq!(base64_std(b""), "");
        assert_eq!(base64_std(b"f"), "Zg==");
        assert_eq!(base64_std(b"fo"), "Zm8=");
        assert_eq!(base64_std(b"foo"), "Zm9v");
        assert_eq!(base64_std(b"foobar"), "Zm9vYmFy");
    }

    fn media_apc_options(id: i64, cols: i64, rows: i64) -> KittyOptions {
        KittyOptions {
            action: ACTION_TRANSMIT_AND_PUT,
            transmission: TRANSMISSION_DIRECT,
            format: FORMAT_PNG,
            id,
            columns: cols,
            rows,
            virtual_placement: true,
            quite: 2,
            chunk: true,
            ..KittyOptions::default()
        }
    }

    #[test]
    fn single_chunk_apc_framing() {
        // Payload below MaxChunkSize: one APC, full option set, no m key
        // (writer.go:178-185 skips m for a lone chunk).
        let out = encode_graphics_chunks("QUJD", &media_apc_options(10001, 3, 2));
        assert_eq!(out, "\x1b_Gf=100,q=2,i=10001,U=1,c=3,r=2,a=T;QUJD\x1b\\");
    }

    #[test]
    fn exact_multiple_payload_emits_trailing_empty_chunk() {
        // PARITY quirk: io.ReadFull semantics — a payload of exactly
        // MaxChunkSize emits a full m=1 chunk plus an EMPTY m=0 chunk
        // with no `;`.
        let payload = "A".repeat(MAX_CHUNK_SIZE);
        let out = encode_graphics_chunks(&payload, &media_apc_options(43, 4, 4));
        let chunks: Vec<&str> = out.split("\x1b\\").filter(|s| !s.is_empty()).collect();
        assert_eq!(chunks.len(), 2);
        assert_eq!(
            chunks[0],
            format!("\x1b_Gf=100,q=2,i=43,U=1,c=4,r=4,a=T,m=1;{payload}")
        );
        assert_eq!(chunks[1], "\x1b_Gq=2,m=0");
    }

    #[test]
    fn multi_chunk_apc_framing() {
        // 5000 bytes → 4096-byte m=1 chunk with full options, then a
        // 904-byte m=0 chunk with only q=2.
        let payload = "B".repeat(5000);
        let out = encode_graphics_chunks(&payload, &media_apc_options(10002, 2, 1));
        let chunks: Vec<&str> = out.split("\x1b\\").filter(|s| !s.is_empty()).collect();
        assert_eq!(chunks.len(), 2);
        let first = chunks[0];
        assert!(first.starts_with("\x1b_Gf=100,q=2,i=10002,U=1,c=2,r=1,a=T,m=1;"));
        let first_payload = first.split(';').nth(1).unwrap();
        assert_eq!(first_payload.len(), MAX_CHUNK_SIZE);
        let last = chunks[1];
        assert!(last.starts_with("\x1b_Gq=2,m=0;"));
        assert_eq!(last.split(';').nth(1).unwrap().len(), 5000 - MAX_CHUNK_SIZE);
    }

    #[test]
    fn build_kitty_apc_payload_round_trips_pixels() {
        // The concatenated base64 payload decodes to a PNG whose pixels
        // equal the prepared image (2×2 distinct colors).
        let pix = vec![
            255, 0, 0, 255, //
            0, 255, 0, 255, //
            0, 0, 255, 255, //
            255, 255, 255, 128,
        ];
        let img = Arc::new(SourceImage::from_nrgba(2, 2, pix.clone()));
        let apc = build_kitty_apc(&PreparedImage::Source(img), 10003, 2, 1);
        assert!(apc.starts_with("\x1b_Gf=100,q=2,i=10003,U=1,c=2,r=1,a=T"));

        // Reassemble the base64 payload from all chunks.
        let mut b64 = String::new();
        for chunk in apc.split("\x1b\\").filter(|s| !s.is_empty()) {
            if let Some((_, payload)) = chunk.split_once(';') {
                b64.push_str(payload);
            }
        }
        // Decode base64 (test-local helper).
        let table: std::collections::HashMap<u8, u32> =
            b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
                .iter()
                .enumerate()
                .map(|(i, &c)| (c, i as u32))
                .collect();
        let mut bytes = Vec::new();
        let raw: Vec<u8> = b64.bytes().filter(|&b| b != b'=').collect();
        for group in raw.chunks(4) {
            let mut n = 0u32;
            for (k, &c) in group.iter().enumerate() {
                n |= table[&c] << (18 - 6 * k);
            }
            bytes.push((n >> 16) as u8);
            if group.len() > 2 {
                bytes.push((n >> 8) as u8);
            }
            if group.len() > 3 {
                bytes.push(n as u8);
            }
        }
        let decoded = image::load_from_memory(&bytes)
            .expect("valid png")
            .to_rgba8();
        assert_eq!((decoded.width(), decoded.height()), (2, 2));
        assert_eq!(decoded.into_raw(), pix);
    }

    #[test]
    fn kitty_delete_image_format() {
        // picture/kitty.go:62-64.
        assert_eq!(kitty_delete_image(10001), "\x1b_Ga=d,d=I,i=10001,q=2\x1b\\");
    }

    #[test]
    fn kitty_grid_shape_and_diacritics() {
        let grid = build_kitty_grid(3, 2, 10001);
        assert_eq!(grid.lines.len(), 2);
        // 10001 = 0x2711 → fg (0, 39, 17).
        let fg = Some(Color::Rgb(0, 39, 17));
        for (y, line) in grid.lines.iter().enumerate() {
            assert_eq!(line.spans.len(), 1);
            assert_eq!(line.spans[0].style.fg, fg);
            let chars: Vec<char> = line.spans[0].content.chars().collect();
            assert_eq!(chars.len(), 9);
            for x in 0..3 {
                assert_eq!(chars[x * 3], PLACEHOLDER);
                assert_eq!(chars[x * 3 + 1], diacritic(y as i64));
                assert_eq!(chars[x * 3 + 2], diacritic(x as i64));
            }
        }
    }

    #[test]
    fn diacritic_table_and_bounds() {
        assert_eq!(DIACRITICS.len(), 297);
        assert_eq!(diacritic(0), '\u{0305}');
        assert_eq!(diacritic(1), '\u{030D}');
        assert_eq!(diacritic(296), '\u{1D244}');
        // Out of bounds → first entry (kitty/graphics.go:107-112).
        assert_eq!(diacritic(297), '\u{0305}');
        assert_eq!(diacritic(-1), '\u{0305}');
    }

    #[test]
    fn media_kitty_ids_are_monotonic_above_base() {
        let a = next_media_kitty_id();
        let b = next_media_kitty_id();
        assert!(a > MEDIA_KITTY_ID_BASE);
        assert_eq!(b, a + 1);
    }

    #[test]
    fn kitty_options_order_matches_go() {
        // The mediapane option set in options.go:150-282 emission order.
        let opts = media_apc_options(10001, 3, 2).options();
        assert_eq!(
            opts,
            vec![
                "f=100".to_string(),
                "q=2".to_string(),
                "i=10001".to_string(),
                "U=1".to_string(),
                "c=3".to_string(),
                "r=2".to_string(),
                "a=T".to_string(),
            ]
        );
        // Delete-resources uppercases the delete key (options.go:268-275).
        let del = KittyOptions {
            delete: b'i',
            delete_resources: true,
            ..KittyOptions::default()
        };
        assert!(del.options().contains(&"d=I".to_string()));
    }
}
