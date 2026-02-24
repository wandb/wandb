package leet_test

import (
	"bytes"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const (
	shortWait = 2 * time.Second
	longWait  = 3 * time.Second
)

// newTestModel creates a test model and sends an initial WindowSizeMsg to force the first render.
// The model's View returns "Loading..." until width/height are non-zero, so we always size first.
// Uses the full Model (not bare Run) so help and mode-switching work correctly.
func newTestModel(
	t *testing.T,
	cfg *leet.ConfigManager,
	runPath string,
	w, h int,
) *teatest.TestModel {
	t.Helper()
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(leet.ModelParams{
		RunFile: runPath,
		Config:  cfg,
		Logger:  logger,
	})
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(w, h))
	tm.Send(tea.WindowSizeMsg{Width: w, Height: h})
	return tm
}

// writeRecord marshals and writes a single protobuf record to the leveldb writer.
func writeRecord(t *testing.T, w *leveldb.Writer, rec *spb.Record) {
	t.Helper()
	data, err := proto.Marshal(rec)
	require.NoError(t, err)
	dst, err := w.Next()
	require.NoError(t, err)
	_, err = dst.Write(data)
	require.NoError(t, err)
}

// forceRepaint nudges Bubble Tea to produce a fresh frame.
// Why needed: teatest.WaitFor consumes tm.Output(). Without a new render, a second
// WaitFor may time out even if the content is already on-screen. Sending a slightly
// different WindowSizeMsg ensures Update runs and View emits new bytes.
func forceRepaint(tm *teatest.TestModel, w, h int) {
	tm.Send(tea.WindowSizeMsg{Width: w + 1, Height: h})
}

func TestLoadingScreenAndQuit(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	tm := newTestModel(t, cfg, "no/such/file.wandb", 100, 30)

	// Wait for loading screen text.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("Loading data...")) },
		teatest.WithDuration(shortWait),
	)

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}

