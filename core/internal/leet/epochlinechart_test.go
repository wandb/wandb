package leet_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/require"

	leet "github.com/wandb/wandb/core/internal/leet"
)

func TestEpochLineChart_Range(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(100, 10)

	// Add a couple of points; Y padding should expand range.
	c.AddData(m, leet.MetricData{X: []float64{0, 1}, Y: []float64{0.5, 1.0}})

	require.Less(t, c.ViewMinY(), 0.5)
	require.Greater(t, c.ViewMaxY(), 1.0)

	// Force X-range to expand in rounded tens (0..30) once we exceed 20 steps.
	for i := range 21 {
		c.AddData(m, leet.MetricData{
			X: []float64{float64(i + 2)},
			Y: []float64{float64(i)},
		})
	}
	// Expecting MaxX≈30 after 21 steps.
	require.LessOrEqual(t, math.Abs(c.MaxX()-30), 1e-9)
	// Expecting view range to be [0, 30].
	require.NotEqual(t, c.ViewMinX(), 0)
	require.LessOrEqual(t, math.Abs(c.ViewMaxX()-30), 1e-9)
}

func TestEpochLineChart_ZoomClampsAndAnchors(t *testing.T) {
	m := "acc"
	c := leet.NewEpochLineChart(m)
	c.Resize(120, 12)
	for i := range 40 {
		c.AddData(m, leet.MetricData{
			X: []float64{float64(i)},
			Y: []float64{0.1 + 0.02*float64(i)},
		})
	}
	oldMin, oldMax := c.ViewMinX(), c.ViewMaxX()
	oldRange := oldMax - oldMin

	// Zoom in around the middle of the graph - should NOT snap to tail.
	mouseX := c.GraphWidth() / 2
	c.HandleZoom("in", mouseX)

	newMin, newMax := c.ViewMinX(), c.ViewMaxX()
	newRange := newMax - newMin

	// Verify zoom reduced range.
	require.Less(t, newRange, oldRange)

	// Verify we're still centered around the middle (not snapped to tail).
	midPoint := (newMin + newMax) / 2
	expectedMid := (oldMin + oldMax) / 2
	tolerance := oldRange * 0.2 // Allow some movement but not a full snap
	require.LessOrEqual(t, math.Abs(midPoint-expectedMid), tolerance)

	// Test zoom at right edge - should maintain tail visibility.
	c.SetViewXRange(30, 40)              // Position at tail
	c.HandleZoom("in", c.GraphWidth()-1) // Mouse at far right

	// Should still see the last data point (39).
	require.GreaterOrEqual(t, c.ViewMaxX(), 39.0)
}

// When zooming away from the right edge (and not already at the tail),
// the view should NOT jump to the tail.
func TestEpochLineChart_ZoomDoesNotSnapToTailAwayFromRight(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(120, 12)
	for i := range 40 {
		c.AddData(m, leet.MetricData{
			X: []float64{float64(i)},
			Y: []float64{float64(i)},
		})
	}
	// Sanity: initial view is [0, 40] with data tail at x≈39.

	mouseX := c.GraphWidth() / 4 // left-ish
	c.HandleZoom("in", mouseX)

	// If the view wrongly snapped to the tail, ViewMaxX would be ~39.
	require.Greater(t, math.Abs(c.ViewMaxX()-39.0), 0.75)
}

// When zooming near the right edge, we still anchor to the tail.
func TestEpochLineChart_ZoomNearRightAnchorsToTail(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(120, 12)
	for i := range 40 {
		c.AddData(m, leet.MetricData{
			X: []float64{float64(i)},
			Y: []float64{0.5},
		})
	}

	mouseX := int(float64(c.GraphWidth()) * 0.95) // near right edge
	c.HandleZoom("in", mouseX)

	// Expect the right edge to be close to the last data point (~39).
	require.Less(t, math.Abs(c.ViewMaxX()-39.0), 1.0)
}

func TestTruncateTitle(t *testing.T) {
	tests := []struct {
		name     string
		title    string
		maxWidth int
		want     string
	}{
		{
			name:     "fits within max width",
			title:    "short",
			maxWidth: 10,
			want:     "short",
		},
		{
			name:     "needs basic truncation",
			title:    "this is a very long title",
			maxWidth: 10,
			want:     "this is...",
		},
		{
			name:     "truncates at separator",
			title:    "path/to/file/document.txt",
			maxWidth: 15,
			want:     "path/to/file...",
		},
		{
			name:     "tiny max width",
			title:    "title",
			maxWidth: 3,
			want:     "...",
		},
		{
			name:     "empty string",
			title:    "",
			maxWidth: 10,
			want:     "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := leet.TruncateTitle(tt.title, tt.maxWidth)
			require.Equal(t, got, tt.want)
		})
	}
}

func TestFormatXAxisTick(t *testing.T) {
	tests := []struct {
		name     string
		value    float64
		maxWidth int
		want     string
	}{
		// Special values
		{"zero", 0, 0, "0"},
		{"NaN", math.NaN(), 0, ""},
		{"positive infinity", math.Inf(1), 0, ""},
		{"negative infinity", math.Inf(-1), 0, ""},

		// Small integers (no suffix)
		{"one", 1, 0, "1"},
		{"small", 42, 0, "42"},
		{"hundred", 100, 0, "100"},
		{"max before k", 999, 0, "999"},

		// Thousands (k)
		{"exactly 1k", 1000, 0, "1k"},
		{"1.5k", 1500, 0, "1.5k"},
		{"fractional k", 1234, 0, "1.23k"},
		{"large k", 50000, 0, "50k"},
		{"max k", 999000, 0, "999k"},
		{"high precision k", 999600, 0, "999.6k"},

		// Millions (M)
		{"exactly 1M", 1e6, 0, "1M"},
		{"1.2M", 1.2e6, 0, "1.2M"},
		{"fractional M", 1234567, 0, "1.23M"},
		{"high precision M", 999.95e6, 0, "999.95M"},

		// Billions (G)
		{"exactly 1G", 1e9, 0, "1G"},
		{"2.5G", 2.5e9, 0, "2.5G"},

		// Trillions (T)
		{"exactly 1T", 1e12, 0, "1T"},

		// Negative values
		{"negative small", -42, 0, "-42"},
		{"negative k", -1500, 0, "-1.5k"},
		{"negative M", -1.2e6, 0, "-1.2M"},

		// Boundary bump: rounding at 2 decimals produces "1000"
		{"999.9996k bumps to M", 999999.6, 0, "1M"},
		{"999.9996M bumps to G", 999999.6e3, 0, "1G"},

		// Width constraints
		{"width forces fewer decimals", 1234, 4, "1.2k"},
		{"width forces integer", 1234, 3, "1k"},
		{"width allows full precision", 1234, 10, "1.23k"},
		{"negative with width", -1234, 5, "-1.2k"},

		// Width-constrained bump: reduction to 0 decimals triggers bump
		{"width causes bump", 999600, 4, "1M"},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := leet.FormatXAxisTick(tt.value, tt.maxWidth)
			require.Equal(t, tt.want, got)
		})
	}
}
