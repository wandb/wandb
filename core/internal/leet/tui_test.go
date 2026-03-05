package leet_test

import (
	"fmt"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// const (
// 	shortWait = 2 * time.Second
// 	longWait  = 3 * time.Second
// )

// TODO: teatest is not yet fully compatible with bubbletea v2.

// // waitForContent is a v2-compatible replacement for teatest.WaitFor.
// //
// // The v2 Cursed Renderer sends differential updates, so any single read
// // from tm.Output() may contain only the changed cells — not the full
// // terminal state. This helper accumulates all bytes received, strips
// // all escape sequences, and checks the accumulated text on each read.
// func waitForContent(
// 	t *testing.T, r io.Reader, cond func(string) bool, opts ...teatest.WaitForOption) {
// 	t.Helper()
// 	var acc bytes.Buffer
// 	teatest.WaitFor(t, r, func(b []byte) bool {
// 		acc.Write(b)
// 		return cond(stripANSI(acc.String()))
// 	}, opts...)
// }

// // newTestModel creates a test model and sends an initial WindowSizeMsg to force the first render.
// // The model's View returns "Loading..." until width/height are non-zero, so we always size first.
// // Uses the full Model (not bare Run) so help and mode-switching work correctly.
// func newTestModel(
// 	t *testing.T,
// 	cfg *leet.ConfigManager,
// 	runPath string,
// 	w, h int,
// ) *teatest.TestModel {
// 	t.Helper()
// 	logger := observability.NewNoOpLogger()
// 	m := leet.NewModel(leet.ModelParams{
// 		RunFile: runPath,
// 		Config:  cfg,
// 		Logger:  logger,
// 	})
// 	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(w, h))
// 	tm.Send(tea.WindowSizeMsg{Width: w, Height: h})
// 	return tm
// }

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

// // forceRepaint nudges Bubble Tea to produce a fresh frame.
// // Why needed: teatest.WaitFor consumes tm.Output(). Without a new render, a second
// // WaitFor may time out even if the content is already on-screen. Sending a slightly
// // different WindowSizeMsg ensures Update runs and View emits new bytes.
// func forceRepaint(tm *teatest.TestModel, w, h int) {
// 	tm.Send(tea.WindowSizeMsg{Width: w + 1, Height: h})
// }

// func TestLoadingScreenAndQuit(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
// 	tm := newTestModel(t, cfg, "no/such/file.wandb", 100, 30)

// 	// Wait for loading screen text.
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "Loading data...") },
// 		teatest.WithDuration(shortWait),
// 	)

// 	// Quit.
// 	tm.Type("q")
// 	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
// }

// func TestMetricsAndSystemMetrics_RenderAndSeriesCount(t *testing.T) {
// 	if testing.Short() {
// 		t.Skip("skipping in short mode")
// 	}
// 	logger := observability.NewNoOpLogger()
// 	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
// 	_ = cfg.SetSystemRows(2)
// 	_ = cfg.SetSystemCols(2)
// 	_ = cfg.SetRightSidebarVisible(true)

// 	// Create a writable .wandb file and keep it open to simulate a live run.
// 	tmp, err := os.CreateTemp(t.TempDir(), "test-*.wandb")
// 	if err != nil {
// 		t.Fatalf("CreateTemp: %v", err)
// 	}
// 	defer tmp.Close()
// 	writer := leveldb.NewWriterExt(tmp, leveldb.CRCAlgoIEEE, 0)

