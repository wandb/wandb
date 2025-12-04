package leet_test

import (
	"math"
	"testing"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
)

// stubColorProvider returns deterministic colors for series creation order.
func stubColorProvider(colors ...string) func() lipgloss.AdaptiveColor {
	i := 0
	return func() lipgloss.AdaptiveColor {
		if len(colors) == 0 {
			return lipgloss.AdaptiveColor{}
		}
		c := colors[i%len(colors)]
		i++
		return lipgloss.AdaptiveColor{Light: c, Dark: c}
	}
}

func TestNewTimeSeriesLineChart_ConstructsAndInitializes(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "CPU",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		AutoRange:  true,
		Percentage: false,
	}
	now := time.Unix(1_700_000_000, 0)

	ch := leet.NewTimeSeriesLineChart(leet.TimeSeriesLineChartParams{
		80, 20,
		def,
		lipgloss.AdaptiveColor{Light: "#FF00FF", Dark: "#FF00FF"}, // base color
		stubColorProvider("#00FF00"),                              // provider for subsequent series
		now,
	})

	require.Equal(t, "CPU (%)", ch.Title())
	require.Equal(t, now, ch.LastUpdate(), "constructor sets last update to now")

	min, max := ch.ValueBounds()
	require.True(t, math.IsInf(min, +1))
	require.True(t, math.IsInf(max, -1))
}

func TestAddDataPoint_DefaultSeries_BookKeeping(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "Mem",
		Unit:       leet.UnitGiB,
		MinY:       0,
		MaxY:       64,
		AutoRange:  true,
		Percentage: false,
	}
	now := time.Unix(1_700_000_000, 0)
	ch := leet.NewTimeSeriesLineChart(leet.TimeSeriesLineChartParams{
		80, 20, def, lipgloss.AdaptiveColor{Light: "#ABCDEF", Dark: "#ABCDEF"}, stubColorProvider(), now})

	// First point
	ts1 := now.Add(-5 * time.Minute).Unix()
	val1 := 12.5
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts1, val1)

	require.Equal(t, time.Unix(ts1, 0), ch.LastUpdate())

	min, max := ch.ValueBounds()
	require.Equal(t, val1, min)
	require.Equal(t, val1, max)
	require.Equal(t, 0, ch.TestSeriesCount(), "Default dataset should not create a named series")

	// Lower value adjusts min only
	ts2 := ts1 + 5
	val2 := 10.0
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts2, val2)
	min, max = ch.ValueBounds()
	require.Equal(t, val2, min)
	require.Equal(t, val1, max)

	// Higher value adjusts max only
	ts3 := ts2 + 5
	val3 := 20.0
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts3, val3)
	min, max = ch.ValueBounds()
	require.Equal(t, val2, min)
	require.Equal(t, val3, max)
	require.Equal(t, time.Unix(ts3, 0), ch.LastUpdate())
}

func TestAddDataPoint_NamedSeries_CreatesSeriesOnDemand(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "CPU",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		AutoRange:  true,
		Percentage: false,
	}
	now := time.Unix(1_700_000_000, 0)
	ch := leet.NewTimeSeriesLineChart(leet.TimeSeriesLineChartParams{
		80, 20, def, lipgloss.AdaptiveColor{Light: "#FF00FF", Dark: "#FF00FF"}, stubColorProvider("#00FF00", "#0000FF"), now})

	ts := now.Unix()
	ch.AddDataPoint("cpu0", ts, 30)
	require.Equal(t, 1, ch.TestSeriesCount(), "first named series should be created")

	ch.AddDataPoint("cpu1", ts+1, 70)
	require.Equal(t, 2, ch.TestSeriesCount(), "second named series should be created")

	// Adding to an existing series should not create more
	ch.AddDataPoint("cpu0", ts+2, 15)
	require.Equal(t, 2, ch.TestSeriesCount(), "reusing series must not change count")

	// Bounds track across all series
	min, max := ch.ValueBounds()
	require.Equal(t, 15.0, min)
	require.Equal(t, 70.0, max)
}
