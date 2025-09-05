package leet_test

import (
	"math"
	"testing"

	leet "github.com/wandb/wandb/core/internal/leet"
)

func TestEpochLineChart_RangeAndReset(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(100, 10, 0, "loss")

	// Add a couple of points; Y padding should expand range.
	c.AddDataPoint(0.5)
	c.AddDataPoint(1.0)

	if c.ViewMinY() >= 0.5 {
		t.Fatalf("expected ViewMinY < 0.5 due to padding, got %v", c.ViewMinY())
	}
	if c.ViewMaxY() <= 1.0 {
		t.Fatalf("expected ViewMaxY > 1.0 due to padding, got %v", c.ViewMaxY())
	}

	// Force X-range to expand in rounded tens (0..30) once we exceed 20 steps.
	for i := 0; i < 21; i++ {
		c.AddDataPoint(float64(i))
	}
	if maxX := c.MaxX(); math.Abs(maxX-30) > 1e-9 {
		t.Fatalf("expected MaxX≈30 after 21 steps, got %v", maxX)
	}
	if vmin, vmax := c.ViewMinX(), c.ViewMaxX(); vmin != 0 || math.Abs(vmax-30) > 1e-9 {
		t.Fatalf("expected view X range [0,30], got [%v,%v]", vmin, vmax)
	}

	// Reset should restore defaults and clear zoom state.
	c.Reset()
	if minY, maxY := c.MinY(), c.MaxY(); minY != 0 || maxY != 1 {
		t.Fatalf("expected Y range [0,1] after reset, got [%v,%v]", minY, maxY)
	}
	if vmin, vmax := c.ViewMinX(), c.ViewMaxX(); vmin != 0 || vmax != 20 {
		t.Fatalf("expected view X range [0,20] after reset, got [%v,%v]", vmin, vmax)
	}
}

func TestEpochLineChart_ZoomClampsAndAnchors(t *testing.T) {
	t.Parallel()

	c := leet.NewEpochLineChart(120, 12, 0, "acc")
	for i := range 40 {
		c.AddDataPoint(0.1 + 0.02*float64(i))
	}
	oldMin, oldMax := c.ViewMinX(), c.ViewMaxX()
	oldRange := oldMax - oldMin

	// Zoom in around the middle of the graph.
	mouseX := c.GraphWidth() / 2
	c.HandleZoom("in", mouseX)

	newMin, newMax := c.ViewMinX(), c.ViewMaxX()
	newRange := newMax - newMin
	if !(newRange < oldRange) {
		t.Fatalf("expected zoom-in to reduce range, old=%v new=%v", oldRange, newRange)
	}

	// Zoom out should expand range but never exceed maxSteps.
	c.HandleZoom("out", mouseX)
	outMin, outMax := c.ViewMinX(), c.ViewMaxX()
	if !(outMax-outMin >= newRange) {
		t.Fatalf("expected zoom-out to increase range, got [%v,%v] vs newRange=%v", outMin, outMax, newRange)
	}
}