// 	// Seed minimal run + metrics so both the main grid and system grid can render.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Run{
// 			Run: &spb.RunRecord{
// 				RunId:       "test-run",
// 				DisplayName: "Test Run",
// 				Project:     "test-project",
// 			},
// 		},
// 	})
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_History{
// 			History: &spb.HistoryRecord{
// 				Step: &spb.HistoryStep{Num: 1},
// 				Item: []*spb.HistoryItem{
// 					{NestedKey: []string{"_step"}, ValueJson: "1"},
// 					{NestedKey: []string{"loss"}, ValueJson: "1.0"},
// 				},
// 			},
// 		},
// 	})

// 	ts := time.Now().Unix()
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Stats{
// 			Stats: &spb.StatsRecord{
// 				Timestamp: &timestamppb.Timestamp{Seconds: ts},
// 				Item: []*spb.StatsItem{
// 					{Key: "gpu.0.temp", ValueJson: "40"},
// 					{Key: "gpu.1.temp", ValueJson: "42"},
// 					{Key: "cpu.0.cpu_percent", ValueJson: "55"},
// 				},
// 			},
// 		},
// 	})
// 	require.NoError(t, writer.Flush())

// 	// Spin up the TUI against the live file.
// 	const W, H = 240, 80
// 	tm := newTestModel(t, cfg, tmp.Name(), W, H)

// 	// Track width bumps so each forceRepaint produces a distinct layout,
// 	// forcing the Cursed Renderer to re-send content.
// 	repaintW := W

// 	// Wait for the main grid to show (loss chart).
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "loss") },
// 		teatest.WithDuration(longWait),
// 	)

// 	// Force a fresh frame for the next assertion.
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	// Assert the right sidebar header renders.
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "System Metrics") },
// 		teatest.WithDuration(longWait),
// 	)

// 	// Append more stats (2 GPUs -> series count [2]) and notify the app.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Stats{
// 			Stats: &spb.StatsRecord{
// 				Timestamp: &timestamppb.Timestamp{Seconds: ts + 1},
// 				Item: []*spb.StatsItem{
// 					{Key: "gpu.0.temp", ValueJson: "41"},
// 					{Key: "gpu.1.temp", ValueJson: "43"},
// 					{Key: "cpu.0.cpu_percent", ValueJson: "56"},
// 				},
// 			},
// 		},
// 	})
// 	require.NoError(t, writer.Flush())
// 	tm.Send(leet.FileChangedMsg{}) // triggers ReadAvailableRecords + redraw in Update.

// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	// Expect the GPU Temp chart with series count [2] and the CPU Core chart.
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool {
// 			return strings.Contains(s, "GPU Temp") &&
// 				strings.Contains(s, "[2]") &&
// 				strings.Contains(s, "CPU Core")
// 		},
// 		teatest.WithDuration(longWait),
// 	)

// 	// Add a 3rd GPU and then a RunExit, close the writer, and notify again.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Stats{
// 			Stats: &spb.StatsRecord{
// 				Timestamp: &timestamppb.Timestamp{Seconds: ts + 2},
// 				Item: []*spb.StatsItem{
// 					{Key: "gpu.0.temp", ValueJson: "41"},
// 					{Key: "gpu.1.temp", ValueJson: "43"},
// 					{Key: "gpu.2.temp", ValueJson: "44"},
// 					{Key: "cpu.0.cpu_percent", ValueJson: "57"},
// 				},
// 			},
// 		},
// 	})
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Exit{
// 			Exit: &spb.RunExitRecord{ExitCode: 0},
// 		},
// 	})
// 	require.NoError(t, writer.Close())
// 	tm.Send(leet.FileChangedMsg{}) // live read + redraw.

// 	// Force a complete redraw so [3] appears as a contiguous string.
// 	// Without this, the differential renderer only overwrites the digit
// 	// "2" -> "3", and the accumulated text has "[2]...3" not "[3]".
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	// Wait for the series count [3].
// 	// waitForContent(t, tm.Output(),
// 	// 	func(s string) bool { return strings.Contains(s, "[3]") },
// 	// 	teatest.WithDuration(longWait),
// 	// )

// 	// Toggle help on, then assert the banner appears, then toggle it off.
// 	tm.Type("h")
// 	forceRepaint(tm, repaintW, H)

// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "LEET") },
// 		teatest.WithDuration(shortWait),
// 	)
// 	tm.Type("h")

// 	// Quit.
// 	tm.Type("q")
// 	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
// }

// // newWorkspaceTestModel mirrors newTestModel from tui_test.go but starts in workspace mode.
// func newWorkspaceTestModel(
// 	t *testing.T,
// 	cfg *leet.ConfigManager,
// 	wandbDir string,
// 	w, h int,
// ) *teatest.TestModel {
// 	t.Helper()
// 	logger := observability.NewNoOpLogger()

// 	m := leet.NewModel(leet.ModelParams{
// 		WandbDir: wandbDir,
// 		Config:   cfg,
// 		Logger:   logger,
// 	})

// 	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(w, h))
// 	tm.Send(tea.WindowSizeMsg{Width: w, Height: h})
// 	return tm
// }

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

// // waitForPlainOutput is an accumulating WaitFor that strips all ANSI sequences
// // before checking want/notWant substrings.
// func waitForPlainOutput(
// 	t *testing.T,
// 	tm *teatest.TestModel,
// 	want []string,
// 	notWant []string,
// ) {
// 	t.Helper()

// 	waitForContent(t, tm.Output(),
// 		func(s string) bool {
// 			for _, w := range want {
// 				if !strings.Contains(s, w) {
// 					return false
// 				}
// 			}
// 			for _, nw := range notWant {
// 				if strings.Contains(s, nw) {
// 					return false
// 				}
// 			}
// 			return true
// 		},
// 		teatest.WithDuration(longWait),
// 	)
// }

// func TestWorkspace_MultiRun_SelectPinDeselect_OverlaySeriesCount(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

// 	require.NoError(t, cfg.SetStartupMode(leet.StartupModeWorkspaceLatest))
// 	require.NoError(t, cfg.SetMetricsRows(1))
// 	require.NoError(t, cfg.SetMetricsCols(1))

// 	wandbDir := t.TempDir()

// 	newestRunKey := "run-20260209_010102-newest"
// 	olderRunKey := "run-20260209_010101-older"

// 	writeWorkspaceRunWandbFile(t, wandbDir, newestRunKey, "newest", 1.0)
// 	writeWorkspaceRunWandbFile(t, wandbDir, olderRunKey, "older", 2.0)

// 	const W, H = 240, 60
// 	tm := newWorkspaceTestModel(t, cfg, wandbDir, W, H)

// 	// Toggle sidebars.
// 	tm.Type("[")
// 	tm.Type("[")
// 	tm.Type("]")
// 	tm.Type("]")

// 	// Track width bumps so forceRepaint always changes layout (teatest output consumption).
// 	repaintW := W

// 	// 1) Initial load: workspace scans wandbDir, lists runs, auto-selects + pins the newest run.
// 	waitForPlainOutput(t, tm,
// 		[]string{
// 			leet.PinnedRunMark + " " + newestRunKey,
// 			"loss",
// 		},
// 		nil,
// 	)

// 	// Exercise filtering codepath.
// 	tm.Type("/")
// 	tm.Type("l")
// 	tm.Type("o")
// 	tm.Type("s")
// 	tm.Type("s")
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyEnter})
// 	waitForPlainOutput(t, tm,
// 		[]string{
// 			"Filter",
// 			"loss",
// 			"[1/1]",
// 		},
// 		nil,
// 	)
// 	tm.Send(tea.KeyPressMsg{Code: 'l', Mod: tea.ModCtrl})

// 	// 2) Select the older run (down + space). Expect multi-series overlay.
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyDown})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeySpace})

// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{
// 			leet.PinnedRunMark + " " + newestRunKey,
// 			leet.SelectedRunMark + " " + olderRunKey,
// 			"loss",
// 		},
// 		nil,
// 	)

// 	// 3) Pin the older run. The pinned marker should move; both still selected.
// 	tm.Type("p")

// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{
// 			leet.PinnedRunMark + " " + olderRunKey,
// 			leet.SelectedRunMark + " " + newestRunKey,
// 			"loss",
// 		},
// 		nil,
// 	)

// 	// 4) Deselect the newest run (up + space). Should drop back to single run.
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyUp})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeySpace})

// 	forceRepaint(tm, repaintW, H)

// 	waitForPlainOutput(t, tm,
// 		[]string{
// 			leet.PinnedRunMark + " " + olderRunKey,
// 			leet.RunMark + " " + newestRunKey,
// 			"loss",
// 		},
// 		nil,
// 	)

// 	// Exercise navigation.
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyLeft})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyRight})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyTab})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyTab})

// 	// Quit.
// 	tm.Type("q")
// 	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
// }

// // consoleLogsRangeRe matches "Console Logs" followed by a bracketed range
// // anywhere in the accumulated (stripped) text, allowing arbitrary characters
// // between them since differential frames may interleave content.
// var consoleLogsRangeRe = regexp.MustCompile(`Console Logs[^\[]*\[(\d+)-(\d+) of (\d+)\]`)

