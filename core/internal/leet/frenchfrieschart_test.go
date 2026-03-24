package leet_test

import (
	"path/filepath"
	"strconv"
	"testing"
	"time"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

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

	require.Equal(t, []string{"GPU 0", "GPU 1", "GPU 7"}, chart.TestVisibleSeries())
	require.Equal(t, "[0,1,7/8]", chart.TestTitleDetail())
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
	for gpu := 0; gpu < 4; gpu++ {
		metric := "gpu." + strconv.Itoa(gpu) + ".gpu"
		grid.AddDataPoint(metric, baseTS, float64(25*gpu))
	}

	chart := grid.TestFrenchFriesChartAt(0, 0)
	require.NotNil(t, chart)
	require.Nil(t, grid.TestChartAt(0, 0),
		"GPU utilization should no longer use a line chart")
}