func TestMetricsAndSystemMetrics_RenderAndSeriesCount(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping in short mode")
	}
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	_ = cfg.SetSystemRows(2)
	_ = cfg.SetSystemCols(2)
	_ = cfg.SetRightSidebarVisible(true)

	// Create a writable .wandb file and keep it open to simulate a live run.
	tmp, err := os.CreateTemp(t.TempDir(), "test-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	defer tmp.Close()
	writer := leveldb.NewWriterExt(tmp, leveldb.CRCAlgoIEEE, 0)

	// Seed minimal run + metrics so both the main grid and system grid can render.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       "test-run",
				DisplayName: "Test Run",
				Project:     "test-project",
			},
		},
	})
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: 1},
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: "1"},
					{NestedKey: []string{"loss"}, ValueJson: "1.0"},
				},
			},
		},
	})

	ts := time.Now().Unix()
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				Timestamp: &timestamppb.Timestamp{Seconds: ts},
				Item: []*spb.StatsItem{
					{Key: "gpu.0.temp", ValueJson: "40"},
					{Key: "gpu.1.temp", ValueJson: "42"},
					{Key: "cpu.0.cpu_percent", ValueJson: "55"},
				},
			},
		},
	})
	require.NoError(t, writer.Flush())

	// Spin up the TUI against the live file.
	const W, H = 240, 80
	tm := newTestModel(t, cfg, tmp.Name(), W, H)

	// Wait for the main grid to show (loss chart).
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("loss")) },
		teatest.WithDuration(longWait),
	)

	// Force a fresh frame for the next assertion.
	//
	// Why: teatest.WaitFor reads and consumes tm.Output(). The "loss" wait above
	// may have already consumed the bytes that contained the "System Metrics"
	// header. We must trigger a new render so the next WaitFor can observe it.
	// WindowSizeMsg goes through the model's Update -> handleOther(WindowSizeMsg) path,
	// which updates widths/heights and re-computes layout, causing a redraw.
	forceRepaint(tm, W, H)

	// Assert the right sidebar header renders.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("System Metrics")) },
		teatest.WithDuration(longWait),
	)

	// Append more stats (2 GPUs → series count [2]) and notify the app.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				Timestamp: &timestamppb.Timestamp{Seconds: ts + 1},
				Item: []*spb.StatsItem{
					{Key: "gpu.0.temp", ValueJson: "41"},
					{Key: "gpu.1.temp", ValueJson: "43"},
					{Key: "cpu.0.cpu_percent", ValueJson: "56"},
				},
			},
		},
	})
	require.NoError(t, writer.Flush())
	tm.Send(leet.FileChangedMsg{}) // triggers ReadAvailableRecords + redraw in Update.

	forceRepaint(tm, 241, 80)

	// Expect the GPU Temp chart with series count [2] and the CPU Core chart.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return bytes.Contains(b, []byte("GPU Temp")) &&
				bytes.Contains(b, []byte("[2]")) &&
				bytes.Contains(b, []byte("CPU Core"))
		},
		teatest.WithDuration(longWait),
	)

	// Add a 3rd GPU and then a RunExit, close the writer, and notify again.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				Timestamp: &timestamppb.Timestamp{Seconds: ts + 2},
				Item: []*spb.StatsItem{
					{Key: "gpu.0.temp", ValueJson: "41"},
					{Key: "gpu.1.temp", ValueJson: "43"},
					{Key: "gpu.2.temp", ValueJson: "44"},
					{Key: "cpu.0.cpu_percent", ValueJson: "57"},
				},
			},
		},
	})
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{ExitCode: 0},
		},
	})
	require.NoError(t, writer.Close())
	tm.Send(leet.FileChangedMsg{}) // live read + redraw.

	// Wait for the series count [3].
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("[3]")) },
		teatest.WithDuration(longWait),
	)

	// Toggle help on, then assert the banner appears, then toggle it off.
	// Why? To get some free coverage, of course!
	tm.Type("h")
	forceRepaint(tm, 240, 80)
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("LEET")) },
		teatest.WithDuration(shortWait),
	)
	tm.Type("h")

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}

// newWorkspaceTestModel mirrors newTestModel from tui_test.go but starts in workspace mode.
func newWorkspaceTestModel(
	t *testing.T,
	cfg *leet.ConfigManager,
	wandbDir string,
	w, h int,
) *teatest.TestModel {
	t.Helper()
	logger := observability.NewNoOpLogger()

	m := leet.NewModel(leet.ModelParams{
		WandbDir: wandbDir,
		Config:   cfg,
		Logger:   logger,
	})

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(w, h))
	tm.Send(tea.WindowSizeMsg{Width: w, Height: h})
	return tm
}

func writeWorkspaceRunWandbFile(
	t *testing.T,
	wandbDir, runKey, runID string,
	loss float64,
) string {
	t.Helper()

	runFile := filepath.Join(wandbDir, runKey, "run-"+runID+".wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))

	f, err := os.Create(runFile)
	require.NoError(t, err)
	defer func() { _ = f.Close() }()

	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)

	// Minimal Run record (powers run overview preload + nicer UI).
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       runID,
				DisplayName: runID,
				Project:     "test-project",
			},
		},
	})

	// Minimal History record with a single metric ("loss") so the MetricsGrid renders.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: 1},
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: "1"},
					{NestedKey: []string{"loss"}, ValueJson: fmt.Sprintf("%g", loss)},
				},
			},
		},
	})

	require.NoError(t, writer.Flush())
	require.NoError(t, writer.Close())

	return runFile
}

func waitForPlainOutput(
	t *testing.T,
	tm *teatest.TestModel,
	want []string,
	notWant []string,
) {
	t.Helper()

	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			s := stripANSI(string(b))
			for _, w := range want {
				if !strings.Contains(s, w) {
					return false
				}
			}
			for _, nw := range notWant {
				if strings.Contains(s, nw) {
					return false
				}
			}
			return true
		},
		teatest.WithDuration(longWait),
	)
}

