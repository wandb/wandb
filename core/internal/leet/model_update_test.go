package leet_test

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
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
	if runID := model.TestRunID(); runID != "run_123" {
		t.Fatalf("Run ID not updated to: %+v", runID)
	}
	if displayName := model.TestRunDisplayName(); displayName != "cool-run" {
		t.Fatalf("Run displayName not updated to: %+v", displayName)
	}
	if project := model.TestRunProject(); project != "proj" {
		t.Fatalf("Run project not updated to: %+v", project)
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

func TestFocus_Clicks_SetClear(t *testing.T) {
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
}

func TestHandleOverviewFilter_TypingSpaceBackspaceEnterEsc(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 60})

	// Enter overview filter mode
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'o'}})

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
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'o'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("tmp")})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// Should keep the previously applied "acc" state
	if !model.TestSidebarIsFiltering() || model.TestSidebarFilterQuery() != "acc" {
		t.Fatalf("overview filter ESC should restore applied query; got active=%v query=%q",
			model.TestSidebarIsFiltering(), model.TestSidebarFilterQuery())
	}
}

func TestHandleKeyMsg_VariousPaths(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 50})

	// Toggle left sidebar
	m, _ = m.Update(tea.KeyMsg{Runes: []rune{'['}, Type: tea.KeyRunes})
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

func TestHeartbeat_LiveRun(t *testing.T) {
	// Setup config with short heartbeat interval for testing
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetHeartbeatInterval(1)

	// Create a wandb file with initial data
	tmp, err := os.CreateTemp(t.TempDir(), "heartbeat-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	_ = tmp.Close()
	_ = os.Remove(tmp.Name())

	w, err := transactionlog.OpenWriter(tmp.Name())
	if err != nil {
		t.Fatalf("Failed to open transaction log for writing: %v", err)
	}

	// Write initial records
	runRecord := &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       "heartbeat-test",
				DisplayName: "Heartbeat Test",
			},
		},
	}
	if err := w.Write(runRecord); err != nil {
		t.Fatalf("write run: %v", err)
	}

	// Write some history
	for i := range 5 {
		h := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
				{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
			},
		}
		if err := w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}}); err != nil {
			t.Fatalf("write history: %v", err)
		}
	}
	w.Close()

	// Create model
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(tmp.Name(), logger)

	// Track heartbeat messages
	heartbeatCount := 0
	var heartbeatMu sync.Mutex

	// Initialize and process initial data
	var model tea.Model = m
	model, initCmd := model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Execute init command
	if initCmd != nil {
		msg := initCmd()
		model, _ = model.Update(msg)
	}

	// Process initial reader
	model, _ = model.Update(leet.InitMsg{
		Reader: func() *leet.WandbReader {
			r, _ := leet.NewWandbReader(tmp.Name(), logger)
			return r
		}(),
	})

	// Simulate initial data load
	model, _ = model.Update(leet.ChunkedBatchMsg{
		Msgs: []tea.Msg{
			leet.RunMsg{ID: "heartbeat-test", DisplayName: "Heartbeat Test"},
			leet.HistoryMsg{Metrics: map[string]float64{"loss": 0.1}, Step: 0},
		},
		HasMore: false,
	})

	// Verify model is in running state
	concreteModel := model.(*leet.Model)
	if concreteModel.TestRunState() != leet.RunStateRunning {
		t.Fatalf("expected RunStateRunning, got %v", concreteModel.TestRunState())
	}

	// Write more data in background to simulate live run
	go func() {
		time.Sleep(500 * time.Millisecond)
		_ = os.Remove(tmp.Name())
		w, _ := transactionlog.OpenWriter(tmp.Name())

		for i := 5; i < 10; i++ {
			h := &spb.HistoryRecord{
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
					{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
				},
			}
			_ = w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}})
			time.Sleep(200 * time.Millisecond)
		}

		w.Close()
	}()

	// Process heartbeats for a short time
	done := make(chan bool)
	go func() {
		time.Sleep(2 * time.Second)
		done <- true
	}()

	// Process messages and count heartbeats
	processing := true
	for processing {
		select {
		case <-done:
			processing = false
		default:
			// Check for heartbeat messages
			_, cmd := model.Update(leet.HeartbeatMsg{})
			if cmd != nil {
				heartbeatMu.Lock()
				heartbeatCount++
				heartbeatMu.Unlock()
			}
			time.Sleep(100 * time.Millisecond)
		}
	}

	// Verify heartbeat was triggered at least once
	heartbeatMu.Lock()
	finalCount := heartbeatCount
	heartbeatMu.Unlock()

	if finalCount == 0 {
		t.Fatal("no heartbeats were processed during live run")
	}

	// Send exit to stop heartbeat
	model.Update(leet.FileCompleteMsg{ExitCode: 0})

	// Verify heartbeat stops after completion
	heartbeatMu.Lock()
	countBefore := heartbeatCount
	heartbeatMu.Unlock()

	time.Sleep(1500 * time.Millisecond)

	heartbeatMu.Lock()
	countAfter := heartbeatCount
	heartbeatMu.Unlock()

	if countAfter != countBefore {
		t.Fatal("heartbeat continued after file completion")
	}
}

