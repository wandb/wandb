package leet_test

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestProcessRecordMsg_Run_Summary_System_FileComplete(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewRun("dummy", cfg, logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 140, Height: 50})

	model := m.(*leet.Run)
	model.TestHandleRecordMsg(leet.RunMsg{
		ID:          "run_123",
		DisplayName: "cool-run",
		Project:     "proj",
	})
	require.Equal(t, "run_123", model.TestRunID())
	require.Equal(t, "cool-run", model.TestRunDisplayName())
	require.Equal(t, "proj", model.TestRunProject())

	model.TestHandleRecordMsg(leet.SystemInfoMsg{
		Record: &spb.EnvironmentRecord{},
	})

	model.TestHandleRecordMsg(leet.SummaryMsg{
		Summary: []*spb.SummaryRecord{{}},
	})

	model.TestHandleRecordMsg(leet.FileCompleteMsg{ExitCode: 0})
	require.Equal(t, leet.RunStateFinished, model.TestRunState())
}

func TestFocus_Clicks_SetClear(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewRun("dummy", cfg, logger)

	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 60})
	d := map[string]leet.MetricData{
		"a": {
			X: []float64{0},
			Y: []float64{1},
		},
		"b": {
			X: []float64{0},
			Y: []float64{2},
		},
	}
	m, _ = m.Update(leet.HistoryMsg{Metrics: d})

	model := m.(*leet.Run)
	model.TestSetMainChartFocus(0, 0)
	fs := model.TestFocusState()
	require.Equal(t, leet.FocusMainChart, fs.Type)
	require.Equal(t, 0, fs.Row)
	require.Equal(t, 0, fs.Col)
	require.NotEmpty(t, fs.Title)

	model.TestHandleChartGridClick(0, 0)
	require.Equal(t, leet.FocusNone, model.TestFocusState().Type)

	model.TestHandleChartGridClick(0, 1)
	require.Equal(t, leet.FocusMainChart, model.TestFocusState().Type)

	model.TestClearMainChartFocus()
	require.Equal(t, leet.FocusNone, model.TestFocusState().Type)
}

func TestHandleOverviewFilter_TypingSpaceBackspaceEnterEsc(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewRun("dummy", cfg, logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 60})

	// Enter overview filter mode
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'o'}})

	// Type "acc", add space, backspace, then Enter
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("ac")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("c")})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeySpace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyBackspace})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyEnter})

	model := m.(*leet.Run)
	require.True(t, model.TestSidebarIsFiltering())
	require.Equal(t, "acc", model.TestSidebarFilterQuery())

	// Enter filter mode again, type something, then Esc
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune{'o'}})
	m, _ = m.Update(tea.KeyMsg{Type: tea.KeyRunes, Runes: []rune("tmp")})
	_, _ = m.Update(tea.KeyMsg{Type: tea.KeyEsc})

	// Should keep the previously applied "acc" state
	require.True(t, model.TestSidebarIsFiltering())
	require.Equal(t, "acc", model.TestSidebarFilterQuery())
}

