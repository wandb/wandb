package leet_test

import (
	"path/filepath"
	"testing"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestProcessRecordMsg_Run_Summary_System_FileComplete(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 140, Height: 50})

	model := m.(*leet.Model)
	model.TestProcessRecordMsg(leet.RunMsg{
		ID:          "run_123",
		DisplayName: "cool-run",
		Project:     "proj",
	})
	ro := model.TestRunOverview()
	if ro.ID != "run_123" || ro.DisplayName != "cool-run" || ro.Project != "proj" {
		t.Fatalf("Run overview not populated: %+v", ro)
	}

	model.TestProcessRecordMsg(leet.SystemInfoMsg{
		Record: &spb.EnvironmentRecord{},
	})

	model.TestProcessRecordMsg(leet.SummaryMsg{
		Summary: &spb.SummaryRecord{},
	})

	model.TestProcessRecordMsg(leet.FileCompleteMsg{ExitCode: 0})
	if got := model.TestRunState(); got != leet.RunStateFinished {
		t.Fatalf("run state=%v; want Finished", got)
	}
}

func TestFocus_Clicks_SetClear_All(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)

	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 60})
	m, _ = m.Update(leet.HistoryMsg{
		Metrics: map[string]float64{"a": 1, "b": 2},
	})

	model := m.(*leet.Model)
	model.TestSetMainChartFocus(0, 0)
	fs := model.TestFocusState()
	if fs.Type != leet.FocusMainChart || fs.Row != 0 || fs.Col != 0 || fs.Title == "" {
		t.Fatalf("unexpected focus after setMainChartFocus: %+v", fs)
	}

	model.TestHandleChartGridClick(0, 0)
	if model.TestFocusState().Type != leet.FocusNone {
		t.Fatalf("expected no focus after clicking focused chart")
	}

	model.TestHandleChartGridClick(0, 1)
	if model.TestFocusState().Type != leet.FocusMainChart {
		t.Fatalf("expected main focus after clicking a different chart")
	}
	model.TestClearMainChartFocus()
	if model.TestFocusState().Type != leet.FocusNone {
		t.Fatalf("expected no focus after clearMainChartFocus")
	}

	model.TestHandleChartGridClick(0, 0)
	model.TestClearAllFocus()
	if model.TestFocusState().Type != leet.FocusNone {
		t.Fatalf("expected no focus after clearAllFocus")
	}
}

func TestHandleOverviewFilter_TypingSpaceBackspaceEnterEsc(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 60})

	// Enter overview filter mode
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'['}})

	// Type "acc", add space, backspace, then Enter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("ac")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("c")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeySpace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	model := m.(*leet.Model)
	if !model.TestSidebarIsFiltering() || model.TestSidebarFilterQuery() != "acc" {
		t.Fatalf("overview filter not applied; got active=%v query=%q",
			model.TestSidebarIsFiltering(), model.TestSidebarFilterQuery())
	}

	// Enter filter mode again, type something, then Esc
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'['}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("tmp")})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// Should keep the previously applied "acc" state
	if !model.TestSidebarIsFiltering() || model.TestSidebarFilterQuery() != "acc" {
		t.Fatalf("overview filter ESC should restore applied query; got active=%v query=%q",
			model.TestSidebarIsFiltering(), model.TestSidebarFilterQuery())
	}
}

func TestHandleKeyMsg_VariousPaths(t *testing.T) {
	cfgPath := filepath.Join(t.TempDir(), "config.json")
	cfg := leet.GetConfig()
	cfg.SetPathForTests(cfgPath)
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}

	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 50})

	// Toggle left sidebar
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyCtrlB})
	model := m.(*leet.Model)

	// Force complete the animation
	ls := model.TestGetLeftSidebar()
	ls.TestForceExpand()

	if !model.TestLeftSidebarVisible() {
		t.Fatalf("expected left sidebar visible after Ctrl+B toggle + animation")
	}

	// Page navigation (shouldn't panic)
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyPgUp})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyShiftUp})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyPgDown})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyShiftDown})

	// Help toggle
	m, _ = m.Update(tea.KeyMsg{Runes: []rune{'h'}, Type: tea.KeyRunes})
	m, _ = m.Update(tea.KeyMsg{Runes: []rune{'?'}, Type: tea.KeyRunes})

	// Overview filter
	m, _ = m.Update(tea.KeyMsg{Runes: []rune{'['}, Type: tea.KeyRunes})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeySpace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	// Clear overview filter
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyCtrlK})
}
