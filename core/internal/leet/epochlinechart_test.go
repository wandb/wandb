package leet_test

import (
	"math"
	"strings"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
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

// TestEpochLineChart_YLabelsDoNotStack guards against the ntcharts v2.0.1
// regression where drawYLabel forces a label at graphHeight, stacking it
// directly above the previous tick when graphHeight mod yStep is small.
//
// At height 8 the chart has graphHeight=6 and yStep=5, so the buggy
// behavior places labels on rows i=5 and i=6 (adjacent). After the fix
// only rows i=0 and i=5 carry labels.
func TestEpochLineChart_YLabelsDoNotStack(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(80, 8)
	c.AddData(m, leet.MetricData{
		X: []float64{0, 1, 2, 3, 4, 5},
		Y: []float64{4.86, 4.0, 3.0, 2.0, 1.0, 0.5},
	})
	c.Draw()

	lines := strings.Split(stripANSI(c.View()), "\n")
	require.GreaterOrEqual(t, len(lines), 7,
		"expected chart to be at least 7 rows tall")

	// Locate the Y-axis column ('│' for axis, '└' for the bottom-left corner).
	axisCol := -1
	for _, line := range lines {
		if i := strings.IndexAny(line, "│└"); i >= 0 {
			axisCol = i
			break
		}
	}
	require.GreaterOrEqual(t, axisCol, 0, "expected to find Y-axis column")

	// Collect plot rows that carry a non-blank Y label (text left of axis).
	var labeledRows []int
	for r, line := range lines {
		// Skip the X-axis label row, which lives below the axis line and
		// has no Y label of its own.
		if !strings.ContainsAny(line, "│└") {
			continue
		}
		if axisCol > len(line) {
			continue
		}
		if strings.TrimSpace(line[:axisCol]) != "" {
			labeledRows = append(labeledRows, r)
		}
	}
	require.GreaterOrEqual(t, len(labeledRows), 1, "expected at least one Y label")

	for i := 1; i < len(labeledRows); i++ {
		require.Greater(t, labeledRows[i]-labeledRows[i-1], 1,
			"Y labels stacked on adjacent rows %d and %d:\n%s",
			labeledRows[i-1], labeledRows[i], strings.Join(lines, "\n"))
	}
}

// TestEpochLineChart_YLabelsKeepTopTickWhenSpaced verifies that we still
// draw a label at graphHeight when the gap above the previous stepped tick
// is large enough to avoid stacking. Height 13 → graphHeight=11; ticks at
// i=0,5,10 leave a 1-row gap to graphHeight=11 (no top tick), so we test a
// height where the gap >= yStep/2 instead.
func TestEpochLineChart_YLabelsKeepTopTickWhenSpaced(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	// Height 10 → graphHeight=8; stepped ticks at i=0,5; gap to top = 3 >= 3,
	// so a top tick at i=8 is added.
	c.Resize(80, 10)
	c.AddData(m, leet.MetricData{
		X: []float64{0, 1, 2, 3, 4, 5},
		Y: []float64{10, 8, 6, 4, 2, 0},
	})
	c.Draw()

	lines := strings.Split(stripANSI(c.View()), "\n")
	axisCol := -1
	for _, line := range lines {
		if i := strings.IndexAny(line, "│└"); i >= 0 {
			axisCol = i
			break
		}
	}
	require.GreaterOrEqual(t, axisCol, 0)

	var labeledRows []int
	for r, line := range lines {
		if !strings.ContainsAny(line, "│└") {
			continue
		}
		if axisCol <= len(line) && strings.TrimSpace(line[:axisCol]) != "" {
			labeledRows = append(labeledRows, r)
		}
	}
	require.GreaterOrEqual(t, len(labeledRows), 3,
		"expected at least 3 Y labels (top + middle + bottom):\n%s",
		strings.Join(lines, "\n"))
	// And still no stacking.
	for i := 1; i < len(labeledRows); i++ {
		require.Greater(t, labeledRows[i]-labeledRows[i-1], 1,
			"Y labels stacked on rows %d and %d", labeledRows[i-1], labeledRows[i])
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

func TestEpochLineChart_ToggleYScale_RejectsNonPositiveOnlyData(t *testing.T) {
	c := leet.NewEpochLineChart("loss")
	c.Resize(80, 12)
	c.AddData("run", leet.MetricData{
		X: []float64{0, 1, 2},
		Y: []float64{-3, 0, -1},
	})

	require.False(t, c.TestIsLogY())
	require.False(t, c.ToggleYScale())
	require.False(t, c.TestIsLogY())
}

func TestEpochLineChart_LogY_FormatsTicksInRawUnits(t *testing.T) {
	c := leet.NewEpochLineChart("loss")
	c.Resize(80, 12)
	c.AddData("run", leet.MetricData{
		X: []float64{0, 1, 2},
		Y: []float64{0.1, 1, 10},
	})

	require.True(t, c.ToggleYScale())
	require.True(t, c.TestIsLogY())
	require.Equal(t, "0.1", c.TestFormatYTick(-1))
	require.Equal(t, "1", c.TestFormatYTick(0))
	require.Equal(t, "10", c.TestFormatYTick(1))
}

func TestTimeSeriesLineChart_LogY_FormatsTicksWithMetricUnits(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "CPU",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		AutoRange:  true,
		Percentage: true,
	}

	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		Width:  80,
		Height: 20,
		Def:    def,
		BaseColor: leet.AdaptiveColor{
			Light: lipgloss.Color("#FF00FF"),
			Dark:  lipgloss.Color("#FF00FF"),
		},
		ColorProvider: stubColorProvider("#00FF00"),
		Now:           time.Unix(1_700_000_000, 0),
	})

	ch.AddDataPoint("", 1, 0.1)
	ch.AddDataPoint("", 2, 10)

	require.True(t, ch.ToggleYScale())
	require.True(t, ch.TestIsLogY())
	require.Equal(t, "10%", ch.TestFormatYTick(1))
}