// func TestConsoleLogsPanel_ToggleAppendAndNavigate(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)

// 	// Keep layout stable and the test focused on the bottom logs panel.
// 	require.NoError(t, cfg.SetMetricsRows(1))
// 	require.NoError(t, cfg.SetMetricsCols(1))
// 	require.NoError(t, cfg.SetLeftSidebarVisible(false))
// 	require.NoError(t, cfg.SetRightSidebarVisible(false))

// 	// Create a writable .wandb file and keep it open to simulate a live run.
// 	tmp, err := os.CreateTemp(t.TempDir(), "logs-*.wandb")
// 	require.NoError(t, err)
// 	defer tmp.Close()

// 	writer := leveldb.NewWriterExt(tmp, leveldb.CRCAlgoIEEE, 0)
// 	defer func() { _ = writer.Close() }()

// 	// Minimal Run record (avoid loading screen).
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Run{
// 			Run: &spb.RunRecord{
// 				RunId:       "test-run",
// 				DisplayName: "Test Run",
// 				Project:     "test-project",
// 			},
// 		},
// 	})

// 	// Minimal History record so the MetricsGrid renders ("loss").
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_History{
// 			History: &spb.HistoryRecord{
// 				Step: &spb.HistoryStep{Num: 1},
// 				Item: []*spb.HistoryItem{
// 					{NestedKey: []string{"_step"}, ValueJson: "1"},
// 					{NestedKey: []string{"loss"}, ValueJson: "1.0"},
// 				},
// 			},
// 		},
// 	})
// 	require.NoError(t, writer.Flush())

// 	// Height chosen so ConsoleLogsPane expands to 4 lines (ratio * (H-1) => 4),
// 	// which yields 2 content lines. That makes paging assertions crisp.
// 	const W, H = 120, 15
// 	tm := newTestModel(t, cfg, tmp.Name(), W, H)

// 	// Wait for the main chart to show.
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "loss") },
// 		teatest.WithDuration(longWait),
// 	)

// 	// Open console logs panel.
// 	tm.Type("l")
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool { return strings.Contains(s, "Console Logs") },
// 		teatest.WithDuration(longWait),
// 	)

// 	// parseRange extracts the [start-end of total] range from the accumulated
// 	// stripped text using a regex, taking the last match (most recent frame).
// 	parseRange := func(s string) (start, end, total int, ok bool) {
// 		matches := consoleLogsRangeRe.FindAllStringSubmatch(s, -1)
// 		if len(matches) == 0 {
// 			return 0, 0, 0, false
// 		}
// 		// Use the last match (most recent render).
// 		m := matches[len(matches)-1]
// 		_, _ = fmt.Sscanf(m[1], "%d", &start)
// 		_, _ = fmt.Sscanf(m[2], "%d", &end)
// 		_, _ = fmt.Sscanf(m[3], "%d", &total)
// 		return start, end, total, true
// 	}

// 	// Append output_raw console logs.
// 	baseTS := time.Now().Unix()
// 	for i := 1; i <= 10; i++ {
// 		writeRecord(t, writer, &spb.Record{
// 			RecordType: &spb.Record_OutputRaw{
// 				OutputRaw: &spb.OutputRawRecord{
// 					Line:       fmt.Sprintf("log %02d\n", i),
// 					OutputType: spb.OutputRawRecord_STDOUT,
// 					Timestamp:  &timestamppb.Timestamp{Seconds: baseTS + int64(i)},
// 				},
// 			},
// 		})
// 	}
// 	require.NoError(t, writer.Flush())

// 	// Trigger live read + redraw.
// 	tm.Send(leet.FileChangedMsg{})

