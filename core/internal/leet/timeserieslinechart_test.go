package leet_test

import (
	"math"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
)

// stubColorProvider returns deterministic colors for series creation order.
func stubColorProvider(colors ...string) func() compat.AdaptiveColor {
	i := 0
	return func() compat.AdaptiveColor {
		if len(colors) == 0 {
			return compat.AdaptiveColor{}
		}
		c := colors[i%len(colors)]
		i++
		return compat.AdaptiveColor{
			Light: lipgloss.Color(c), Dark: lipgloss.Color(c)}
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

	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		80, 20,
		def,
		compat.AdaptiveColor{
			Light: lipgloss.Color("#FF00FF"), Dark: lipgloss.Color("#FF00FF")}, // base color
		stubColorProvider("#00FF00"), // provider for subsequent series
		now,
	})

	require.Equal(t, "CPU (%)", ch.Title())
	require.Equal(t, now, ch.LastUpdate(), "constructor sets last update to now")

	minimum, maximum := ch.ValueBounds()
	require.True(t, math.IsInf(minimum, +1))
	require.True(t, math.IsInf(maximum, -1))
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
	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		80, 20, def, compat.AdaptiveColor{
			Light: lipgloss.Color("#ABCDEF"), Dark: lipgloss.Color("#ABCDEF")},
		stubColorProvider(), now})

	// First point
	ts1 := now.Add(-5 * time.Minute).Unix()
	val1 := 12.5
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts1, val1)

	require.Equal(t, time.Unix(ts1, 0), ch.LastUpdate())

	minimum, maximum := ch.ValueBounds()
	require.Equal(t, val1, minimum)
	require.Equal(t, val1, maximum)
	require.Equal(t, 0, ch.TestSeriesCount(), "Default dataset should not create a named series")

	// Lower value adjusts min only
	ts2 := ts1 + 5
	val2 := 10.0
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts2, val2)
	minimum, maximum = ch.ValueBounds()
	require.Equal(t, val2, minimum)
	require.Equal(t, val1, maximum)

	// Higher value adjusts max only
	ts3 := ts2 + 5
	val3 := 20.0
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, ts3, val3)
	minimum, maximum = ch.ValueBounds()
	require.Equal(t, val2, minimum)
	require.Equal(t, val3, maximum)
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
	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		80, 20, def,
		compat.AdaptiveColor{
			Light: lipgloss.Color("#FF00FF"), Dark: lipgloss.Color("#FF00FF")},
		stubColorProvider("#00FF00", "#0000FF"), now})

	ts := now.Unix()
	ch.AddDataPoint("cpu0", ts, 30)
	require.Equal(t, 1, ch.TestSeriesCount(), "first named series should be created")

	ch.AddDataPoint("cpu1", ts+1, 70)
	require.Equal(t, 2, ch.TestSeriesCount(), "second named series should be created")

	// Adding to an existing series should not create more
	ch.AddDataPoint("cpu0", ts+2, 15)
	require.Equal(t, 2, ch.TestSeriesCount(), "reusing series must not change count")

	// Bounds track across all series
	minimum, maximum := ch.ValueBounds()
	require.Equal(t, 15.0, minimum)
	require.Equal(t, 70.0, maximum)
}

func TestFormatXAxisTick_NarrowSystemChartsKeepEndpointLabels(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "Apple E-cores Freq",
		Unit:       leet.UnitMHz,
		MinY:       0,
		MaxY:       3000,
		AutoRange:  true,
		Percentage: false,
	}
	now := time.Unix(1_700_000_000, 0)
	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		Width:  leet.MinMetricChartWidth,
		Height: 8,
		Def:    def,
		BaseColor: compat.AdaptiveColor{
			Light: lipgloss.Color("#FF00FF"), Dark: lipgloss.Color("#FF00FF")},
		ColorProvider: stubColorProvider("#00FF00"),
		Now:           now,
	})

	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, now.Add(-10*time.Minute).Unix(), 990)
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, now.Unix(), 1100)

	viewMin, viewMax := ch.TestViewRange()
	mid := (viewMin + viewMax) / 2

	require.Empty(t, ch.TestFormatXAxisTick(mid, 3),
		"narrow charts should suppress interior labels")

	left := ch.TestFormatXAxisTick(viewMin, 3)
	right := ch.TestFormatXAxisTick(viewMax, 3)
	require.NotEmpty(t, left)
	require.NotEmpty(t, right)
	require.NotEqual(t, "...", left)
	require.NotEqual(t, "...", right)
	require.Regexp(t, `^\d{2}:?\d{2}$`, left)
	require.Regexp(t, `^\d{2}:?\d{2}$`, right)
}

func TestFormatXAxisTick_WideSystemChartsKeepInteriorLabels(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "CPU",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		AutoRange:  true,
		Percentage: false,
	}
	now := time.Unix(1_700_000_000, 0)
	ch := leet.NewTimeSeriesLineChart(&leet.TimeSeriesLineChartParams{
		Width:  80,
		Height: 12,
		Def:    def,
		BaseColor: compat.AdaptiveColor{
			Light: lipgloss.Color("#FF00FF"), Dark: lipgloss.Color("#FF00FF")},
		ColorProvider: stubColorProvider("#00FF00"),
		Now:           now,
	})

	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, now.Add(-10*time.Minute).Unix(), 10)
	ch.AddDataPoint(leet.DefaultSystemMetricSeriesName, now.Unix(), 20)

	viewMin, viewMax := ch.TestViewRange()
	mid := (viewMin + viewMax) / 2

	label := ch.TestFormatXAxisTick(mid, 6)
	require.NotEmpty(t, label)
	require.NotEqual(t, "...", label)
	require.Regexp(t, `^\d{2}:?\d{2}$`, label)
}
