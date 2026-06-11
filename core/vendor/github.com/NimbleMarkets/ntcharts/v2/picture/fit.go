package picture

import (
	"image"
	"image/color"

	"golang.org/x/image/draw"
)

// prepareSource returns an image.Image of bounds (cols*cellW × rows*cellH)
// with src mapped onto the target cell rectangle according to fit. All
// three modes composite over bg using draw.Over, so semi-transparent
// sources show the configured Background through their translucent areas
// (matching the behavior of the removed composite() helper). FitContain
// additionally fills the letterbox bars with bg. The returned bitmap is
// sized so both Glyph and Kitty backends can encode it without further AR
// math: each backend's native letterbox or stretch step is a no-op when
// source AR matches target AR.
//
// Returns nil for non-positive dims (defensive — callers should already
// short-circuit on cols/rows <= 0). Returns a bg-filled target when src
// has empty bounds.
func prepareSource(src image.Image, fit FitMode, cols, rows, cellW, cellH int, bg color.Color, anchor FitAnchor) image.Image {
	if cols <= 0 || rows <= 0 || cellW <= 0 || cellH <= 0 {
		return nil
	}
	tw := cols * cellW
	th := rows * cellH
	target := image.Rect(0, 0, tw, th)

	sb := src.Bounds()
	if sb.Dx() == 0 || sb.Dy() == 0 {
		out := image.NewRGBA(target)
		draw.Draw(out, target, &image.Uniform{C: bg}, image.Point{}, draw.Src)
		return out
	}

	switch fit {
	case FitFill:
		return fillTo(src, sb, target, bg)
	case FitCover:
		return coverTo(src, sb, target, bg, anchor)
	default: // FitContain and any out-of-range value
		return containTo(src, sb, target, bg)
	}
}

// bgIsTransparent reports whether bg has zero alpha — same predicate the
// removed composite helper used as its short-circuit.
func bgIsTransparent(bg color.Color) bool {
	_, _, _, a := bg.RGBA()
	return a == 0
}

// fillTo stretches src to exactly target, compositing over bg with
// draw.Over so semi-transparent sources show bg through their translucent
// areas. Fast path: when bg is transparent AND src is already at target
// size, return src unchanged (matches the kitty.go optimization the
// original composite() preserved for the transparent-bg case).
func fillTo(src image.Image, sb, target image.Rectangle, bg color.Color) image.Image {
	if bgIsTransparent(bg) && sb.Dx() == target.Dx() && sb.Dy() == target.Dy() {
		return src
	}
	out := image.NewRGBA(target)
	draw.Draw(out, target, &image.Uniform{C: bg}, image.Point{}, draw.Src)
	draw.CatmullRom.Scale(out, target, src, sb, draw.Over, nil)
	return out
}

// containTo computes the AR-preserving inscribed rect inside target, fills
// target with bg, then draws src into the inscribed rect with draw.Over so
// transparent bg yields literal transparency in the output PNG.
func containTo(src image.Image, sb, target image.Rectangle, bg color.Color) image.Image {
	out := image.NewRGBA(target)
	draw.Draw(out, target, &image.Uniform{C: bg}, image.Point{}, draw.Src)

	tw, th := target.Dx(), target.Dy()
	sw, sh := sb.Dx(), sb.Dy()

	// Inscribed rect: scale source to fit within target preserving AR.
	// Compare cross products to avoid floating point: sw/sh <=> tw/th.
	var iw, ih int
	if sw*th >= sh*tw {
		// Source is "wider" relative to target; width-limited.
		iw = tw
		ih = sh * tw / sw
	} else {
		// Source is "taller" relative to target; height-limited.
		ih = th
		iw = sw * th / sh
	}
	if iw < 1 {
		iw = 1
	}
	if ih < 1 {
		ih = 1
	}
	ox := (tw - iw) / 2
	oy := (th - ih) / 2
	dst := image.Rect(ox, oy, ox+iw, oy+ih)
	draw.CatmullRom.Scale(out, dst, src, sb, draw.Over, nil)
	return out
}

// coverTo computes the AR-preserving circumscribed rect (one axis matches
// target, the other overflows), fills target with bg, then draws src into
// the circumscribed rect with draw.Over. Target-bound clipping crops the
// overflow; bg shows through translucent source pixels.
func coverTo(src image.Image, sb, target image.Rectangle, bg color.Color, anchor FitAnchor) image.Image {
	tw, th := target.Dx(), target.Dy()
	sw, sh := sb.Dx(), sb.Dy()

	// Circumscribed rect: scale source so it covers target preserving AR.
	// Compare cross products: if sw/sh > tw/th, source is wider — height-bind.
	var cw, ch int
	if sw*th > sh*tw {
		// Width overflows: bind height to target, width grows past target.
		ch = th
		cw = sw * th / sh
	} else {
		// Height overflows (or equal): bind width.
		cw = tw
		ch = sh * tw / sw
	}
	if cw < 1 {
		cw = 1
	}
	if ch < 1 {
		ch = 1
	}
	var ox, oy int
	switch anchor {
	case AnchorTop:
		ox = (tw - cw) / 2
		oy = 0
	case AnchorBottom:
		ox = (tw - cw) / 2
		oy = th - ch
	case AnchorLeft:
		ox = 0
		oy = (th - ch) / 2
	case AnchorRight:
		ox = tw - cw
		oy = (th - ch) / 2
	default: // AnchorCenter
		ox = (tw - cw) / 2
		oy = (th - ch) / 2
	}
	dst := image.Rect(ox, oy, ox+cw, oy+ch)
	out := image.NewRGBA(target)
	draw.Draw(out, target, &image.Uniform{C: bg}, image.Point{}, draw.Src)
	draw.CatmullRom.Scale(out, dst, src, sb, draw.Over, nil)
	return out
}
