package leet_test

import (
	"path/filepath"
	"strings"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

func selectField(t *testing.T, m tea.Model, jsonKey string) tea.Model {
	t.Helper()

	needle := "(" + jsonKey + ")"
	for range 50 {
		if strings.Contains(m.View().Content, needle) {
			return m
		}
		m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	}
	require.Failf(t, "field not found", "expected %q in view output", needle)
	return m
}

func TestConfigEditor_EnumChange_SaveAndPersists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Enter opens enum selection; Down selects single_run_latest.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	// Save & quit.
	_, cmd := m.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	// Reload from disk to verify persistence.
	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, leet.StartupModeSingleRunLatest, cfg2.Snapshot().StartupMode)
}

func TestConfigEditor_ChartGuidesChange_SaveAndPersists(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})
	m = selectField(t, m, "chart_guides")

	// The default is off; Right twice selects horizontal.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyRight})
	_, cmd := m.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, leet.ChartGuidesHorizontal, cfg2.ChartGuides())
}

func TestConfigEditor_QuitConfirmation_RespectsCtrlCAndClearsOnOtherKeys(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Make the model dirty (cycle the startup mode enum).
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyRight})

	// First Ctrl+C should prompt (no quit).
	m, cmd := m.Update(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl})
	require.Nil(t, cmd)
	require.Contains(t, m.View().Content, "Unsaved changes")

	// Any other key clears the confirmation prompt.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyDown})
	require.NotContains(t, m.View().Content, "Unsaved changes")

	// Ctrl+C again: prompt again.
	m, cmd = m.Update(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl})
	require.Nil(t, cmd)

	// Ctrl+C again: now quit.
	_, cmd = m.Update(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)
}

func TestConfigEditor_CtrlCQuitsFromEnumModal_WhenClean(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "startup_mode")

	// Enter enum modal, then Ctrl+C should quit immediately (no unsaved changes).
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	_, cmd := m.Update(tea.KeyPressMsg{Code: 'c', Mod: tea.ModCtrl})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)
}

func TestConfigEditor_IntEdit_ValidatesAndApplies(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "heartbeat_interval_seconds")

	// Enter int edit mode.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	// Clear current input (default 15) and enter an invalid value 0.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyPressMsg{Code: '0', Text: "0"})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	require.Contains(t, m.View().Content, "Must be >= 1")

	// Replace with valid value 10.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyPressMsg{Code: '1', Text: "1"})
	m, _ = m.Update(tea.KeyPressMsg{Code: '0', Text: "0"})
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	require.NotContains(t, m.View().Content, "Must be >= 1")

	// Save & quit.
	_, cmd := m.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	cfg2 := leet.NewConfigManager(path, logger)
	require.Equal(t, 10, cfg2.Snapshot().HeartbeatInterval)
}

func TestConfigEditor_DefaultDescriptionsForGridConfig(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "metrics_grid.rows")

	view := m.View().Content
	require.Contains(t, view, "Rows in the main metrics grid.")
	require.Contains(t, view, "(metrics_grid.rows)")
}

func TestConfigEditor_SpaceTogglesBool(t *testing.T) {
	logger := observability.NewNoOpLogger()
	path := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.NewConfigManager(path, logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "left_sidebar_visible")

	// Space toggles the bool (default true).
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeySpace, Text: " "})

	// Save & quit.
	_, cmd := m.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	require.NotNil(t, cmd)
	_, ok := cmd().(tea.QuitMsg)
	require.True(t, ok)

	cfg2 := leet.NewConfigManager(path, logger)
	require.False(t, cfg2.Snapshot().LeftSidebarVisible)
}

// firstLines returns the first n lines of the view with ANSI stripped.
func firstLines(m tea.Model, n int) string {
	lines := strings.Split(stripANSI(m.View().Content), "\n")
	if len(lines) > n {
		lines = lines[:n]
	}
	return strings.Join(lines, "\n")
}

func TestConfigEditor_Height24_SelectionAndEnumModalVisible(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 100, Height: 24})

	// Open the largest enum picker (14 color schemes); the whole modal
	// must render within the 24 visible lines.
	m = selectField(t, m, "color_scheme")
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})
	head := firstLines(m, 24)
	require.Contains(t, head, "Select Color scheme")
	require.Contains(t, head, "> "+leet.DefaultColorScheme)
	require.Contains(t, head, "╰") // modal bottom border

	// Back to browse; the selected row must stay within the 24 visible
	// lines even for the last field.
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEscape})
	m = selectField(t, m, "workspace_media_visible")
	require.Contains(t, firstLines(m, 24), "Workspace media visible")
}

func TestConfigEditor_ColorSchemePicker_ShowsPalettePreview(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	var m tea.Model = leet.NewConfigEditor(leet.ConfigEditorParams{Config: cfg, Logger: logger})
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	m = selectField(t, m, "color_scheme")
	m, _ = m.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	view := stripANSI(m.View().Content)
	preview := strings.Repeat(
		leet.ConfigEditorPalettePreviewBlock, len(leet.GraphColors("wandb-vibe-10")))
	require.Contains(t, view, "wandb-vibe-10  "+preview)
}
