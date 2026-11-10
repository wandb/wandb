// The half-block encoder is adapted from pixterm's pkg/ansimage renderer:
// https://github.com/eliukblau/pixterm
// https://github.com/NimbleMarkets/pixterm/blob/dc18ac6c1a0f/pkg/ansimage/ansimage.go
// In particular, appendGlyph follows appendNoDitheringRow's color-change
// suppression and row resets, with direct image access and reusable storage.
//
// Copyright 2017 Eliuk Blau
// Copyright (c) 2026 Neomantra Corp
//
// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

package picture

import (
	"image"
	"strconv"
)

// appendGlyph encodes an already fitted, even-height image as half-blocks:
// upper pixel as background, lower pixel as foreground, and a reset at each
// row boundary. Pixel RGB is alpha-premultiplied; prepareSource has already
// composited Background.
// Keeping this small encoder here lets Model reuse its output buffer without
// exposing mutable storage through returned View strings.
// It panics if the image height is odd; callers must prepare complete pairs
// of pixel rows (View does this with a 1x2 cell size).
func appendGlyph(buf []byte, src image.Image) []byte {
	bounds := src.Bounds()
	if bounds.Dy()%2 != 0 {
		panic("picture: appendGlyph requires an even-height prepared image")
	}
	// Two true-color SGRs (19 bytes each) and a three-byte half block per cell.
	size := bounds.Dx()*bounds.Dy()/2*41 + bounds.Dy()/2*5
	if cap(buf) < size {
		buf = make([]byte, 0, size)
	}
	rgba, isRGBA := src.(*image.RGBA)
	for y := bounds.Min.Y; y < bounds.Max.Y; y += 2 {
		var prevUpper, prevLower [3]byte
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			var upper, lower [3]byte
			if isRGBA {
				i := rgba.PixOffset(x, y)
				j := i + rgba.Stride
				upper = [3]byte{rgba.Pix[i], rgba.Pix[i+1], rgba.Pix[i+2]}
				lower = [3]byte{rgba.Pix[j], rgba.Pix[j+1], rgba.Pix[j+2]}
			} else {
				r, g, b, _ := src.At(x, y).RGBA()
				upper = [3]byte{byte(r >> 8), byte(g >> 8), byte(b >> 8)}
				r, g, b, _ = src.At(x, y+1).RGBA()
				lower = [3]byte{byte(r >> 8), byte(g >> 8), byte(b >> 8)}
			}
			if x == bounds.Min.X || upper != prevUpper {
				buf = appendGlyphColor(buf, "\x1b[48;2;", upper)
			}
			if x == bounds.Min.X || lower != prevLower {
				buf = appendGlyphColor(buf, "\x1b[38;2;", lower)
			}
			buf = append(buf, "▄"...)
			prevUpper, prevLower = upper, lower
		}
		buf = append(buf, "\x1b[0m"...)
		if y+2 < bounds.Max.Y {
			buf = append(buf, '\n')
		}
	}
	return buf
}

func appendGlyphColor(buf []byte, prefix string, rgb [3]byte) []byte {
	buf = append(buf, prefix...)
	for i, v := range rgb {
		if i != 0 {
			buf = append(buf, ';')
		}
		buf = strconv.AppendUint(buf, uint64(v), 10)
	}
	return append(buf, 'm')
}
