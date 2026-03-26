package leet_test

import (
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"

	"charm.land/lipgloss/v2"
	"charm.land/lipgloss/v2/compat"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestFrenchFriesChart_UsesProvidedPalette(t *testing.T) {
	palette := []compat.AdaptiveColor{
		{Light: lipgloss.Color("#112233"), Dark: lipgloss.Color("#112233")},
		{Light: lipgloss.Color("#445566"), Dark: lipgloss.Color("#445566")},
		{Light: lipgloss.Color("#778899"), Dark: lipgloss.Color("#778899")},
	}

	chart := leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  8,
		Height: 2,
		Def: &leet.MetricDef{
			Name:       "GPU Utilization",
			Unit:       leet.UnitPercent,
			MinY:       0,
			MaxY:       100,
			Percentage: true,
		},
		Colors: palette,
		Now:    time.Unix(1_700_000_000, 0),
	})

	low := lipgloss.NewStyle().Foreground(palette[0]).Render("█")
	high := lipgloss.NewStyle().Foreground(palette[len(palette)-1]).Render("█")
	require.Equal(t, low, chart.TestColorForValue(0))
	require.Equal(t, high, chart.TestColorForValue(100))
}

func TestFrenchFriesChart_AlignsMetricsByTimestamp(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "GPU Utilization",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		Percentage: true,
	}

	chart := leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  8,
		Height: 2,
		Def:    def,
		Now:    time.Unix(1_700_000_000, 0),
	})

	chart.AddDataPoint("GPU 0", 100, 10)
	chart.AddDataPoint("GPU 1", 100, 90)
	chart.AddDataPoint("GPU 0", 101, 20)
	chart.AddDataPoint("GPU 1", 101, 80)

	require.Equal(t, 2, chart.TestSampleCount(), "same-timestamp samples should share a column")
}

func TestFrenchFriesChart_RetainsHistoryBeyondVisibleWidth(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "GPU Utilization",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		Percentage: true,
	}

	chart := leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  4,
		Height: 3,
		Def:    def,
		Now:    time.Unix(1_700_000_000, 0),
	})

	for i := range 10 {
		chart.AddDataPoint("GPU 0", int64(100+i), float64(i*10))
	}

	require.Equal(t, 10, chart.TestSampleCount())
}

func TestFrenchFriesChart_TruncatedRowsExposeVisibleSeriesInTitle(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "GPU Utilization",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		Percentage: true,
	}

	chart := leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  12,
		Height: 3,
		Def:    def,
		Now:    time.Unix(1_700_000_000, 0),
	})

	for gpu := 0; gpu < 8; gpu++ {
		chart.AddDataPoint("GPU "+strconv.Itoa(gpu), 100, float64(gpu)*10)
	}

	require.Equal(t, []string{"GPU 0", "GPU 7"}, chart.TestVisibleSeries())
	require.Equal(t, "[0,7/8]", chart.TestTitleDetail())
}

func TestFrenchFriesChart_InspectionShowsValuesForWholeColumn(t *testing.T) {
	def := &leet.MetricDef{
		Name:       "GPU Utilization",
		Unit:       leet.UnitPercent,
		MinY:       0,
		MaxY:       100,
		Percentage: true,
	}

	start := time.Unix(1_700_000_000, 0)
	chart := leet.NewFrenchFriesChart(&leet.FrenchFriesChartParams{
		Width:  32,
		Height: 4,
		Def:    def,
		Now:    start,
	})

	ts := start.Unix()
	chart.AddDataPoint("GPU 0", ts, 10)
	chart.AddDataPoint("GPU 1", ts, 50)
	chart.AddDataPoint("GPU 7", ts, 90)
	chart.SetViewWindow(float64(ts-1), float64(ts+1))
	chart.InspectAtDataX(float64(ts))

	view := stripANSI(chart.View())
	lines := strings.Split(view, "\n")
	require.Len(t, lines, 4)
	require.Contains(t, view, "│")
	require.Contains(t, lines[0], "0: 10%")
	require.Contains(t, lines[1], "1: 50%")
	require.Contains(t, lines[2], "7: 90%")
	require.Contains(t, lines[3], start.Local().Format("15:04"))
}

func TestSystemMetricsGrid_CycleFocusedChartMode(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(1)

	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	baseTS := time.Unix(1_700_000_000, 0).Unix()
	for gpu := 0; gpu < 4; gpu++ {
		metric := "gpu." + strconv.Itoa(gpu) + ".gpu"
		grid.AddDataPoint(metric, baseTS, float64(25*(gpu+1)))
	}

	require.True(t, grid.HandleMouseClick(0, 0))
	require.False(t, grid.TestHeatmapModeAt(0, 0))
	require.False(t, grid.TestChartAt(0, 0).IsLogY())

	require.True(t, grid.TestCycleFocusedChartMode())
	require.False(t, grid.TestHeatmapModeAt(0, 0))
	require.True(t, grid.TestChartAt(0, 0).IsLogY())

	require.True(t, grid.TestCycleFocusedChartMode())
	require.True(t, grid.TestHeatmapModeAt(0, 0))
	require.True(t, grid.TestChartAt(0, 0).IsLogY())

	require.True(t, grid.TestCycleFocusedChartMode())
	require.False(t, grid.TestHeatmapModeAt(0, 0))
	require.False(t, grid.TestChartAt(0, 0).IsLogY())
}

func TestSystemMetricsGrid_GPUUtilizationUsesFrenchFriesChart(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(1)

	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	baseTS := time.Unix(1_700_000_000, 0).Unix()
	for gpu := range 4 {
		metric := "gpu." + strconv.Itoa(gpu) + ".gpu"
		grid.AddDataPoint(metric, baseTS, float64(25*gpu))
	}

	chart := grid.TestFrenchFriesChartAt(0, 0)
	require.NotNil(t, chart)
}

func TestSystemMetricsGrid_FrenchFriesUsesConfiguredPalette(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(1)
	_ = cfg.SetSystemCols(1)
	require.NoError(t, cfg.SetFrenchFriesColorScheme("plasma"))

	grid := leet.NewSystemMetricsGrid(
		2*leet.MinMetricChartWidth,
		2*leet.MinMetricChartHeight,
		cfg,
		cfg.SystemGrid,
		leet.NewFocus(),
		leet.NewFilter(),
		logger,
	)

	baseTS := time.Unix(1_700_000_000, 0).Unix()
	for gpu := range 2 {
		metric := "gpu." + strconv.Itoa(gpu) + ".gpu"
		grid.AddDataPoint(metric, baseTS, float64(50*gpu))
	}

	chart := grid.TestFrenchFriesChartAt(0, 0)
	require.NotNil(t, chart)

	palette := leet.FrenchFriesColors("plasma")
	low := lipgloss.NewStyle().Foreground(palette[0]).Render("█")
	high := lipgloss.NewStyle().Foreground(palette[len(palette)-1]).Render("█")
	require.Equal(t, low, chart.TestColorForValue(0))
	require.Equal(t, high, chart.TestColorForValue(100))
}