// 	// Track width bumps so we always get fresh bytes after WaitFor consumes output.
// 	repaintW := W
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	// Wait until:
// 	// - log 10 is visible (auto-scroll)
// 	// - range is present and shows 2 visible rows (expanded height 4 => 2 content lines)
// 	var start0, end0, total0 int
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool {
// 			if !strings.Contains(s, "log 10") {
// 				return false
// 			}
// 			st, en, tot, ok := parseRange(s)
// 			if !ok || tot < 2 {
// 				return false
// 			}
// 			if en-st+1 != 2 {
// 				// Not fully expanded yet (during animation it may show fewer rows).
// 				return false
// 			}
// 			start0, end0, total0 = st, en, tot
// 			_ = end0 // captured for debugging; start0/total0 used below
// 			return true
// 		},
// 		teatest.WithDuration(longWait),
// 	)

// 	// Focus logs (tab) and page up (left).
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyTab})
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyLeft})
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	var start1, total1 int
// 	waitForContent(t, tm.Output(),
// 		func(s string) bool {
// 			st, _, tot, ok := parseRange(s)
// 			if !ok {
// 				return false
// 			}
// 			start1, total1 = st, tot
// 			return total1 == total0 && start1 < start0
// 		},
// 		teatest.WithDuration(longWait),
// 	)