func TestHeartbeat_ResetsOnDataReceived(t *testing.T) {
	// Setup config with short heartbeat
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetHeartbeatInterval(1) // 1 second minimum

	// Create wandb file
	tmp, err := os.CreateTemp(t.TempDir(), "reset-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	tmpPath := tmp.Name()
	_ = tmp.Close()
	_ = os.Remove(tmpPath)

	w, err := transactionlog.OpenWriter(tmpPath)
	if err != nil {
		t.Fatalf("Failed to open transaction log for writing: %v", err)
	}
	_ = w.Write(&spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{RunId: "test"},
		},
	})
	w.Close()

	// Create model
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(tmpPath, logger)

	var model tea.Model = m
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Initialize
	model, _ = model.Update(leet.InitMsg{
		Reader: func() *leet.WandbReader {
			r, _ := leet.NewWandbReader(tmpPath, logger)
			return r
		}(),
	})

	// Load initial data to start as running
	model, _ = model.Update(leet.ChunkedBatchMsg{
		Msgs:    []tea.Msg{leet.RunMsg{ID: "test"}},
		HasMore: false,
	})

	// Track heartbeat resets
	heartbeatReceived := false

	// Process a heartbeat
	model, cmd := model.Update(leet.HeartbeatMsg{})
	if cmd != nil {
		heartbeatReceived = true
	}

	// Now send new data (should reset heartbeat)
	model, _ = model.Update(leet.HistoryMsg{
		Metrics: map[string]float64{"metric": 1.0},
		Step:    1,
	})

	// The heartbeat should have been reset internally
	// We can't directly test the timer reset, but we can verify
	// that receiving data doesn't break the heartbeat mechanism
	model, _ = model.Update(leet.HeartbeatMsg{})

	if !heartbeatReceived {
		t.Fatal("heartbeat not processed initially")
	}

	// Verify model still in good state
	concreteModel := model.(*leet.Model)
	if concreteModel.TestRunState() != leet.RunStateRunning {
		t.Fatal("model not in running state after data receipt")
	}
}

func TestReload_WhileLoading_DoesNotCrash(t *testing.T) {
	logger := observability.NewNoOpLogger()
	var m tea.Model = leet.NewModel("dummy", logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Trigger a reload (Alt+r).
	var cmd tea.Cmd
	m, cmd = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'r'}, Alt: true})
	if cmd == nil {
		t.Fatal("expected reload command")
	}

	// Execute the reload message; this sets m.reader = nil internally.
	m, _ = m.Update(cmd())

	// A late chunk with HasMore=true should NOT panic.
	defer func() {
		if r := recover(); r != nil {
			t.Fatalf("Update panicked handling late chunk during reload: %v", r)
		}
	}()
	_, _ = m.Update(leet.ChunkedBatchMsg{Msgs: nil, HasMore: true, Progress: 1})
}

