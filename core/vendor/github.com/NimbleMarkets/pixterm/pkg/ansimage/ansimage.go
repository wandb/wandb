//       ___  _____  ____
//      / _ \/  _/ |/_/ /____ ______ _
//     / ___// /_>  </ __/ -_) __/  ' \
//    /_/  /___/_/|_|\__/\__/_/ /_/_/_/
//
//    Copyright 2017 Eliuk Blau
//
//    This Source Code Form is subject to the terms of the Mozilla Public
//    License, v. 2.0. If a copy of the MPL was not distributed with this
//    file, You can obtain one at https://mozilla.org/MPL/2.0/.

package ansimage

import (
	"errors"
	"fmt"
	"image"
	"image/color"
	"image/draw"
	"io"
	"net/http"
	"os"
	"sync"
	"unsafe"

	_ "image/gif"  // initialize decoder
	_ "image/jpeg" // initialize decoder
	_ "image/png"  // initialize decoder

	_ "golang.org/x/image/bmp"  // initialize decoder
	_ "golang.org/x/image/tiff" // initialize decoder
	_ "golang.org/x/image/webp" // initialize decoder

	"github.com/disintegration/imaging"
)

// Unicode Block Element character used to represent lower pixel in terminal row.
// INFO: https://en.wikipedia.org/wiki/Block_Elements
const lowerHalfBlock = "\u2584"

// Unicode Block Element characters used to represent dithering in terminal row.
// INFO: https://en.wikipedia.org/wiki/Block_Elements
const fullBlock = "\u2588"
const darkShadeBlock = "\u2593"
const mediumShadeBlock = "\u2592"
const lightShadeBlock = "\u2591"

// ANSImage scale modes:
// resize (full scaled to area),
// fill (resize and crop the image with a center anchor point to fill area),
// fit (resize the image to fit area, preserving the aspect ratio).
const (
	ScaleModeResize = ScaleMode(iota)
	ScaleModeFill
	ScaleModeFit
)

// ANSImage dithering modes:
// no dithering (classic mode: half block based),
// chars (use characters to represent brightness),
// blocks (use character blocks to represent brightness).
const (
	NoDithering = DitheringMode(iota)
	DitheringWithBlocks
	DitheringWithChars
)

// ANSImage block size in pixels (dithering mode)
const (
	BlockSizeY = 8
	BlockSizeX = 4
)

var (
	// ErrImageDownloadFailed occurs in the attempt to download an image and the status code of the response is not "200 OK".
	ErrImageDownloadFailed = errors.New("ANSImage: image download failed")

	// ErrHeightNonMoT occurs when ANSImage height is not a Multiple of Two value.
	ErrHeightNonMoT = errors.New("ANSImage: height must be a Multiple of Two value")

	// ErrInvalidBoundsMoT occurs when ANSImage height or width are invalid values (Multiple of Two).
	ErrInvalidBoundsMoT = errors.New("ANSImage: height or width must be >=2")

	// ErrOutOfBounds occurs when ANSI-pixel coordinates are out of ANSImage bounds.
	ErrOutOfBounds = errors.New("ANSImage: out of bounds")

	// errUnknownScaleMode occurs when scale mode is invalid.
	errUnknownScaleMode = errors.New("ANSImage: unknown scale mode")

	// errUnknownDitheringMode occurs when dithering mode is invalid.
	errUnknownDitheringMode = errors.New("ANSImage: unknown dithering mode")
)

// ScaleMode type is used for image scale mode constants.
type ScaleMode uint8

// DitheringMode type is used for image scale dithering mode constants.
type DitheringMode uint8

// ANSIpixel represents a pixel of an ANSImage.
type ANSIpixel struct {
	Brightness uint8
	R, G, B    uint8
	upper      bool
	source     *ANSImage
}

type ansiPixelData struct {
	Brightness uint8
	R, G, B    uint8
}

// ANSImage represents an image encoded in ANSI escape codes.
type ANSImage struct {
	h, w      int
	maxprocs  int
	bgR       uint8
	bgG       uint8
	bgB       uint8
	dithering DitheringMode
	pixmap    []ansiPixelData
}