func TestWorkspace_MultiRun_SelectPinDeselect_OverlaySeriesCount(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	require.NoError(t, cfg.SetStartupMode(leet.StartupModeWorkspaceLatest))
	require.NoError(t, cfg.SetMetricsRows(1))
	require.NoError(t, cfg.SetMetricsCols(1))

	wandbDir := t.TempDir()

	newestRunKey := "run-20260209_010102-newest"
	olderRunKey := "run-20260209_010101-older"

	writeWorkspaceRunWandbFile(t, wandbDir, newestRunKey, "newest", 1.0)
	writeWorkspaceRunWandbFile(t, wandbDir, olderRunKey, "older", 2.0)

	const W, H = 240, 60
	tm := newWorkspaceTestModel(t, cfg, wandbDir, W, H)

	// Toggle sidebars.
	tm.Type("[")
	tm.Type("[")
	tm.Type("]")
	tm.Type("]")

	// Track width bumps so forceRepaint always changes layout (teatest output consumption).
	repaintW := W

	// 1) Initial load: workspace scans wandbDir, lists runs, auto-selects + pins the newest run.
	waitForPlainOutput(t, tm,
		[]string{
			leet.PinnedRunMark + " " + newestRunKey,
			"loss",
		},
		nil,
	)

	// Exercise filtering codepath.
	tm.Type("/")
	tm.Type("l")
	tm.Type("o")
	tm.Type("s")
	tm.Type("s")
	tm.Send(tea.KeyMsg{Type: tea.KeyEnter})
	waitForPlainOutput(t, tm,
		[]string{
			"Filter",
			"loss",
			"[1/1]",
		},
		nil,
	)
	tm.Send(tea.KeyMsg{Type: tea.KeyCtrlL})

	// 2) Select the older run (down + space). Expect multi-series overlay.
	tm.Send(tea.KeyMsg{Type: tea.KeyDown})
	tm.Send(tea.KeyMsg{Type: tea.KeySpace})

	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{
			leet.PinnedRunMark + " " + newestRunKey,
			leet.SelectedRunMark + " " + olderRunKey,
			"loss",
		},
		nil,
	)

	// 3) Pin the older run. The pinned marker should move; both still selected.
	tm.Type("p")

	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{
			leet.PinnedRunMark + " " + olderRunKey,
			leet.SelectedRunMark + " " + newestRunKey,
			"loss",
		},
		nil,
	)

	// 4) Deselect the newest run (up + space). Should drop back to single run.
	tm.Send(tea.KeyMsg{Type: tea.KeyUp})
	tm.Send(tea.KeyMsg{Type: tea.KeySpace})

	forceRepaint(tm, repaintW, H)

	waitForPlainOutput(t, tm,
		[]string{
			leet.PinnedRunMark + " " + olderRunKey,
			leet.RunMark + " " + newestRunKey,
			"loss",
		},
		nil,
	)

	// Exercise navigation.
	tm.Send(tea.KeyMsg{Type: tea.KeyLeft})
	tm.Send(tea.KeyMsg{Type: tea.KeyRight})
	tm.Send(tea.KeyMsg{Type: tea.KeyTab})
	tm.Send(tea.KeyMsg{Type: tea.KeyTab})

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}