func TestModel_HandleMouseMsg(t *testing.T) {
	// Helper to create a fresh model with data
	setupModel := func(t *testing.T) *leet.Model {
		cfg := leet.GetConfig()
		cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
		if err := cfg.Load(); err != nil {
			t.Fatalf("Load: %v", err)
		}
		_ = cfg.SetMetricsRows(2)
		_ = cfg.SetMetricsCols(2)
		_ = cfg.SetSystemRows(2)
		_ = cfg.SetSystemCols(1)
		_ = cfg.SetLeftSidebarVisible(true)
		_ = cfg.SetRightSidebarVisible(true)

		logger := observability.NewNoOpLogger()
		m := leet.NewModel("dummy", logger)

		var model tea.Model = m
		model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

		// Add metrics data
		model, _ = model.Update(leet.HistoryMsg{
			Metrics: map[string]float64{
				"loss":     1.0,
				"accuracy": 0.9,
				"val_loss": 1.2,
			},
		})

		// Process stats multiple times to ensure system charts are created and drawn
		model, _ = model.Update(leet.StatsMsg{
			Timestamp: 1234567890,
			Metrics: map[string]float64{
				"gpu.0.temp":        45.0,
				"cpu.0.cpu_percent": 65.0,
			},
		})

		// Add more data points to ensure charts are properly initialized
		model, _ = model.Update(leet.StatsMsg{
			Timestamp: 1234567891,
			Metrics: map[string]float64{
				"gpu.0.temp":        46.0,
				"cpu.0.cpu_percent": 66.0,
			},
		})

		// Force a render to ensure sidebars are drawn
		_ = model.(*leet.Model).View()

		return model.(*leet.Model)
	}

	tests := []struct {
		name   string
		setup  func(*leet.Model)
		events []tea.MouseMsg
		verify func(*testing.T, *leet.Model)
	}{
		{
			name: "click_in_left_sidebar_clears_all_focus",
			setup: func(m *leet.Model) {
				m.TestSetMainChartFocus(0, 0)
			},
			events: []tea.MouseMsg{
				{X: 10, Y: 10, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Model) {
				if m.TestFocusState().Type != leet.FocusNone {
					t.Errorf("expected FocusNone, got %v", m.TestFocusState().Type)
				}
			},
		},
		{
			name: "click_in_main_grid_focuses_and_unfocuses_chart",
			events: []tea.MouseMsg{
				{X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Model) {
				if m.TestFocusState().Type != leet.FocusMainChart {
					t.Fatalf("expected FocusMainChart after first click, got %v", m.TestFocusState().Type)
				}

				// Send second click to same position
				var model tea.Model = m
				model.Update(tea.MouseMsg{
					X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress,
				})

				if m.TestFocusState().Type != leet.FocusNone {
					t.Errorf("expected FocusNone after second click, got %v", m.TestFocusState().Type)
				}
			},
		},
		{
			name: "click_in_right_sidebar_focuses_system_chart",
			events: []tea.MouseMsg{
				// Right sidebar starts at approximately 120 - 40 (sidebar width) = 80
				// Click well inside the right sidebar area
				{X: 110, Y: 10, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Model) {
				fs := m.TestFocusState()
				if fs.Type != leet.FocusSystemChart {
					t.Errorf("expected FocusSystemChart, got %v", fs.Type)
				}
				if fs.Title == "" {
					t.Error("expected focused system chart to have a title")
				}
			},
		},
		{
			name: "wheel_events_focus_chart_and_zoom",
			events: []tea.MouseMsg{
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
				{X: 60, Y: 25, Button: tea.MouseButtonWheelDown},
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
			},
			verify: func(t *testing.T, m *leet.Model) {
				if m.TestFocusState().Type != leet.FocusMainChart {
					t.Errorf("expected FocusMainChart after wheel events, got %v", m.TestFocusState().Type)
				}
			},
		},
		{
			name: "mouse_release_ignored",
			setup: func(m *leet.Model) {
				m.TestSetMainChartFocus(0, 0)
			},
			events: []tea.MouseMsg{
				{X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionRelease},
			},
			verify: func(t *testing.T, m *leet.Model) {
				if m.TestFocusState().Type != leet.FocusMainChart {
					t.Errorf("expected focus unchanged after release, got %v", m.TestFocusState().Type)
				}
			},
		},
		{
			name: "wheel_on_unfocused_chart_focuses_it",
			setup: func(m *leet.Model) {
				// Ensure no initial focus
				m.TestClearMainChartFocus()
			},
			events: []tea.MouseMsg{
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
			},
			verify: func(t *testing.T, m *leet.Model) {
				if m.TestFocusState().Type != leet.FocusMainChart {
					t.Errorf("expected wheel to focus chart, got %v", m.TestFocusState().Type)
				}
			},
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			m := setupModel(t)
			var model tea.Model = m

			// Run setup if provided
			if tc.setup != nil {
				tc.setup(m)
			}

			// Process all events
			for _, event := range tc.events {
				model, _ = model.Update(event)
			}

			// Verify final state
			tc.verify(t, m)
		})
	}
}