func TestHandleKeyMsg_VariousPaths(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	var m tea.Model = leet.NewRun("dummy", cfg, logger)
	m, _ = m.Update(tea.WindowSizeMsg{Width: 180, Height: 50})

	// Toggle left sidebar
	m, _ = m.Update(tea.KeyMsg{Runes: []rune{'['}, Type: tea.KeyRunes})
	model := m.(*leet.Run)

	// Force complete the animation
	ls := model.TestGetLeftSidebar()
	ls.TestForceExpand()

	require.True(t, model.TestLeftSidebarVisible())

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
	if testing.Short() {
		t.Skip("skipping test in short mode.")
	}

	// Setup config with short heartbeat interval for testing
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	require.NoError(t, cfg.SetHeartbeatInterval(1))

	// Create a wandb file with initial data
	path := filepath.Join(t.TempDir(), "heartbeat.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	// Write initial records
	runRecord := &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       "heartbeat-test",
				DisplayName: "Heartbeat Test",
			},
		},
	}
	require.NoError(t, w.Write(runRecord))

	// Write some history
	for i := range 5 {
		h := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
				{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
			},
		}
		require.NoError(t, w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}}))
	}
	w.Close()

	// Create model
	m := leet.NewRun(path, cfg, logger)

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
			r, _ := leet.NewWandbReader(path, logger)
			return r
		}(),
	})

	// Simulate initial data load.
	d := map[string]leet.MetricData{
		"loss": {
			X: []float64{0},
			Y: []float64{0.1},
		},
	}
	model, _ = model.Update(leet.ChunkedBatchMsg{
		Msgs: []tea.Msg{
			leet.RunMsg{ID: "heartbeat-test", DisplayName: "Heartbeat Test"},
			leet.HistoryMsg{Metrics: d},
		},
		HasMore: false,
	})

	// Verify model is in running state
	concreteModel := model.(*leet.Run)
	require.Equal(t, leet.RunStateRunning, concreteModel.TestRunState())

	// Write more data in background to simulate live run
	go func() {
		time.Sleep(100 * time.Millisecond)
		_ = os.Remove(path)
		w, _ := transactionlog.OpenWriter(path)

		for i := 5; i < 10; i++ {
			h := &spb.HistoryRecord{
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
					{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%f", float64(i)*0.1)},
				},
			}
			_ = w.Write(&spb.Record{RecordType: &spb.Record_History{History: h}})
			time.Sleep(50 * time.Millisecond)
		}

		w.Close()
	}()

	// Process heartbeats for a short time
	done := make(chan bool)
	go func() {
		time.Sleep(500 * time.Millisecond)
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
			time.Sleep(50 * time.Millisecond)
		}
	}

	// Verify heartbeat was triggered at least once
	heartbeatMu.Lock()
	finalCount := heartbeatCount
	heartbeatMu.Unlock()

	require.NotZero(t, finalCount, "no heartbeats were processed during live run")

	// Send exit to stop heartbeat
	model.Update(leet.FileCompleteMsg{ExitCode: 0})

	// Verify heartbeat stops after completion
	heartbeatMu.Lock()
	countBefore := heartbeatCount
	heartbeatMu.Unlock()

	time.Sleep(200 * time.Millisecond)

	heartbeatMu.Lock()
	countAfter := heartbeatCount
	heartbeatMu.Unlock()

	require.Equal(t, countBefore, countAfter, "heartbeat continued after file completion")
}

