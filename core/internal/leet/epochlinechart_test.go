package leet_test

import (
	"math"
	"testing"

	leet "github.com/wandb/wandb/core/internal/leet"
)

func TestEpochLineChart_Range(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(100, 10, 0, "loss")

	// Add a couple of points; Y padding should expand range.
	c.AddPoint(0, 0.5)
	c.AddPoint(1, 1.0)

	if c.ViewMinY() >= 0.5 {
		t.Fatalf("expected ViewMinY < 0.5 due to padding, got %v", c.ViewMinY())
	}
	if c.ViewMaxY() <= 1.0 {
		t.Fatalf("expected ViewMaxY > 1.0 due to padding, got %v", c.ViewMaxY())
	}

	// Force X-range to expand in rounded tens (0..30) once we exceed 20 steps.
	for i := range 21 {
		c.AddPoint(float64(i+2), float64(i))
	}
	if maxX := c.MaxX(); math.Abs(maxX-30) > 1e-9 {
		t.Fatalf("expected MaxX≈30 after 21 steps, got %v", maxX)
	}
	if vmin, vmax := c.ViewMinX(), c.ViewMaxX(); vmin != 0 || math.Abs(vmax-30) > 1e-9 {
		t.Fatalf("expected view X range [0,30], got [%v,%v]", vmin, vmax)
	}
}

func TestEpochLineChart_ZoomClampsAndAnchors(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(120, 12, 0, "acc")
	for i := range 40 {
		c.AddPoint(float64(i), 0.1+0.02*float64(i))
	}
	oldMin, oldMax := c.ViewMinX(), c.ViewMaxX()
	oldRange := oldMax - oldMin

	// Zoom in around the middle of the graph - should NOT snap to tail
	mouseX := c.GraphWidth() / 2
	c.HandleZoom("in", mouseX)

	newMin, newMax := c.ViewMinX(), c.ViewMaxX()
	newRange := newMax - newMin

	// Verify zoom reduced range
	if !(newRange < oldRange) {
		t.Fatalf("expected zoom-in to reduce range, old=%v new=%v", oldRange, newRange)
	}

	// Verify we're still centered around the middle (not snapped to tail)
	midPoint := (newMin + newMax) / 2
	expectedMid := (oldMin + oldMax) / 2
	tolerance := oldRange * 0.2 // Allow some movement but not a full snap
	if math.Abs(midPoint-expectedMid) > tolerance {
		t.Fatalf("zoom incorrectly snapped away from center: mid=%v expected=%v", midPoint, expectedMid)
	}

	// Test zoom at right edge - should maintain tail visibility
	c.SetViewXRange(30, 40)              // Position at tail
	c.HandleZoom("in", c.GraphWidth()-1) // Mouse at far right

	_, tailMax := c.ViewMinX(), c.ViewMaxX()
	// Should still see the last data point (39)
	if tailMax < 39 {
		t.Fatalf("zoom lost tail visibility: max=%v, expected >= 39", tailMax)
	}
}

// When zooming away from the right edge (and not already at the tail),
// the view should NOT jump to the tail.
func TestEpochLineChart_ZoomDoesNotSnapToTailAwayFromRight(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(120, 12, 0, "loss")
	for i := range 40 {
		c.AddPoint(float64(i), float64(i))
	}
	// Sanity: initial view is [0, 40] with data tail at x≈39.

	mouseX := c.GraphWidth() / 4 // left-ish
	c.HandleZoom("in", mouseX)

	// If the view wrongly snapped to the tail, ViewMaxX would be ~39±ε.
	if diff := math.Abs(c.ViewMaxX() - 39.0); diff < 0.75 {
		t.Fatalf("unexpected snap to tail: ViewMaxX=%v (diff=%v)", c.ViewMaxX(), diff)
	}
}

// When zooming near the right edge, we still anchor to the tail.
func TestEpochLineChart_ZoomNearRightAnchorsToTail(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(120, 12, 0, "loss")
	for i := range 40 {
		c.AddPoint(float64(i), 0.5)
	}

	mouseX := int(float64(c.GraphWidth()) * 0.95) // near right edge
	c.HandleZoom("in", mouseX)

	// Expect the right edge to be close to the last data point (~39).
	if diff := math.Abs(c.ViewMaxX() - 39.0); diff > 1.0 {
		t.Fatalf("expected right edge near tail (~39), got %v (diff=%v)", c.ViewMaxX(), diff)
	}
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
			if got != tt.want {
				t.Errorf("TruncateTitle(%q, %d) = %q, want %q", tt.title, tt.maxWidth, got, tt.want)
			}
		})
	}
}