// Render returns the ANSI-compatible string form of ANSI-pixel.
func (ap *ANSIpixel) Render() string {
	return ap.RenderExt(false, false)
}

// RenderExt returns the ANSI-compatible string form of ANSI-pixel.
// Can specify if it renders in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
func (ap *ANSIpixel) RenderExt(renderGoCode, disableBgColor bool) string {
	buf := make([]byte, 0, 48)
	buf = appendANSIPixel(buf, ap, ansiEscape(renderGoCode), disableBgColor)
	return string(buf)
}

func ansiEscape(renderGoCode bool) string {
	if renderGoCode {
		return "\\033"
	}
	return "\033"
}

func appendANSIPixel(buf []byte, ap *ANSIpixel, backslash033 string, disableBgColor bool) []byte {
	return appendANSIPixelData(buf, ansiPixelData{
		Brightness: ap.Brightness,
		R:          ap.R,
		G:          ap.G,
		B:          ap.B,
	}, ap.source, ap.upper, backslash033, disableBgColor)
}

func appendANSIPixelData(buf []byte, p ansiPixelData, source *ANSImage, upper bool, backslash033 string, disableBgColor bool) []byte {
	// WITHOUT DITHERING
	if source.dithering == NoDithering {
		if upper {
			return appendANSIColor(buf, backslash033, "48", p.R, p.G, p.B)
		}
		buf = appendANSIColor(buf, backslash033, "38", p.R, p.G, p.B)
		return append(buf, lowerHalfBlock...)
	}

	// WITH DITHERING
	if !disableBgColor {
		buf = appendANSIColor(buf, backslash033, "48", source.bgR, source.bgG, source.bgB)
	}
	buf = appendANSIColor(buf, backslash033, "38", p.R, p.G, p.B)
	return append(buf, ditherBlock(p.Brightness, source.dithering)...)
}

// ditherBlock maps an aggregated 8-bit brightness to its rendered glyph for
// the given dithering mode. Returns " " when no glyph threshold is reached.
func ditherBlock(brightness uint8, mode DitheringMode) string {
	switch mode {
	case DitheringWithBlocks:
		switch {
		case brightness > 204:
			return fullBlock
		case brightness > 152:
			return darkShadeBlock
		case brightness > 100:
			return mediumShadeBlock
		case brightness > 48:
			return lightShadeBlock
		}
		return " "
	case DitheringWithChars:
		switch {
		case brightness > 230:
			return "#"
		case brightness > 207:
			return "&"
		case brightness > 184:
			return "$"
		case brightness > 161:
			return "X"
		case brightness > 138:
			return "x"
		case brightness > 115:
			return "="
		case brightness > 92:
			return "+"
		case brightness > 69:
			return ";"
		case brightness > 46:
			return ":"
		case brightness > 23:
			return "."
		}
		return " "
	default:
		panic(errUnknownDitheringMode)
	}
}

func appendANSIColor(buf []byte, backslash033, colorCode string, r, g, b uint8) []byte {
	buf = append(buf, backslash033...)
	buf = append(buf, '[')
	buf = append(buf, colorCode...)
	buf = append(buf, ";2;"...)
	buf = appendUint8(buf, r)
	buf = append(buf, ';')
	buf = appendUint8(buf, g)
	buf = append(buf, ';')
	buf = appendUint8(buf, b)
	return append(buf, 'm')
}

func appendUint8(buf []byte, v uint8) []byte {
	if v >= 100 {
		return append(buf, '0'+v/100, '0'+v/10%10, '0'+v%10)
	}
	if v >= 10 {
		return append(buf, '0'+v/10, '0'+v%10)
	}
	return append(buf, '0'+v)
}

func appendReset(buf []byte, backslash033, backslashN string) []byte {
	buf = append(buf, backslash033...)
	buf = append(buf, "[0m"...)
	return append(buf, backslashN...)
}