func TestHeartbeat_ResetsOnDataReceived(t *testing.T) {
	// Setup config with short heartbeat
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	require.NoError(t, cfg.SetHeartbeatInterval(1)) // 1 second minimum

	path := filepath.Join(t.TempDir(), "reset.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.Write(&spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{RunId: "test"},
		},
	}))
	w.Close()

	// Create model
	m := leet.NewRun(path, cfg, logger)

	var model tea.Model = m
	model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

	// Initialize
	model, _ = model.Update(leet.InitMsg{
		Reader: func() *leet.WandbReader {
			r, _ := leet.NewWandbReader(path, logger)
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

	// Now send new data (should reset heartbeat).
	d := map[string]leet.MetricData{
		"metric": {
			X: []float64{1},
			Y: []float64{1.0},
		},
	}
	model, _ = model.Update(leet.HistoryMsg{Metrics: d})

	// The heartbeat should have been reset internally
	// We can't directly test the timer reset, but we can verify
	// that receiving data doesn't break the heartbeat mechanism
	model, _ = model.Update(leet.HeartbeatMsg{})

	require.True(t, heartbeatReceived, "heartbeat not processed initially")

	// Verify model still in good state
	concreteModel := model.(*leet.Run)
	require.Equal(t, leet.RunStateRunning, concreteModel.TestRunState())
}

func TestModel_HandleMouseMsg(t *testing.T) {
	// Helper to create a fresh model with data
	setupModel := func(t *testing.T) *leet.Run {
		logger := observability.NewNoOpLogger()
		cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

		require.NoError(t, cfg.SetMetricsRows(2))
		require.NoError(t, cfg.SetMetricsCols(2))
		require.NoError(t, cfg.SetSystemRows(2))
		require.NoError(t, cfg.SetSystemCols(1))
		require.NoError(t, cfg.SetLeftSidebarVisible(true))
		require.NoError(t, cfg.SetRightSidebarVisible(true))

		m := leet.NewRun("dummy", cfg, logger)

		var model tea.Model = m
		model, _ = model.Update(tea.WindowSizeMsg{Width: 120, Height: 40})

		// Add metrics data.
		d := map[string]leet.MetricData{
			"loss": {
				X: []float64{0},
				Y: []float64{1.0},
			},
			"accuracy": {
				X: []float64{0},
				Y: []float64{0.9},
			},
			"val_loss": {
				X: []float64{0},
				Y: []float64{1.2},
			},
		}
		model, _ = model.Update(leet.HistoryMsg{Metrics: d})

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
		_ = model.(*leet.Run).View()

		return model.(*leet.Run)
	}

	tests := []struct {
		name   string
		setup  func(*leet.Run)
		events []tea.MouseMsg
		verify func(*testing.T, *leet.Run)
	}{
		{
			name: "click_in_left_sidebar_clears_all_focus",
			setup: func(m *leet.Run) {
				m.TestSetMainChartFocus(0, 0)
			},
			events: []tea.MouseMsg{
				{X: 10, Y: 10, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Run) {
				require.Equal(t, leet.FocusNone, m.TestFocusState().Type)
			},
		},
		{
			name: "click_in_main_grid_focuses_and_unfocuses_chart",
			events: []tea.MouseMsg{
				{X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Run) {
				require.Equal(t, leet.FocusMainChart, m.TestFocusState().Type)

				// Send second click to same position
				var model tea.Model = m
				model.Update(tea.MouseMsg{
					X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress,
				})

				require.Equal(t, leet.FocusNone, m.TestFocusState().Type)
			},
		},
		{
			name: "click_in_right_sidebar_focuses_system_chart",
			events: []tea.MouseMsg{
				// Right sidebar starts at approximately 120 - 40 (sidebar width) = 80
				// Click well inside the right sidebar area
				{X: 110, Y: 10, Button: tea.MouseButtonLeft, Action: tea.MouseActionPress},
			},
			verify: func(t *testing.T, m *leet.Run) {
				fs := m.TestFocusState()
				require.Equal(t, leet.FocusSystemChart, fs.Type)
				require.NotEmpty(t, fs.Title)
			},
		},
		{
			name: "wheel_events_focus_chart_and_zoom",
			events: []tea.MouseMsg{
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
				{X: 60, Y: 25, Button: tea.MouseButtonWheelDown},
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
			},
			verify: func(t *testing.T, m *leet.Run) {
				require.Equal(t, leet.FocusMainChart, m.TestFocusState().Type)
			},
		},
		{
			name: "mouse_release_ignored",
			setup: func(m *leet.Run) {
				m.TestSetMainChartFocus(0, 0)
			},
			events: []tea.MouseMsg{
				{X: 60, Y: 15, Button: tea.MouseButtonLeft, Action: tea.MouseActionRelease},
			},
			verify: func(t *testing.T, m *leet.Run) {
				require.Equal(t, leet.FocusMainChart, m.TestFocusState().Type)
			},
		},
		{
			name: "wheel_on_unfocused_chart_focuses_it",
			setup: func(m *leet.Run) {
				// Ensure no initial focus
				m.TestClearMainChartFocus()
			},
			events: []tea.MouseMsg{
				{X: 60, Y: 25, Button: tea.MouseButtonWheelUp},
			},
			verify: func(t *testing.T, m *leet.Run) {
				require.Equal(t, leet.FocusMainChart, m.TestFocusState().Type)
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
