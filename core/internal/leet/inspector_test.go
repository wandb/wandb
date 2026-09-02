package leet_test

import (
	"path/filepath"
	"testing"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
)

// newTestInspector builds an inspector over a small .wandb file with its
// initial scan completed.
func newTestInspector(t *testing.T) *leet.Inspector {
	t.Helper()

	logger := observability.NewNoOpLogger()
	path := writeWandbFile(t, inspectorTestRecords()...)
	ins := leet.NewInspector(leet.InspectorParams{
		RunFile: path,
		Config:  leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger),
	})
	t.Cleanup(ins.Cleanup)

	_, _ = ins.Update(tea.WindowSizeMsg{Width: 120, Height: 30})

	initMsg := leet.InitializeInspector(path, "", logger)()
	require.IsType(t, leet.InspectorInitMsg{}, initMsg)
	_, cmd := ins.Update(initMsg)
	require.NotNil(t, cmd)

	batchMsg := cmd()
	require.IsType(t, leet.InspectorBatchMsg{}, batchMsg)
	_, _ = ins.Update(batchMsg)

	return ins
}

func TestInspector_ListsRecordsAndShowsDetail(t *testing.T) {
	ins := newTestInspector(t)

	view := ins.View().Content
	// The list shows all records with type and summary hints.
	assert.Contains(t, view, "run")
	assert.Contains(t, view, "history")
	assert.Contains(t, view, "step 5")
	assert.Contains(t, view, "exit")
	// The detail pane shows the first record.
	assert.Contains(t, view, "record 1: run")
	assert.Contains(t, view, "abc123")
	// The header counts the records; the exit record marks the file
	// complete.
	assert.Contains(t, view, "[5 records]")
	assert.NotContains(t, view, "live")
}

func TestInspector_FocusToggleDimsSelection(t *testing.T) {
	ins := newTestInspector(t)

	listSelected := ins.View().Content
	_, _ = ins.Update(tea.KeyPressMsg{Code: tea.KeyTab})
	detailFocused := ins.View().Content

	// The selected row's highlight changes when focus moves to the detail
	// pane, so the two frames must differ.
	assert.NotEqual(t, listSelected, detailFocused)

	_, _ = ins.Update(tea.KeyPressMsg{Code: tea.KeyEsc})
	assert.Equal(t, listSelected, ins.View().Content)
}

func TestInspector_NavigationChangesDetail(t *testing.T) {
	ins := newTestInspector(t)

	_, _ = ins.Update(tea.KeyPressMsg{Code: 's', Text: "s"})
	assert.Contains(t, ins.View().Content, "record 2: history")

	_, _ = ins.Update(tea.KeyPressMsg{Code: tea.KeyEnd})
	assert.Contains(t, ins.View().Content, "record 5: exit")

	_, _ = ins.Update(tea.KeyPressMsg{Code: tea.KeyHome})
	assert.Contains(t, ins.View().Content, "record 1: run")
}

func TestInspector_FilterNarrowsList(t *testing.T) {
	ins := newTestInspector(t)

	_, _ = ins.Update(tea.KeyPressMsg{Code: '/', Text: "/"})
	for _, r := range "history" {
		_, _ = ins.Update(tea.KeyPressMsg{Code: r, Text: string(r)})
	}
	_, _ = ins.Update(tea.KeyPressMsg{Code: tea.KeyEnter})

	view := ins.View().Content
	// Only the history and partial_history records match; the selection
	// moved onto a matching record.
	assert.Contains(t, view, "of 2 filtered from 5]")
	assert.Contains(t, view, "record 2: history")
	assert.NotContains(t, view, "output_raw")

	_, _ = ins.Update(tea.KeyPressMsg{Code: '/', Mod: tea.ModCtrl})
	assert.Contains(t, ins.View().Content, "[5 records]")
}

func TestInspector_DragResizesAndResetsListPane(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	path := writeWandbFile(t, inspectorTestRecords()...)

	ins := leet.NewInspector(leet.InspectorParams{
		RunFile: path,
		Config:  cfg,
	})
	t.Cleanup(ins.Cleanup)
	_, _ = ins.Update(tea.WindowSizeMsg{Width: 120, Height: 30})

	// The default list width at 120 columns is the golden-ratio minimum
	// clamp (40 + border padding overhead). Drag its border to column 60
	// and release: the fraction is persisted.
	border := 45 // 0.382 * 120, clamped to [40, 120]
	_, _ = ins.Update(tea.MouseClickMsg{X: border, Y: 5, Button: tea.MouseLeft})
	_, _ = ins.Update(tea.MouseMotionMsg{X: 60, Y: 5, Button: tea.MouseLeft})
	_, _ = ins.Update(tea.MouseReleaseMsg{X: 60, Y: 5, Button: tea.MouseLeft})
	assert.InDelta(t, 61.0/120.0, cfg.InspectorLayout().LeftSidebar, 0.01)

	// "0" resets the layout to the defaults.
	_, _ = ins.Update(tea.KeyPressMsg{Code: '0', Text: "0"})
	assert.Zero(t, cfg.InspectorLayout().LeftSidebar)
}

func TestInspector_HelpOverlay(t *testing.T) {
	ins := newTestInspector(t)

	_, _ = ins.Update(tea.KeyPressMsg{Code: 'h', Text: "h"})
	view := ins.View().Content
	assert.Contains(t, view, "record inspector")
	assert.Contains(t, view, "Filter records by type or summary")

	_, _ = ins.Update(tea.KeyPressMsg{Code: 'h', Text: "h"})
	assert.Contains(t, ins.View().Content, "record 1: run")
}