func appendGoPrintStart(buf []byte) []byte {
	return append(buf, `fmt.Print("`...)
}

func appendGoPrintEnd(buf []byte) []byte {
	buf = append(buf, `")`...)
	return append(buf, '\n')
}

func rgbaComponent(c, a uint8) uint8 {
	if a == 0 || c == 0 {
		return 0
	}
	if a == 0xff {
		return c
	}
	v := uint32(c) * 0xff / uint32(a)
	if v > 0xff {
		return 0xff
	}
	return uint8(v)
}

// luminance calculates perceptual brightness using ITU-R BT.601 luma coefficients.
// These constants reflect the human eye's higher sensitivity to green and lower
// sensitivity to blue.
func luminance(r, g, b uint8) uint8 {
	return uint8((299*uint32(r) + 587*uint32(g) + 114*uint32(b)) / 1000)
}

// Height gets total rows of ANSImage.
func (ai *ANSImage) Height() int {
	return ai.h
}

// Width gets total columns of ANSImage.
func (ai *ANSImage) Width() int {
	return ai.w
}

// DitheringMode gets the dithering mode of ANSImage.
func (ai *ANSImage) DitheringMode() DitheringMode {
	return ai.dithering
}

// SetMaxProcs sets the maximum number of parallel goroutines to render the ANSImage.
// Values less than 1 are clamped to 1; otherwise the render loop's outer
// step `y += ai.maxprocs` would never advance (or go negative).
func (ai *ANSImage) SetMaxProcs(max int) {
	if max < 1 {
		max = 1
	}
	ai.maxprocs = max
}

// GetMaxProcs gets the maximum number of parallels goroutines to render the ANSImage.
func (ai *ANSImage) GetMaxProcs() int {
	return ai.maxprocs
}

func (ai *ANSImage) pixelIndex(y, x int) int {
	return y*ai.w + x
}

func (ai *ANSImage) pixelAt(y, x int) *ansiPixelData {
	return &ai.pixmap[ai.pixelIndex(y, x)]
}

// SetAt sets ANSI-pixel color (RBG) and brightness in coordinates (y,x).
func (ai *ANSImage) SetAt(y, x int, r, g, b, brightness uint8) error {
	if y >= 0 && y < ai.h && x >= 0 && x < ai.w {
		p := ai.pixelAt(y, x)
		p.R = r
		p.G = g
		p.B = b
		p.Brightness = brightness
		return nil
	}
	return ErrOutOfBounds
}

// GetAt gets ANSI-pixel in coordinates (y,x).
func (ai *ANSImage) GetAt(y, x int) (*ANSIpixel, error) {
	if y >= 0 && y < ai.h && x >= 0 && x < ai.w {
		p := ai.pixelAt(y, x)
		return &ANSIpixel{
				R:          p.R,
				G:          p.G,
				B:          p.B,
				Brightness: p.Brightness,
				upper:      (ai.dithering == NoDithering) && (y%2 == 0),
				source:     ai,
			},
			nil
	}
	return nil, ErrOutOfBounds
}

// Render returns the ANSI-compatible string form of ANSImage.
func (ai *ANSImage) Render() string {
	return ai.RenderExt(false, false)
}

// maxRowSize is the per-row upper bound on rendered byte count. A worst-case
// cell is two SGR sequences (each up to 21 bytes in go-code mode: `\\033[..m`)
// plus a 3-byte UTF-8 block character, so 48 bytes is generous. The trailing
// constant covers the row reset (`\\033[0m\\n` = 8 bytes worst case) and the
// optional go-code wrap (`fmt.Print("` + `")\\n` = 14 bytes).
func (ai *ANSImage) maxRowSize() int {
	return ai.w*48 + 24
}

