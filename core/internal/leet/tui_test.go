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

	// Keep the viewport simple and stable for assertions.
	require.NoError(t, cfg.SetStartupMode(leet.StartupModeWorkspaceLatest))
	require.NoError(t, cfg.SetMetricsRows(1))
	require.NoError(t, cfg.SetMetricsCols(1))

	wandbDir := t.TempDir()

	// Names intentionally follow the expected wandb run dir format so sorting is deterministic.
	// parseRunDirTimestamp sorts descending, so *_010102 is considered newer than *_010101.
	newestRunKey := "run-20260209_010102-newest"
	olderRunKey := "run-20260209_010101-older"

	writeWorkspaceRunWandbFile(t, wandbDir, newestRunKey, "newest", 1.0)
	writeWorkspaceRunWandbFile(t, wandbDir, olderRunKey, "older", 2.0)

	const W, H = 240, 60
	tm := newWorkspaceTestModel(t, cfg, wandbDir, W, H)

	// Track width bumps so forceRepaint always changes layout (teatest output consumption).
	repaintW := W

	// 1) Initial load: workspace scans wandbDir, lists runs, auto-selects + pins the newest run.
	waitForPlainOutput(t, tm,
		[]string{
			"Runs: 1/2 selected",
			"Pinned: " + newestRunKey,
			"▶ " + newestRunKey,
			"loss",
		},
		nil,
	)

	// 2) Select the older run (down + space). Expect multi-series overlay.
	tm.Send(tea.KeyMsg{Type: tea.KeyDown})
	tm.Send(tea.KeyMsg{Type: tea.KeySpace})

	forceRepaint(tm, repaintW, H)
	repaintW++

	waitForPlainOutput(t, tm,
		[]string{
			"Runs: 2/2 selected",
			"Pinned: " + newestRunKey,
			"▶ " + newestRunKey,
			"● " + olderRunKey,
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
			"Runs: 2/2 selected",
			"Pinned: " + olderRunKey,
			"▶ " + olderRunKey,
			"● " + newestRunKey,
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
			"Runs: 1/2 selected",
			"Pinned: " + olderRunKey,
			"▶ " + olderRunKey,
			"○ " + newestRunKey,
			"loss",
		},
		nil,
	)

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}
