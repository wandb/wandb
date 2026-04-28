package picture

import (
	"image"
	"image/color"
	"image/draw"
)

// composite returns an image with bg filled and src drawn over it.
// For color.Transparent it short-circuits and returns src unchanged.
func composite(src image.Image, bg color.Color) image.Image {
	if _, _, _, a := bg.RGBA(); a == 0 {
		return src
	}
	bounds := src.Bounds()
	out := image.NewRGBA(bounds)
	draw.Draw(out, bounds, &image.Uniform{C: bg}, image.Point{}, draw.Src)
	draw.Draw(out, bounds, src, bounds.Min, draw.Over)
	return out
}