// RenderExt returns the ANSI-compatible string form of ANSImage.
// Can specify if it renders in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
// (Nice info for ANSI True Colour - https://gist.github.com/XVilka/8346728)
func (ai *ANSImage) RenderExt(renderGoCode, disableBgColor bool) string {
	backslashN := "\n"
	backslash033 := ansiEscape(renderGoCode)
	if renderGoCode {
		backslashN = "\\n"
	}

	// nRows is the number of output cell rows; for NoDithering each cell row
	// consumes two pixmap rows (upper + lower).
	nRows := ai.h
	if ai.dithering == NoDithering {
		nRows = ai.h / 2
	}

	if ai.maxprocs == 1 {
		return ai.renderSerial(nRows, renderGoCode, disableBgColor, backslash033, backslashN)
	}
	return ai.renderParallel(nRows, renderGoCode, disableBgColor, backslash033, backslashN)
}

func (ai *ANSImage) renderSerial(nRows int, renderGoCode, disableBgColor bool, backslash033, backslashN string) string {
	buf := make([]byte, 0, nRows*ai.maxRowSize())
	for r := 0; r < nRows; r++ {
		buf = ai.appendRow(buf, r, renderGoCode, disableBgColor, backslash033, backslashN)
	}
	// buf is local and goes out of scope here; nothing else can mutate it.
	return unsafeBytesToString(buf)
}

// renderParallel renders rows concurrently into a single shared backing buffer.
// Each goroutine writes into its own [r*maxRow : (r+1)*maxRow] slot via append
// (capped via 3-index slice so an out-of-bound write would re-allocate that
// goroutine's view, never touching another row's slot). Once all workers are
// done, the slots are compacted left into a contiguous buffer and returned
// as a string aliasing that buffer (see unsafeBytesToString).
func (ai *ANSImage) renderParallel(nRows int, renderGoCode, disableBgColor bool, backslash033, backslashN string) string {
	maxRow := ai.maxRowSize()
	buf := make([]byte, nRows*maxRow)
	rowEnds := make([]int, nRows)

	var wg sync.WaitGroup
	sem := make(chan struct{}, ai.maxprocs)
	for r := 0; r < nRows; r++ {
		wg.Add(1)
		sem <- struct{}{}
		go func(r int) {
			defer wg.Done()
			defer func() { <-sem }()
			start := r * maxRow
			slot := buf[start : start : start+maxRow]
			slot = ai.appendRow(slot, r, renderGoCode, disableBgColor, backslash033, backslashN)
			rowEnds[r] = start + len(slot)
		}(r)
	}
	wg.Wait()

	// Compact: slide each row's content left to remove the gaps between slots.
	// Safe because each row's destination range is at or before its source.
	out := 0
	for r := 0; r < nRows; r++ {
		start := r * maxRow
		n := rowEnds[r] - start
		if out != start {
			copy(buf[out:out+n], buf[start:start+n])
		}
		out += n
	}
	// buf is local and goes out of scope here; nothing else can mutate it.
	return unsafeBytesToString(buf[:out])
}

// unsafeBytesToString reinterprets buf as a string with no copy, the same
// trick strings.Builder.String uses internally. It saves one allocation and
// one full-output memcpy per render — a measurable ~15-20% speedup on the
// render benchmarks.
//
// MAINTAINER CONTRACT: the caller MUST guarantee that buf is never written to
// after this call returns. Strings in Go are required to be immutable; if the
// underlying bytes change, equality comparisons, map lookups, and string
// hashing can silently misbehave.
//
// Safe uses in this file:
//   - renderSerial: buf is a local make([]byte, ...) that goes out of scope
//     immediately after the return; no other reference exists.
//   - renderParallel: same shape; the goroutines that wrote to buf have all
//     joined via wg.Wait() before this call, and buf is local thereafter.
//
// DO NOT use this with any buffer that:
//   - is returned to a sync.Pool,
//   - is reused across renders,
//   - has a slice header escaping to a caller, or
//   - is written to in any way after the conversion.
//
// If any of those become true, replace the call with `string(buf)`.
func unsafeBytesToString(buf []byte) string {
	if len(buf) == 0 {
		return ""
	}
	return unsafe.String(unsafe.SliceData(buf), len(buf))
}

