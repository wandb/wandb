package leet_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

func TestEpochLineChart_AddData_CreatesNewSeries(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	require.Equal(t, 0, c.SeriesCount())

	c.AddData("series_a", leet.MetricData{X: []float64{0, 1}, Y: []float64{1, 2}})
	require.Equal(t, 1, c.SeriesCount())

	c.AddData("series_b", leet.MetricData{X: []float64{0, 1}, Y: []float64{3, 4}})
	require.Equal(t, 2, c.SeriesCount())
}

func TestEpochLineChart_AddData_AppendsToExistingSeries(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("series_a", leet.MetricData{X: []float64{0, 1}, Y: []float64{1, 2}})
	require.Equal(t, 1, c.SeriesCount())

	c.AddData("series_a", leet.MetricData{X: []float64{2, 3}, Y: []float64{3, 4}})
	require.Equal(t, 1, c.SeriesCount())

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.InDelta(t, 0.0, xMin, 1e-9)
	require.InDelta(t, 3.0, xMax, 1e-9)
	require.InDelta(t, 1.0, yMin, 1e-9)
	require.InDelta(t, 4.0, yMax, 1e-9)
}

func TestEpochLineChart_AddData_EmptyDataNoOp(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("series_a", leet.MetricData{X: []float64{1}, Y: []float64{10}})
	require.Equal(t, 1, c.SeriesCount())

	// Adding empty data should not change anything.
	c.AddData("series_a", leet.MetricData{X: []float64{}, Y: []float64{}})
	require.Equal(t, 1, c.SeriesCount())

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.InDelta(t, 1.0, xMin, 1e-9)
	require.InDelta(t, 1.0, xMax, 1e-9)
	require.InDelta(t, 10.0, yMin, 1e-9)
	require.InDelta(t, 10.0, yMax, 1e-9)
}

func TestEpochLineChart_AddData_DrawOrder(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("alpha", leet.MetricData{X: []float64{0}, Y: []float64{1}})
	c.AddData("beta", leet.MetricData{X: []float64{0}, Y: []float64{2}})
	c.AddData("gamma", leet.MetricData{X: []float64{0}, Y: []float64{3}})

	order := c.DrawOrder()
	require.Equal(t, []string{"alpha", "beta", "gamma"}, order)
}

func TestEpochLineChart_Bounds_AggregatesAcrossSeries(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	// Series A: X [0,10], Y [5,15]
	c.AddData("A", leet.MetricData{X: []float64{0, 10}, Y: []float64{5, 15}})

	// Series B: X [5,20], Y [-10,20]
	c.AddData("B", leet.MetricData{X: []float64{5, 20}, Y: []float64{-10, 20}})

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.InDelta(t, 0.0, xMin, 1e-9, "xMin should be min of all series")
	require.InDelta(t, 20.0, xMax, 1e-9, "xMax should be max of all series")
	require.InDelta(t, -10.0, yMin, 1e-9, "yMin should be min of all series")
	require.InDelta(t, 20.0, yMax, 1e-9, "yMax should be max of all series")
}

func TestEpochLineChart_RemoveSeries_UpdatesBounds(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	// Series A: X [0,10], Y [0,10]
	c.AddData("A", leet.MetricData{X: []float64{0, 10}, Y: []float64{0, 10}})

	// Series B: X [100,200], Y [100,200]
	c.AddData("B", leet.MetricData{X: []float64{100, 200}, Y: []float64{100, 200}})

	require.Equal(t, 2, c.SeriesCount())
	xMin, xMax, _, _ := c.TestBounds()
	require.InDelta(t, 0.0, xMin, 1e-9)
	require.InDelta(t, 200.0, xMax, 1e-9)

	// Remove series B; bounds should shrink back to A.
	c.RemoveSeries("B")
	require.Equal(t, 1, c.SeriesCount())

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.InDelta(t, 0.0, xMin, 1e-9)
	require.InDelta(t, 10.0, xMax, 1e-9)
	require.InDelta(t, 0.0, yMin, 1e-9)
	require.InDelta(t, 10.0, yMax, 1e-9)
}