func TestConsoleLogsPanel_ToggleAppendAndNavigate(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

	// Keep layout stable and the test focused on the bottom logs panel.
	require.NoError(t, cfg.SetMetricsRows(1))
	require.NoError(t, cfg.SetMetricsCols(1))
	require.NoError(t, cfg.SetLeftSidebarVisible(false))
	require.NoError(t, cfg.SetRightSidebarVisible(false))

	// Create a writable .wandb file and keep it open to simulate a live run.
	tmp, err := os.CreateTemp(t.TempDir(), "logs-*.wandb")
	require.NoError(t, err)
	defer tmp.Close()

	writer := leveldb.NewWriterExt(tmp, leveldb.CRCAlgoIEEE, 0)
	defer func() { _ = writer.Close() }()

	// Minimal Run record (avoid loading screen).
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       "test-run",
				DisplayName: "Test Run",
				Project:     "test-project",
			},
		},
	})

	// Minimal History record so the MetricsGrid renders ("loss").
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: 1},
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: "1"},
					{NestedKey: []string{"loss"}, ValueJson: "1.0"},
				},
			},
		},
	})
	require.NoError(t, writer.Flush())

	// Height chosen so BottomBar expands to 4 lines (ratio * (H-1) => 4),
	// which yields 2 content lines. That makes paging assertions crisp.
	const W, H = 120, 15
	tm := newTestModel(t, cfg, tmp.Name(), W, H)

	// Wait for the main chart to show.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("loss")) },
		teatest.WithDuration(longWait),
	)

	// Open console logs panel.
	tm.Type("l")
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, []byte("Console Logs")) },
		teatest.WithDuration(longWait),
	)

	parseRange := func(s string) (start, end, total int, ok bool) {
		idx := strings.LastIndex(s, "Console Logs")
		if idx == -1 {
			return 0, 0, 0, false
		}
		line := s[idx:]
		if nl := strings.IndexByte(line, '\n'); nl != -1 {
			line = line[:nl]
		}
		lb := strings.IndexByte(line, '[')
		rb := strings.IndexByte(line, ']')
		if lb == -1 || rb == -1 || rb <= lb {
			return 0, 0, 0, false
		}
		content := strings.TrimSpace(line[lb+1 : rb])
		if _, err := fmt.Sscanf(content, "%d-%d of %d", &start, &end, &total); err != nil {
			return 0, 0, 0, false
		}
		return start, end, total, true
	}

	// Append output_raw console logs.
	baseTS := time.Now().Unix()
	for i := 1; i <= 10; i++ {
		writeRecord(t, writer, &spb.Record{
			RecordType: &spb.Record_OutputRaw{
				OutputRaw: &spb.OutputRawRecord{
					Line:       fmt.Sprintf("log %02d\n", i),
					OutputType: spb.OutputRawRecord_STDOUT,
					Timestamp:  &timestamppb.Timestamp{Seconds: baseTS + int64(i)},
				},
			},
		})
	}
	require.NoError(t, writer.Flush())

	// Trigger live read + redraw.
	tm.Send(leet.FileChangedMsg{})

	// Track width bumps so we always get fresh bytes after WaitFor consumes output.
	repaintW := W
	forceRepaint(tm, repaintW, H)
	repaintW++

	// Wait until:
	// - log 10 is visible (auto-scroll)
	// - range is present and shows 2 visible rows (expanded height 4 => 2 content lines)
	var start0, end0, total0 int
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			s := stripANSI(string(b))
			if !strings.Contains(s, "log 10") {
				return false
			}
			st, en, tot, ok := parseRange(s)
			if !ok || tot < 2 {
				return false
			}
			if en-st+1 != 2 {
				// Not fully expanded yet (during animation it may show fewer rows).
				return false
			}
			start0, end0, total0 = st, en, tot
			_ = end0 // captured for debugging; start0/total0 used below
			return true
		},
		teatest.WithDuration(longWait),
	)

	// Focus logs (tab) and page up (left).
	tm.Send(tea.KeyMsg{Type: tea.KeyTab})
	tm.Send(tea.KeyMsg{Type: tea.KeyLeft})
	forceRepaint(tm, repaintW, H)
	repaintW++

	var start1, total1 int
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			s := stripANSI(string(b))
			st, _, tot, ok := parseRange(s)
			if !ok {
				return false
			}
			start1, total1 = st, tot
			return total1 == total0 && start1 < start0
		},
		teatest.WithDuration(longWait),
	)

	// Page down (right) back toward the end.
	tm.Send(tea.KeyMsg{Type: tea.KeyRight})
	forceRepaint(tm, repaintW, H)
	repaintW++

	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			s := stripANSI(string(b))
			st, _, tot, ok := parseRange(s)
			return ok && tot == total0 && st > start1 && strings.Contains(s, "log 10")
		},
		teatest.WithDuration(longWait),
	)

	// Close console logs panel.
	tm.Type("l")
	forceRepaint(tm, repaintW, H)

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}

