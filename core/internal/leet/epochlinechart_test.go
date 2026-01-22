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
	c.AddData(leet.MetricData{X: []float64{0, 1}, Y: []float64{0.5, 1.0}})

	require.Less(t, c.ViewMinY(), 0.5)
	require.Greater(t, c.ViewMaxY(), 1.0)

	// Force X-range to expand in rounded tens (0..30) once we exceed 20 steps.
	for i := range 21 {
		c.AddData(leet.MetricData{
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
		c.AddData(leet.MetricData{
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
		c.AddData(leet.MetricData{
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
		c.AddData(leet.MetricData{
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