func TestEpochLineChart_RemoveSeries_UpdatesDrawOrder(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("alpha", leet.MetricData{X: []float64{0}, Y: []float64{1}})
	c.AddData("beta", leet.MetricData{X: []float64{0}, Y: []float64{2}})
	c.AddData("gamma", leet.MetricData{X: []float64{0}, Y: []float64{3}})

	require.Equal(t, []string{"alpha", "beta", "gamma"}, c.DrawOrder())

	c.RemoveSeries("beta")
	require.Equal(t, []string{"alpha", "gamma"}, c.DrawOrder())
}

func TestEpochLineChart_RemoveSeries_NonExistent(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("A", leet.MetricData{X: []float64{1}, Y: []float64{1}})
	require.Equal(t, 1, c.SeriesCount())

	// Removing a non-existent series should be a no-op.
	c.RemoveSeries("nonexistent")
	require.Equal(t, 1, c.SeriesCount())
	require.Equal(t, []string{"A"}, c.DrawOrder())
}

func TestEpochLineChart_RemoveSeries_AllSeries(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("A", leet.MetricData{X: []float64{1}, Y: []float64{10}})
	c.AddData("B", leet.MetricData{X: []float64{2}, Y: []float64{20}})

	c.RemoveSeries("A")
	c.RemoveSeries("B")

	require.Equal(t, 0, c.SeriesCount())
	require.Empty(t, c.DrawOrder())

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.True(t, math.IsInf(xMin, 1))
	require.True(t, math.IsInf(xMax, -1))
	require.True(t, math.IsInf(yMin, 1))
	require.True(t, math.IsInf(yMax, -1))
}

func TestEpochLineChart_RemoveSeries_ThenAddNewData(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("A", leet.MetricData{X: []float64{0, 100}, Y: []float64{0, 100}})
	c.RemoveSeries("A")

	// Add a new series with smaller bounds.
	c.AddData("B", leet.MetricData{X: []float64{5, 10}, Y: []float64{5, 10}})

	xMin, xMax, yMin, yMax := c.TestBounds()
	require.InDelta(t, 5.0, xMin, 1e-9)
	require.InDelta(t, 10.0, xMax, 1e-9)
	require.InDelta(t, 5.0, yMin, 1e-9)
	require.InDelta(t, 10.0, yMax, 1e-9)
}

func TestEpochLineChart_PromoteSeriesToTop_MovesToEnd(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("A", leet.MetricData{X: []float64{0}, Y: []float64{1}})
	c.AddData("B", leet.MetricData{X: []float64{0}, Y: []float64{2}})
	c.AddData("C", leet.MetricData{X: []float64{0}, Y: []float64{3}})

	require.Equal(t, []string{"A", "B", "C"}, c.DrawOrder())

	// Promote A to top (end of draw order).
	c.PromoteSeriesToTop("A")
	require.Equal(t, []string{"B", "C", "A"}, c.DrawOrder())
}

func TestEpochLineChart_PromoteSeriesToTop_NonExistent(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	c.AddData("A", leet.MetricData{X: []float64{0}, Y: []float64{1}})

	// Promoting a non-existent series should be a no-op.
	c.PromoteSeriesToTop("nonexistent")
	require.Equal(t, []string{"A"}, c.DrawOrder())
}

func TestEpochLineChart_PromoteSeriesToTop_EmptyChart(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(100, 10)

	// Should not panic on empty chart.
	c.PromoteSeriesToTop("A")
	require.Equal(t, 0, c.SeriesCount())
}

func TestEpochLineChart_MultiSeries_ViewRangeCoversAll(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(120, 12)

	// Series with different X ranges.
	c.AddData("early", leet.MetricData{X: []float64{0, 5}, Y: []float64{1, 1}})
	c.AddData("late", leet.MetricData{X: []float64{50, 100}, Y: []float64{1, 1}})

	// View should encompass all data, rounded to nice boundaries.
	require.LessOrEqual(t, c.ViewMinX(), 0.0)
	require.GreaterOrEqual(t, c.ViewMaxX(), 100.0)
}

func TestEpochLineChart_MultiSeries_DrawAfterRemove(t *testing.T) {
	c := leet.NewEpochLineChart("multi")
	c.Resize(80, 12)

	c.AddData("A", leet.MetricData{X: []float64{0, 10}, Y: []float64{1, 5}})
	c.AddData("B", leet.MetricData{X: []float64{5, 15}, Y: []float64{2, 4}})
	c.Draw()

	c.RemoveSeries("A")

	require.NotPanics(t, func() {
		c.Draw()
	})
}
