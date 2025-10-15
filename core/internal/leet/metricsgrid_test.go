package leet_test

import (
	"path/filepath"
	"strings"
	"testing"

	tea "github.com/charmbracelet/bubbletea"
	leet "github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestCalculateChartDimensions_RespectsMinimums(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	m := leet.NewMetricsGrid(cfg, &leet.FocusState{}, logger)
	d := m.CalculateChartDimensions(30, 10) // small on purpose
	if d.ChartWidth < leet.MinChartWidth {
		t.Fatalf("ChartWidth=%d < MinChartWidth=%d", d.ChartWidth, leet.MinChartWidth)
	}
	if d.ChartHeight < leet.MinChartHeight {
		t.Fatalf("ChartHeight=%d < MinChartHeight=%d", d.ChartHeight, leet.MinChartHeight)
	}
}

func TestModelView_TruncatesLongTitles(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	m := leet.NewModel("dummy", cfg, logger)

	// Establish terminal size first so new charts get reasonable dims.
	if tm, _ := m.Update(tea.WindowSizeMsg{Width: 60, Height: 20}); tm != nil {
		m = tm.(*leet.Model)
	}

	// Add one long-titled metric to force truncation inside a narrow cell.
	long := "this/is/a/very/long/title/that/should/truncate"
	if tm, _ := m.Update(leet.HistoryMsg{Metrics: map[string]float64{long: 1.0}}); tm != nil {
		m = tm.(*leet.Model)
	}

	out := m.View()
	if !strings.Contains(out, "...") {
		t.Fatalf("expected truncated title with ellipsis in View(); got:\n%s", out)
	}
}

func TestModelView_ChartsAreSortedAlphabetically(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	m := leet.NewModel("dummy", cfg, logger)

	if tm, _ := m.Update(tea.WindowSizeMsg{Width: 120, Height: 40}); tm != nil {
		m = tm.(*leet.Model)
	}

	// Send metrics out of order; model should sort charts by title.
	msg := leet.HistoryMsg{
		Metrics: map[string]float64{
			"zeta":  1,
			"alpha": 1,
			"beta":  1,
		},
	}
	if tm, _ := m.Update(msg); tm != nil {
		m = tm.(*leet.Model)
	}

	out := m.View()
	a := strings.Index(out, "alpha")
	b := strings.Index(out, "beta")
	z := strings.Index(out, "zeta")

	if a < 0 || b < 0 || z < 0 {
		t.Fatalf("expected all titles in view; got positions: alpha=%d beta=%d zeta=%d\n%s", a, b, z, out)
	}
	if (a >= b) || (b >= z) {
		t.Fatalf("expected alphabetical order alpha < beta < zeta; got positions: a=%d b=%d z=%d", a, b, z)
	}
}
