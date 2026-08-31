package leet

import (
	"image"
	"image/color"
	"image/png"
	"os"
	"testing"

	"github.com/NimbleMarkets/ntcharts/v2/picture"
	"github.com/stretchr/testify/require"
)

// The frame shown between toggling to Kitty mode and the Kitty image being
// encoded must match the Glyph view exactly. A mismatch shows up as a flash
// of black letterbox bars or a jump in image position on every mode switch.
func TestMediaImageRenderer_KittyTransitionalFrameMatchesGlyph(t *testing.T) {
	t.Setenv("TERM", "xterm-kitty")
	picture.ForceKittyCapability(picture.KittyCapabilitySupported)

	path := t.TempDir() + "/img.png"
	img := image.NewRGBA(image.Rect(0, 0, 64, 48))
	for y := range 48 {
		for x := range 64 {
			img.Set(x, y, color.RGBA{R: 255, A: 255})
		}
	}
	f, err := os.Create(path)
	require.NoError(t, err)
	require.NoError(t, png.Encode(f, img))
	require.NoError(t, f.Close())

	r := newMediaImageRenderer()
	key := mediaRenderKey{path: path, width: 30, height: 10}
	glyph := r.Render(path, key.width, key.height)
	require.NotContains(t, glyph, "Empty image")

	r.ToggleMode()
	r.PrepareVisible([]mediaRenderKey{key})

	// The Kitty encode command returned by PrepareVisible never runs here,
	// so Render returns the transitional fallback.
	transitional := r.Render(path, key.width, key.height)
	require.Equal(t, glyph, transitional)
}
