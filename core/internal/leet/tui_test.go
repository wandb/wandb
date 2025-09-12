package leet_test

import (
	"bytes"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/charmbracelet/x/exp/teatest"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/pkg/leveldb"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

const (
	shortWait = 2 * time.Second
	longWait  = 3 * time.Second
)

// containsTTY normalizes control codes, box drawing glyphs, and whitespace
// so that assertions focus on semantic content rather than terminal layout.
func containsTTY(b []byte, want string) bool {
	normalize := func(s string) string {
		// Strip CSI (e.g. \x1b[2J, \x1b[H, \x1b[?25l), OSC (\x1b]... \x07), and single ESC sequences.
		csi := regexp.MustCompile(`\x1b\[[0-9;?]*[A-Za-z]`)
		osc := regexp.MustCompile(`\x1b\].*?\x07`)
		esc := regexp.MustCompile(`\x1b.`) // fallback for ESC+X
		s = csi.ReplaceAllString(s, "")
		s = osc.ReplaceAllString(s, "")
		s = esc.ReplaceAllString(s, "")

		// Remove box drawing chars and borders that may interleave with text.
		s = strings.NewReplacer(
			"│", "", "─", "", "╭", "", "╮", "", "╰", "", "╯", "",
			"┌", "", "┐", "", "└", "", "┘", "",
		).Replace(s)

		// Drop all whitespace (space, tabs, newlines).
		ws := regexp.MustCompile(`\s+`)
		s = ws.ReplaceAllString(s, "")
		return strings.ToLower(s)
	}
	return strings.Contains(normalize(string(b)), normalize(want))
}

// newTestModel creates a test model and sends an initial WindowSizeMsg to force the first render.
// The model's View returns "Loading..." until width/height are non-zero, so we always size first.
// (See Model.View early return.)
func newTestModel(t *testing.T, runPath string, w, h int) (*teatest.TestModel, *leet.Model) {
	t.Helper()
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(runPath, logger)
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(w, h))
	tm.Send(tea.WindowSizeMsg{Width: w, Height: h})
	return tm, m
}

// writeRecord marshals and writes a single protobuf record to the leveldb writer.
func writeRecord(t *testing.T, w *leveldb.Writer, rec *spb.Record) {
	t.Helper()
	data, err := proto.Marshal(rec)
	if err != nil {
		t.Fatalf("marshal record: %v", err)
	}
	dst, err := w.Next()
	if err != nil {
		t.Fatalf("writer.Next: %v", err)
	}
	if _, err := dst.Write(data); err != nil {
		t.Fatalf("writer.Write: %v", err)
	}
}

// forceRepaint nudges Bubble Tea to produce a fresh frame.
// Why needed: teatest.WaitFor consumes tm.Output(). Without a new render, a second
// WaitFor may time out even if the content is already on-screen. Sending a slightly
// different WindowSizeMsg ensures Update runs and View emits new bytes.
func forceRepaint(tm *teatest.TestModel, w, h int) {
	tm.Send(tea.WindowSizeMsg{Width: w + 1, Height: h})
}

func TestLoadingScreenAndQuit(t *testing.T) {
	tm, _ := newTestModel(t, "no/such/file.wandb", 100, 30)

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
	// Configure a visible 2x2 system metrics grid.
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load config: %v", err)
	}
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
			Run: &spb.RunRecord{RunId: "test-run", DisplayName: "Test Run", Project: "test-project"},
		},
	})
	writeRecord(t, writer, &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
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
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush writer: %v", err)
	}

	// Spin up the TUI against the live file.
	const W, H = 240, 80
	tm, _ := newTestModel(t, tmp.Name(), W, H)

	// Wait for the main grid to show (loss chart).
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return containsTTY(b, "loss") },
		teatest.WithDuration(longWait),
	)

	// Force a fresh frame for the next assertion.
	//
	// Why: teatest.WaitFor reads and consumes tm.Output(). The "loss" wait above
	// may have already consumed the bytes that contained the "System Metrics"
	// header. We must trigger a new render so the next WaitFor can observe it.
	// WindowSizeMsg goes through the model's Update → handleOther(WindowSizeMsg) path,
	// which updates widths/heights and re-computes layout, causing a redraw. :contentReference[oaicite:4]{index=4} :contentReference[oaicite:5]{index=5}
	forceRepaint(tm, W, H)

	// Assert the right sidebar header renders (it can be empty if width ≤ 3). :contentReference[oaicite:6]{index=6}
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return containsTTY(b, "System Metrics") },
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
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush writer: %v", err)
	}
	tm.Send(leet.FileChangedMsg{}) // triggers ReadAvailableRecords + redraw in Update. :contentReference[oaicite:7]{index=7} :contentReference[oaicite:8]{index=8}

	forceRepaint(tm, 241, 80)

	// Expect the GPU Temp chart with series count [2] and the CPU Core chart.
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return containsTTY(b, "GPU Temp") && containsTTY(b, "[2]") && containsTTY(b, "CPU Core")
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
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	tm.Send(leet.FileChangedMsg{}) // live read + redraw. :contentReference[oaicite:9]{index=9} :contentReference[oaicite:10]{index=10}

	// Wait for the series count [3].
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return containsTTY(b, "[3]") },
		teatest.WithDuration(longWait),
	)

	// Toggle help on, then assert the banner appears, then toggle it off.
	tm.Type("h")
	forceRepaint(tm, 240, 80)
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return containsTTY(b, "LEET") },
		teatest.WithDuration(shortWait),
	)
	tm.Type("h")

	// Quit.
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(shortWait))
}
