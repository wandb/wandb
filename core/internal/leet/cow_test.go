package leet

import (
	"math/rand/v2"
	"strings"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func newTestCow() *SphericalCow {
	c := NewSphericalCow()
	c.rng = rand.New(rand.NewPCG(1, 2))
	return c
}

// Pane sizes relative to the sprite (~59x27) and logo (~43x13):
// big fits logo+gap+cow stacked, wide fits only the cow with roam slack.
const (
	bigW, bigH   = 120, 60
	wideW, wideH = 100, 35
)

func TestSphericalCowSpriteHasTransparency(t *testing.T) {
	sprite := cowSprite()

	require.Greater(t, sprite.Width(), 40)
	require.Greater(t, sprite.Height(), 20)

	opaque, blank := 0, 0
	for cy := range sprite.Height() {
		for cx := range sprite.Width() {
			cell := sprite.CellAt(cx, cy)
			if cell == nil || cell.Content == "" || cell.Content == " " {
				blank++
			} else {
				opaque++
			}
		}
	}
	assert.Greater(t, opaque, 500, "cow art should have substance")
	assert.Greater(t, blank, 100, "vacuum should be transparent")
}

func TestSphericalCowLayoutModes(t *testing.T) {
	now := time.Now()
	logoW, logoH := 43, 13

	t.Run("hover", func(t *testing.T) {
		c := newTestCow()
		_, logoY, show := c.Layout(now, bigW, bigH, logoW, logoH)
		require.True(t, show)
		assert.True(t, c.canHover)
		assert.Equal(t, cowHovering, c.mode)
		// The logo shifts up to center the logo+cow ensemble.
		assert.Less(t, logoY, (bigH-logoH)/2)
		// The cow hovers below the logo.
		assert.GreaterOrEqual(t, int(c.y), logoY+logoH)
	})

	t.Run("roam only", func(t *testing.T) {
		c := newTestCow()
		_, logoY, show := c.Layout(now, wideW, wideH, logoW, logoH)
		require.True(t, show)
		assert.False(t, c.canHover)
		assert.True(t, c.canRoam)
		assert.Equal(t, cowRoaming, c.mode)
		// The logo stays centered; the cow floats across it.
		assert.Equal(t, (wideH-logoH)/2, logoY)
	})

	t.Run("hidden", func(t *testing.T) {
		c := newTestCow()
		logoX, logoY, show := c.Layout(now, 80, 24, logoW, logoH)
		assert.False(t, show)
		assert.Equal(t, (80-logoW)/2, logoX)
		assert.Equal(t, (24-logoH)/2, logoY)
	})
}

func TestSphericalCowBounces(t *testing.T) {
	c := newTestCow()
	now := time.Now()
	c.Layout(now, bigW, bigH, 43, 13)

	// Send the cow toward the bottom-right corner at high speed.
	c.mode = cowRoaming
	c.returnAt = now.Add(time.Hour)
	c.vx, c.vy = 40, 20
	c.lastTick = now

	sprite := cowSprite()
	maxX := float64(bigW - sprite.Width())
	maxY := float64(bigH - sprite.Height())

	bouncedX, bouncedY := false, false
	for i := range 100 {
		tick := now.Add(time.Duration(i+1) * cowFrame)
		c.advance(tick)
		c.lastTick = tick

		require.GreaterOrEqual(t, c.x, 0.0)
		require.LessOrEqual(t, c.x, maxX)
		require.GreaterOrEqual(t, c.y, 0.0)
		require.LessOrEqual(t, c.y, maxY)
		bouncedX = bouncedX || c.vx < 0
		bouncedY = bouncedY || c.vy < 0
	}
	assert.True(t, bouncedX, "should have bounced off the right wall")
	assert.True(t, bouncedY, "should have bounced off the bottom wall")
}

func TestSphericalCowRoamsAndReturns(t *testing.T) {
	c := newTestCow()
	now := time.Now()
	c.Layout(now, bigW, bigH, 43, 13)
	require.Equal(t, cowHovering, c.mode)

	// Force an immediate launch.
	c.nextLaunch = now
	now = now.Add(cowFrame)
	c.advance(now)
	require.Equal(t, cowRoaming, c.mode)

	// Force an immediate return and let it fly home.
	c.returnAt = now
	for i := 0; c.mode != cowHovering && i < 2000; i++ {
		c.lastTick = now
		now = now.Add(cowFrame)
		c.advance(now)
	}
	require.Equal(t, cowHovering, c.mode)
	assert.Equal(t, c.anchorX, c.x)
	assert.Equal(t, c.anchorY, c.y)
}

func TestRenderLogoArtWithAndWithoutCow(t *testing.T) {
	// Nil cow (or no room) keeps the plain centered logo.
	static := renderLogoArt(nil, 80, 24)
	assert.Contains(t, static, "█")
	assert.Equal(t, 24, lipgloss.Height(static))

	small := renderLogoArt(newTestCow(), 80, 24)
	assert.Equal(t, static, small, "cow must not alter panes it cannot fit")

	// With room, the composited frame contains both logo and cow cells.
	frame := renderLogoArt(newTestCow(), bigW, bigH)
	assert.Equal(t, bigH, lipgloss.Height(frame))
	assert.Contains(t, frame, "█", "logo visible")
	assert.True(t, strings.ContainsRune(frame, '⣿'), "cow visible")
}