func (ai *ANSImage) appendRow(buf []byte, r int, renderGoCode, disableBgColor bool, backslash033, backslashN string) []byte {
	if renderGoCode {
		buf = appendGoPrintStart(buf)
	}
	if ai.dithering == NoDithering {
		buf = ai.appendNoDitheringRow(buf, r, backslash033, backslashN)
	} else {
		buf = ai.appendDitheringRow(buf, r, backslash033, backslashN, disableBgColor)
	}
	if renderGoCode {
		buf = appendGoPrintEnd(buf)
	}
	return buf
}

// appendNoDitheringRow writes one half-block row, deduplicating SGR escapes:
// the row's leading [0m reset (from the previous row) clears all attributes,
// so the first cell must emit both bg (upper-pixel color) and fg (lower-pixel
// color); subsequent cells skip whichever SGR matches the previously emitted
// one.
func (ai *ANSImage) appendNoDitheringRow(buf []byte, r int, backslash033, backslashN string) []byte {
	py := 2 * r
	upperRow := py * ai.w
	lowerRow := (py + 1) * ai.w

	var prevBgR, prevBgG, prevBgB uint8
	var prevFgR, prevFgG, prevFgB uint8
	haveBg, haveFg := false, false

	for x := 0; x < ai.w; x++ {
		u := ai.pixmap[upperRow+x]
		l := ai.pixmap[lowerRow+x]

		if !haveBg || u.R != prevBgR || u.G != prevBgG || u.B != prevBgB {
			buf = appendANSIColor(buf, backslash033, "48", u.R, u.G, u.B)
			prevBgR, prevBgG, prevBgB = u.R, u.G, u.B
			haveBg = true
		}
		if !haveFg || l.R != prevFgR || l.G != prevFgG || l.B != prevFgB {
			buf = appendANSIColor(buf, backslash033, "38", l.R, l.G, l.B)
			prevFgR, prevFgG, prevFgB = l.R, l.G, l.B
			haveFg = true
		}
		buf = append(buf, lowerHalfBlock...)
	}
	return appendReset(buf, backslash033, backslashN)
}

// appendDitheringRow writes one dither-mode row. The bg color is constant
// for the entire image, so it's emitted exactly once per row (right after
// the previous row's [0m reset cleared state). The fg color is per-pixel
// and dedup'd against the previously emitted fg.
func (ai *ANSImage) appendDitheringRow(buf []byte, r int, backslash033, backslashN string, disableBgColor bool) []byte {
	row := r * ai.w

	if !disableBgColor {
		buf = appendANSIColor(buf, backslash033, "48", ai.bgR, ai.bgG, ai.bgB)
	}

	var prevR, prevG, prevB uint8
	haveFg := false

	for x := 0; x < ai.w; x++ {
		p := ai.pixmap[row+x]
		if !haveFg || p.R != prevR || p.G != prevG || p.B != prevB {
			buf = appendANSIColor(buf, backslash033, "38", p.R, p.G, p.B)
			prevR, prevG, prevB = p.R, p.G, p.B
			haveFg = true
		}
		buf = append(buf, ditherBlock(p.Brightness, ai.dithering)...)
	}
	return appendReset(buf, backslash033, backslashN)
}

// Draw writes the ANSImage to standard output (terminal).
func (ai *ANSImage) Draw() {
	ai.DrawExt(false, false)
}

// DrawExt writes the ANSImage to standard output (terminal).
// Can specify if it prints in form of Go code 'fmt.Printf()'.
// Can specify if background color will be disabled in dithering mode.
func (ai *ANSImage) DrawExt(renderGoCode, disableBgColor bool) {
	fmt.Print(ai.RenderExt(renderGoCode, disableBgColor))
}

// New creates a new empty ANSImage ready to draw on it.
func New(h, w int, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	if (dm == NoDithering) && (h%2 != 0) {
		return nil, ErrHeightNonMoT
	}

	if h < 2 || w < 2 {
		return nil, ErrInvalidBoundsMoT
	}

	r, g, b, _ := bg.RGBA()
	ansimage := &ANSImage{
		h: h, w: w,
		maxprocs:  1,
		bgR:       uint8(r),
		bgG:       uint8(g),
		bgB:       uint8(b),
		dithering: dm,
		pixmap:    make([]ansiPixelData, h*w),
	}

	return ansimage, nil
}

