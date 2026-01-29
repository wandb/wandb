package leet_test

import (
	"math"
	"regexp"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// stripANSI removes ANSI color/style sequences so we can assert on plain text.
func stripANSI(s string) string {
	re := regexp.MustCompile(`\x1b\[[0-9;]*m`)
	return re.ReplaceAllString(s, "")
}

func seedXY(n int) leet.MetricData {
	xs := make([]float64, n)
	ys := make([]float64, n)
	for i := range n {
		xs[i] = float64(i)
		ys[i] = float64(i + 1)
	}
	return leet.MetricData{X: xs, Y: ys}
}

func TestEpochLineChart_DrawInspectionOverlay_RendersHairlineAndLegend_RightSide(t *testing.T) {
	m := "acc"
	c := leet.NewEpochLineChart(m)
	c.Resize(80, 12)
	c.AddData(m, seedXY(30))
	c.Draw()

	// Inspect near X=5 -> expect legend to the right of the vertical hairline.
	wantX := 5.0
	px := int(math.Round(
		(wantX - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	c.StartInspection(px)
	c.Draw()

	view := stripANSI(c.View())
	lines := strings.Split(view, "\n")

	label := "5: 6" // y = x+1
	found := false
	for _, line := range lines {
		if strings.Contains(line, "│▬▬ "+label) {
			found = true
			break
		}
	}
	require.True(t, found, "expected hairline followed by legend on the right in the same row")
}

func TestInspectAtDataX_SnapsToNearestAndPixel(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(80, 12)

	// Non-uniform X to exercise nearest selection.
	data := leet.MetricData{
		X: []float64{0, 2, 5, 9},
		Y: []float64{10, 20, 50, 90},
	}
	c.AddData(m, data)

	// Domain becomes [0,20] (niceMax), view = [0,20] initially.
	c.Draw()

	// Target X=4 should snap to X=5 (nearest), then hairline snaps to exact pixel for X=5.
	c.InspectAtDataX(4.0)

	x, y, active := c.InspectionData()
	require.True(t, active)
	require.InDelta(t, 5.0, x, 1e-9)
	require.InDelta(t, 50.0, y, 1e-9)

	px, ok := c.TestInspectionMouseX()
	require.True(t, ok)

	// Expected pixel for X=5
	expectPX := int(math.Round(
		(5.0 - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	require.Equal(t, expectPX, px, "hairline should pixel-snap to the exact sample X")
}

func TestInspectAtDataX_NoData_NoActivate(t *testing.T) {
	c := leet.NewEpochLineChart("acc")
	c.Resize(80, 12)
	// No data; should no-op
	c.InspectAtDataX(1.0)
	_, _, active := c.InspectionData()
	require.False(t, active)
}

// When new data expands the X domain (e.g., [0,20] -> [0,30]), the overlay
// should keep pointing at the same data X and move to the correct pixel.
func TestInspection_RepositionsOnXDomainExpansion(t *testing.T) {
	m := "loss"
	c := leet.NewEpochLineChart(m)
	c.Resize(120, 12)

	// Seed 0..19 so nice X domain is [0,20].
	xs := make([]float64, 20)
	ys := make([]float64, 20)
	for i := range xs {
		xs[i] = float64(i)
	}
	c.AddData(m, leet.MetricData{X: xs, Y: ys})
	require.InDelta(t, 20.0, c.ViewMaxX(), 1e-9)

	// Start inspecting at X=10 (middle of initial view).
	wantX := 10.0
	startPX := int(math.Round(
		(wantX - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	c.StartInspection(startPX)

	// Sanity: active and anchored to ~X=10.
	x0, _, active0 := c.InspectionData()
	require.True(t, active0)
	require.InDelta(t, wantX, x0, 1e-9)
	oldPX, _ := c.TestInspectionMouseX()

	// Append 20..29 -> nice view should expand to [0,30].
	c.AddData(m, leet.MetricData{
		X: []float64{20, 21, 22, 23, 24, 25, 26, 27, 28, 29},
		Y: []float64{0, 0, 0, 0, 0, 0, 0, 0, 0, 0},
	})
	require.InDelta(t, 30.0, c.ViewMaxX(), 1e-9)

	// The overlay remains at the same DataX but moves to the new pixel.
	newPX, active1 := c.TestInspectionMouseX()
	require.True(t, active1)
	x1, _, active1B := c.InspectionData()
	require.True(t, active1B)
	require.InDelta(t, wantX, x1, 1e-9)

	expectPX := int(math.Round(
		(wantX - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	require.Equal(t, expectPX, newPX)
	require.Less(t, newPX, oldPX, "overlay should move left as view widens from 20 to 30")
}

// Resizing the chart should also keep the overlay anchored to the same DataX.
func TestInspection_RepositionsOnResize(t *testing.T) {
	m := "acc"
	c := leet.NewEpochLineChart(m)
	c.Resize(80, 12)

	// Seed 0..29 so nice X domain is [0,30].
	xs := make([]float64, 30)
	ys := make([]float64, 30)
	for i := range xs {
		xs[i] = float64(i)
	}
	c.AddData(m, leet.MetricData{X: xs, Y: ys})
	require.InDelta(t, 30.0, c.ViewMaxX(), 1e-9)

	wantX := 15.0
	startPX := int(math.Round(
		(wantX - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	c.StartInspection(startPX)
	oldPX, _ := c.TestInspectionMouseX()

	// Wider chart -> overlay should move proportionally to new width.
	c.Resize(160, 12)

	newPX, active := c.TestInspectionMouseX()
	require.True(t, active)
	x, _, a := c.InspectionData()
	require.True(t, a)
	require.InDelta(t, wantX, x, 1e-9)

	expectPX := int(math.Round(
		(wantX - c.ViewMinX()) / (c.ViewMaxX() - c.ViewMinX()) *
			float64(c.GraphWidth()),
	))
	require.Equal(t, expectPX, newPX)
	require.Greater(t, newPX, oldPX, "overlay should move right when width doubles")
}