// 	// Page down (right) back toward the end.
// 	tm.Send(tea.KeyPressMsg{Code: tea.KeyRight})
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForContent(t, tm.Output(),
// 		func(s string) bool {
// 			st, _, tot, ok := parseRange(s)
// 			return ok && tot == total0 && st > start1 && strings.Contains(s, "log 10")
// 		},
// 		teatest.WithDuration(longWait),
// 	)

// 	// Close console logs panel.
// 	tm.Type("l")
// 	forceRepaint(tm, repaintW, H)

// 	// Quit.
// 	tm.Type("q")
// 	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
// }

// func writeWorkspaceRunWandbFileWithStatsAndLogs(
// 	t *testing.T,
// 	wandbDir, runKey, runID string,
// ) string {
// 	t.Helper()

// 	runFile := filepath.Join(wandbDir, runKey, "run-"+runID+".wandb")
// 	require.NoError(t, os.MkdirAll(filepath.Dir(runFile), 0o755))

// 	f, err := os.Create(runFile)
// 	require.NoError(t, err)
// 	defer func() { _ = f.Close() }()

// 	writer := leveldb.NewWriterExt(f, leveldb.CRCAlgoIEEE, 0)

// 	// Run record.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Run{
// 			Run: &spb.RunRecord{
// 				RunId:       runID,
// 				DisplayName: runID,
// 				Project:     "test-project",
// 			},
// 		},
// 	})

// 	// History record.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_History{
// 			History: &spb.HistoryRecord{
// 				Step: &spb.HistoryStep{Num: 1},
// 				Item: []*spb.HistoryItem{
// 					{NestedKey: []string{"_step"}, ValueJson: "1"},
// 					{NestedKey: []string{"loss"}, ValueJson: "0.5"},
// 				},
// 			},
// 		},
// 	})

// 	// Stats records (two timestamps -> chart can render).
// 	ts := time.Now().Unix()
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Stats{
// 			Stats: &spb.StatsRecord{
// 				Timestamp: &timestamppb.Timestamp{Seconds: ts},
// 				Item: []*spb.StatsItem{
// 					{Key: "gpu.0.temp", ValueJson: "45"},
// 					{Key: "cpu.0.cpu_percent", ValueJson: "60"},
// 				},
// 			},
// 		},
// 	})
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Stats{
// 			Stats: &spb.StatsRecord{
// 				Timestamp: &timestamppb.Timestamp{Seconds: ts + 1},
// 				Item: []*spb.StatsItem{
// 					{Key: "gpu.0.temp", ValueJson: "47"},
// 					{Key: "cpu.0.cpu_percent", ValueJson: "62"},
// 				},
// 			},
// 		},
// 	})

// 	// Console log record.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_OutputRaw{
// 			OutputRaw: &spb.OutputRawRecord{
// 				Line:       "epoch 1 complete\n",
// 				OutputType: spb.OutputRawRecord_STDOUT,
// 				Timestamp:  &timestamppb.Timestamp{Seconds: ts},
// 			},
// 		},
// 	})

// 	// Exit record so the reader processes everything.
// 	writeRecord(t, writer, &spb.Record{
// 		RecordType: &spb.Record_Exit{
// 			Exit: &spb.RunExitRecord{ExitCode: 0},
// 		},
// 	})

// 	require.NoError(t, writer.Flush())
// 	require.NoError(t, writer.Close())

// 	return runFile
// }

// func TestWorkspace_SystemMetricsPaneAndConsoleLogs(t *testing.T) {
// 	if testing.Short() {
// 		t.Skip("skipping in short mode")
// 	}

// 	logger := observability.NewNoOpLogger()
// 	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
// 	require.NoError(t, cfg.SetStartupMode(leet.StartupModeWorkspaceLatest))

// 	wandbDir := t.TempDir()
// 	runKey := "run-20260209_010101-smlogtest"
// 	writeWorkspaceRunWandbFileWithStatsAndLogs(t, wandbDir, runKey, "smlogtest")

// 	const W, H = 240, 80
// 	tm := newWorkspaceTestModel(t, cfg, wandbDir, W, H)
// 	repaintW := W

// 	// 1) Wait for workspace to discover the run and render the main metrics.
// 	waitForPlainOutput(t, tm,
// 		[]string{"loss", runKey},
// 		nil,
// 	)

// 	// 2) Toggle system metrics pane ('s').
// 	tm.Type("s")
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{leet.WorkspaceSystemMetricsPaneHeader},
// 		nil,
// 	)

// 	// After the pane animation + data load, GPU Temp chart should appear.
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{"GPU Temp"},
// 		nil,
// 	)

// 	// 3) Toggle console logs ('l').
// 	tm.Type("l")
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{"Console Logs"},
// 		nil,
// 	)

// 	// Console log content from the OutputRaw record.
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{"epoch 1 complete"},
// 		nil,
// 	)

// 	// 4) Both panes visible simultaneously.
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	waitForPlainOutput(t, tm,
// 		[]string{leet.WorkspaceSystemMetricsPaneHeader, "Console Logs", "loss"},
// 		nil,
// 	)

// 	// 5) Close both panes.
// 	tm.Type("s")
// 	forceRepaint(tm, repaintW, H)
// 	repaintW++

// 	tm.Type("l")
// 	forceRepaint(tm, repaintW, H)

// 	// 6) Quit.
// 	tm.Type("q")
// 	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
// }

func TestParseStartupArgs(t *testing.T) {
	args := []string{
		"-base-url",
		"https://api.wandb.ai",
		"-entity",
		"test-entity",
		"-project",
		"test-project",
		"-run-id",
		"test-run-id",
	}
	startupArgs, err := leet.ParseStartupArgs(args)

	require.NoError(t, err)
	require.Equal(t, "https://api.wandb.ai", *startupArgs.BaseURL)
	require.Equal(t, "test-entity", *startupArgs.Entity)
	require.Equal(t, "test-project", *startupArgs.Project)
	require.Equal(t, "test-run-id", *startupArgs.RunId)
}

func TestParseStartupArgs_InvalidArgs(t *testing.T) {
	args := []string{
		"-invalid-arg",
		"invalid",
		"-entity",
		"test-entity",
		"-project",
		"test-project",
	}
	_, err := leet.ParseStartupArgs(args)
	require.Error(t, err)
}

func TestCreateModelParams_LocalRun(t *testing.T) {
	wandbDir := "testdata/wandb"
	runFile := "testdata/wandb/run-1234567890.wandb"
	startupArgs := &leet.StartupArgs{
		RunFile:  &runFile,
		WandbDir: wandbDir,
	}

	modelParams := leet.CreateModelParams(startupArgs, observability.NewNoOpLogger())

	require.NotNil(t, modelParams.Backend)
	require.Equal(t, &leet.RunParams{
		LocalRunParams: &leet.LocalRunParams{
			RunFile: runFile,
		},
	}, modelParams.RunParams)
}

func TestCreateModelParams_RemoteRun(t *testing.T) {
	baseURL := "https://api.wandb.ai"
	entity := "test-entity"
	project := "test-project"
	runId := "test-run-id"
	startupArgs := &leet.StartupArgs{
		BaseURL: &baseURL,
		Entity:  &entity,
		Project: &project,
		RunId:   &runId,
	}

	modelParams := leet.CreateModelParams(startupArgs, observability.NewNoOpLogger())

	require.NotNil(t, modelParams.Backend)
	require.Equal(t, &leet.RunParams{
		RemoteRunParams: &leet.RemoteRunParams{
			BaseURL: baseURL,
			Entity:  entity,
			Project: project,
			RunId:   runId,
		},
	}, modelParams.RunParams)
}