// NewFromImage creates a new ANSImage from an image.Image.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromImage(image image.Image, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	return createANSImage(image, bg, dm)
}

var defaultFilter = imaging.Box

// NewScaledFromImage creates a new scaled ANSImage from an image.Image.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromImage(image image.Image, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	switch sm {
	case ScaleModeResize:
		image = imaging.Resize(image, x, y, defaultFilter)
	case ScaleModeFill:
		image = imaging.Fill(image, x, y, imaging.Center, defaultFilter)
	case ScaleModeFit:
		image = imaging.Fit(image, x, y, defaultFilter)
	default:
		panic(errUnknownScaleMode)
	}

	return createANSImage(image, bg, dm)
}

// NewFromReader creates a new ANSImage from an io.Reader.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromReader(reader io.Reader, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	image, _, err := image.Decode(reader)
	if err != nil {
		return nil, err
	}

	return createANSImage(image, bg, dm)
}

// NewScaledFromReader creates a new scaled ANSImage from an io.Reader.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromReader(reader io.Reader, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	image, _, err := image.Decode(reader)
	if err != nil {
		return nil, err
	}

	switch sm {
	case ScaleModeResize:
		image = imaging.Resize(image, x, y, defaultFilter)
	case ScaleModeFill:
		image = imaging.Fill(image, x, y, imaging.Center, defaultFilter)
	case ScaleModeFit:
		image = imaging.Fit(image, x, y, defaultFilter)
	default:
		panic(errUnknownScaleMode)
	}

	return createANSImage(image, bg, dm)
}

// NewFromFile creates a new ANSImage from a file.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromFile(name string, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	reader, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return NewFromReader(reader, bg, dm)
}

// NewScaledFromFile creates a new scaled ANSImage from a file.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromFile(name string, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	reader, err := os.Open(name)
	if err != nil {
		return nil, err
	}
	defer reader.Close()
	return NewScaledFromReader(reader, y, x, bg, sm, dm)
}

// NewFromURL creates a new ANSImage from an image URL.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewFromURL(url string, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	res, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	if res.StatusCode != http.StatusOK {
		return nil, ErrImageDownloadFailed
	}
	defer res.Body.Close()
	return NewFromReader(res.Body, bg, dm)
}

// NewScaledFromURL creates a new scaled ANSImage from an image URL.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func NewScaledFromURL(url string, y, x int, bg color.Color, sm ScaleMode, dm DitheringMode) (*ANSImage, error) {
	res, err := http.Get(url)
	if err != nil {
		return nil, err
	}
	if res.StatusCode != http.StatusOK {
		return nil, ErrImageDownloadFailed
	}
	defer res.Body.Close()
	return NewScaledFromReader(res.Body, y, x, bg, sm, dm)
}

// ClearTerminal clears current terminal buffer using ANSI escape code.
// (Nice info for ANSI escape codes - https://unix.stackexchange.com/questions/124762/how-does-clear-command-work)
func ClearTerminal() {
	fmt.Print("\033[H\033[2J")
}