func writeWorkspaceRunWandbFileWithStatsAndLogs(
	t *testing.T,
	wandbDir, runKey, runID string,
) string {
	t.Helper()

	runFile := filepath.Join(wandbDir, runKey, "run-"+runID+".wandb")
	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))

	f, err := os.Create(runFile)
	require.NoError(t, err)
	defer func() { _ = f.Close() }()

	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)

	// Run record.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       runID,
				DisplayName: runID,
				Project:     "test-project",
			},
		},
	})

	// History record.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: 1},
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: "1"},
					{NestedKey: []string{"loss"}, ValueJson: "0.5"},
				},
			},
		},
	})

	// Stats records (two timestamps → chart can render).
	ts := time.Now().Unix()
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				Timestamp: &timestamppb.Timestamp{Seconds: ts},
				Item: []*spb.StatsItem{
					{Key: "gpu.0.temp", ValueJson: "45"},
					{Key: "cpu.0.cpu_percent", ValueJson: "60"},
				},
			},
		},
	})
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Stats{
			Stats: &spb.StatsRecord{
				Timestamp: &timestamppb.Timestamp{Seconds: ts + 1},
				Item: []*spb.StatsItem{
					{Key: "gpu.0.temp", ValueJson: "47"},
					{Key: "cpu.0.cpu_percent", ValueJson: "62"},
				},
			},
		},
	})

	// Console log record.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_OutputRaw{
			OutputRaw: &spb.OutputRawRecord{
				Line:       "epoch 1 complete\n",
				OutputType: spb.OutputRawRecord_STDOUT,
				Timestamp:  &timestamppb.Timestamp{Seconds: ts},
			},
		},
	})

	// Exit record so the reader processes everything.
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{ExitCode: 0},
		},
	})

	require.NoError(t, writer.Flush())
	require.NoError(t, writer.Close())

	return runFile
}

func TestWorkspace_SystemMetricsPaneAndConsoleLogs(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping in short mode")
	}

	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	require.NoError(t, cfg.SetStartupMode(leet.StartupModeWorkspaceLatest))

	wandbDir := t.TempDir()
	runKey := "run-20260209_010101-smlogtest"
	writeWorkspaceRunWandbFileWithStatsAndLogs(t, wandbDir, runKey, "smlogtest")

	const W, H = 240, 80
	tm := newWorkspaceTestModel(t, cfg, wandbDir, W, H)
	repaintW := W

	// 1) Wait for workspace to discover the run and render the main metrics.
	waitForPlainOutput(t, tm,
		[]string{"loss", runKey},
		nil,
	)

	// 2) Toggle system metrics pane ('s').
	tm.Type("s")
	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{leet.WorkspaceSystemMetricsPaneHeader},
		nil,
	)

	// After the pane animation + data load, GPU Temp chart should appear.
	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{"GPU Temp"},
		nil,
	)

	// 3) Toggle console logs ('l').
	tm.Type("l")
	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{"Console Logs"},
		nil,
	)

	// Console log content from the OutputRaw record.
	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{"epoch 1 complete"},
		nil,
	)

	// 4) Both panes visible simultaneously.
	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{leet.WorkspaceSystemMetricsPaneHeader, "Console Logs", "loss"},
		nil,
	)

	// 5) Close both panes.
	tm.Type("s")
	forceRepaint(tm, repaintW, H)
	repaintW++

	tm.Type("l")
	forceRepaint(tm, repaintW, H)

	// 6) Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}