// createANSImage loads data from an image and returns an ANSImage.
// Background color is used to fill when image has transparency or dithering mode is enabled.
// Dithering mode is used to specify the way that ANSImage render ANSI-pixels (char/block elements).
func createANSImage(img image.Image, bg color.Color, dm DitheringMode) (*ANSImage, error) {
	var rgbaOut *image.RGBA
	bounds := img.Bounds()

	// do compositing only if background color has no transparency (thank you @disq for the idea!)
	// (info - https://stackoverflow.com/questions/36595687/transparent-pixel-color-go-lang-image)
	//
	// Source point for the img copies is bounds.Min, not (0,0): draw.Draw
	// reads `img.At(p - bounds.Min + sp)` for each destination pixel `p`,
	// so for sub-images (where bounds.Min is non-zero) sp=(0,0) would land
	// outside img's actual data. The uniform-bg fill keeps sp=(0,0) since
	// image.NewUniform has infinite bounds.
	if _, _, _, a := bg.RGBA(); a >= 0xffff {
		rgbaOut = image.NewRGBA(bounds)
		draw.Draw(rgbaOut, bounds, image.NewUniform(bg), image.Point{}, draw.Src)
		draw.Draw(rgbaOut, bounds, img, bounds.Min, draw.Over)
	} else {
		if v, ok := img.(*image.RGBA); ok {
			rgbaOut = v
		} else {
			rgbaOut = image.NewRGBA(bounds)
			draw.Draw(rgbaOut, bounds, img, bounds.Min, draw.Src)
		}
	}

	// Pixel-space bounds of the source. For sub-images returned from
	// img.SubImage, Min may be non-zero; we read from rgbaOut at absolute
	// pixel coordinates and write to the pixmap at zero-based indices.
	yMin, xMin := bounds.Min.Y, bounds.Min.X
	yMax, xMax := bounds.Max.Y, bounds.Max.X

	// Pixmap dimensions, in pixmap-index space.
	h := yMax - yMin
	w := xMax - xMin

	if dm == NoDithering {
		// round up to even number of rows to avoid truncation
		h = (h + 1) & ^1
	} else {
		h = h / BlockSizeY // always sets 1 ANSIPixel block...
		w = w / BlockSizeX // per 8x4 real pixels --> with dithering
	}

	ansimage, err := New(h, w, bg, dm)
	if err != nil {
		return nil, err
	}

	if dm == NoDithering {
		for y := 0; y < h; y++ {
			dstOffset := y * w
			if yMin+y < yMax {
				srcOffset := rgbaOut.PixOffset(xMin, yMin+y)
				for x := 0; x < w; x++ {
					ansimage.pixmap[dstOffset+x] = ansiPixelData{
						R: rgbaOut.Pix[srcOffset],
						G: rgbaOut.Pix[srcOffset+1],
						B: rgbaOut.Pix[srcOffset+2],
					}
					srcOffset += 4
				}
			} else {
				// Pad with background color
				for x := 0; x < w; x++ {
					ansimage.pixmap[dstOffset+x] = ansiPixelData{
						R: ansimage.bgR,
						G: ansimage.bgG,
						B: ansimage.bgB,
					}
				}
			}
		}
	} else {
		const pixelCount = uint32(BlockSizeY * BlockSizeX)

		for y := 0; y < h; y++ {
			for x := 0; x < w; x++ {

				var sumR, sumG, sumB, sumBri uint32
				for dy := 0; dy < BlockSizeY; dy++ {
					py := yMin + BlockSizeY*y + dy
					offset := rgbaOut.PixOffset(xMin+BlockSizeX*x, py)

					for dx := 0; dx < BlockSizeX; dx++ {
						r := rgbaOut.Pix[offset]
						g := rgbaOut.Pix[offset+1]
						b := rgbaOut.Pix[offset+2]
						a := rgbaOut.Pix[offset+3]
						offset += 4

						if a != 0xff {
							r = rgbaComponent(r, a)
							g = rgbaComponent(g, a)
							b = rgbaComponent(b, a)
						}

						sumR += uint32(r)
						sumG += uint32(g)
						sumB += uint32(b)
						sumBri += uint32(luminance(r, g, b))
					}
				}

				r := uint8((sumR + pixelCount/2) / pixelCount)
				g := uint8((sumG + pixelCount/2) / pixelCount)
				b := uint8((sumB + pixelCount/2) / pixelCount)
				brightness := uint8((sumBri + pixelCount/2) / pixelCount)

				ansimage.pixmap[y*w+x] = ansiPixelData{
					Brightness: brightness,
					R:          r,
					G:          g,
					B:          b,
				}
			}
		}
	}

	return ansimage, nil
}
