package leet_test

import (
	"bytes"
	"fmt"
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

// containsTTY is tolerant of ANSI/OSC/cursor codes and box-drawing glyphs.
// It normalizes both the output stream and the wanted string and performs a substring check.
func containsTTY(b []byte, want string) bool {
	normalize := func(s string) string {
		// Strip CSI (e.g. \x1b[2J, \x1b[H, \x1b[?25l), OSC (\x1b]... \x07), and single ESC sequences.
		csi := regexp.MustCompile(`\x1b\[[0-9;?]*[A-Za-z]`)
		osc := regexp.MustCompile(`\x1b\].*?\x07`)
		esc := regexp.MustCompile(`\x1b.`) // fallback for any stray ESC+X
		s = csi.ReplaceAllString(s, "")
		s = osc.ReplaceAllString(s, "")
		s = esc.ReplaceAllString(s, "")

		// Remove box drawing chars and borders that can get interleaved.
		replacer := strings.NewReplacer(
			"│", "", "─", "", "╭", "", "╮", "", "╰", "", "╯", "",
			"┌", "", "┐", "", "└", "", "┘", "",
		)
		s = replacer.Replace(s)

		// Remove all whitespace characters; tests compare semantic content not layout.
		// Using a regex with \s is more robust than replacing just spaces and newlines.
		ws := regexp.MustCompile(`\s+`)
		s = ws.ReplaceAllString(s, "")

		return strings.ToLower(s)
	}
	out := normalize(string(b))
	needle := normalize(want)
	return strings.Contains(out, needle)
}

func TestTUI_LoadingAndQuit_Teatest(t *testing.T) {
	logger := observability.NewNoOpLogger()
	m := leet.NewModel("no/such/file.wandb", logger)

	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(100, 30))

	// Send a window size to trigger first render
	tm.Send(tea.WindowSizeMsg{Width: 100, Height: 30})

	// Wait for loading screen
	want := []byte("Loading data...")
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, want) },
		teatest.WithDuration(2*time.Second),
	)

	// Quit
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}

func TestTUI_SystemMetrics_ToggleAndRender_Teatest(t *testing.T) {
	// Setup config with 2x2 system grid visible by default
	cfg := leet.GetConfig()
	cfg.SetPathForTests(filepath.Join(t.TempDir(), "config.json"))
	if err := cfg.Load(); err != nil {
		t.Fatalf("Load: %v", err)
	}
	_ = cfg.SetSystemRows(2)
	_ = cfg.SetSystemCols(2)
	_ = cfg.SetRightSidebarVisible(true)

	// Create a valid wandb file
	tmp, err := os.CreateTemp(t.TempDir(), "test-*.wandb")
	if err != nil {
		t.Fatalf("CreateTemp: %v", err)
	}
	tmpPath := tmp.Name()

	// Use leveldb Writer to write records
	writer := leveldb.NewWriterExt(tmp, leveldb.CRCAlgoIEEE, 0)

	// Helper to write a protobuf record
	writeRecord := func(record *spb.Record) error {
		data, err := proto.Marshal(record)
		if err != nil {
			return err
		}
		w, err := writer.Next()
		if err != nil {
			return err
		}
		_, err = w.Write(data)
		return err
	}

	// Write run record
	runRecord := &spb.Record{
		RecordType: &spb.Record_Run{
			Run: &spb.RunRecord{
				RunId:       "test-run",
				DisplayName: "Test Run",
				Project:     "test-project",
			},
		},
	}
	if err := writeRecord(runRecord); err != nil {
		t.Fatalf("write run record: %v", err)
	}

	// Write initial history record
	histRecord := &spb.Record{
		RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Item: []*spb.HistoryItem{
					{NestedKey: []string{"_step"}, ValueJson: "1"},
					{NestedKey: []string{"loss"}, ValueJson: "1.0"},
				},
			},
		},
	}
	if err := writeRecord(histRecord); err != nil {
		t.Fatalf("write history record: %v", err)
	}

	// Write initial stats with GPU metrics
	ts := time.Now().Unix()
	statsRecord := &spb.Record{
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
	}
	if err := writeRecord(statsRecord); err != nil {
		t.Fatalf("write stats record: %v", err)
	}

	// Flush to ensure data is written
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush writer: %v", err)
	}

	// Keep file open to simulate live writing
	// Don't close tmp yet

	// Create model and test terminal
	logger := observability.NewNoOpLogger()
	m := leet.NewModel(tmpPath, logger)
	tm := teatest.NewTestModel(t, m, teatest.WithInitialTermSize(240, 80))

	// Set window size
	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Wait for the metrics grid to appear (loss chart should be visible)
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return containsTTY(b, "loss")
		},
		teatest.WithDuration(3*time.Second),
	)

	tm.Send(tea.WindowSizeMsg{Width: 241, Height: 80})

	// Wait for System Metrics header (should already be visible due to config)
	// t.Log(m.View())
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return containsTTY(b, "System Metrics")
		},
		teatest.WithDuration(3*time.Second),
	)

	// Write more stats
	statsRecord2 := &spb.Record{
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
	}
	if err := writeRecord(statsRecord2); err != nil {
		t.Fatalf("write second stats record: %v", err)
	}
	if err := writer.Flush(); err != nil {
		t.Fatalf("flush writer: %v", err)
	}

	// Trigger file change notification
	tm.Send(leet.FileChangedMsg{})
	time.Sleep(300 * time.Millisecond)

	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})

	// Check for GPU Temp chart with 2 series (should show [2])
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			hasGPUTemp := containsTTY(b, "GPU Temp")
			hasSeriesCount := containsTTY(b, "[2]")
			hasCPUCore := containsTTY(b, "CPU Core")

			if !hasGPUTemp || !hasSeriesCount || !hasCPUCore {
				output := string(b)
				if strings.Contains(output, "GPU Temp") && !strings.Contains(output, "[2]") {
					t.Log("GPU Temp found but no [2] - checking for series count rendering")
					// Look for any bracket numbers
					for i := 1; i <= 5; i++ {
						marker := fmt.Sprintf("[%d]", i)
						if strings.Contains(output, marker) {
							t.Logf("Found series marker: %s", marker)
						}
					}
				}
			}

			return hasGPUTemp && hasSeriesCount && hasCPUCore
		},
		teatest.WithDuration(3*time.Second),
	)

	// Add third GPU
	statsRecord3 := &spb.Record{
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
	}
	if err := writeRecord(statsRecord3); err != nil {
		t.Fatalf("write third stats record: %v", err)
	}

	// Write exit record to signal completion
	exitRecord := &spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{
				ExitCode: 0,
			},
		},
	}
	if err := writeRecord(exitRecord); err != nil {
		t.Fatalf("write exit record: %v", err)
	}

	// Close the writer and file
	if err := writer.Close(); err != nil {
		t.Fatalf("close writer: %v", err)
	}
	tmp.Close()

	// Trigger file change
	tm.Send(leet.FileChangedMsg{})
	time.Sleep(300 * time.Millisecond)

	// Wait for [3] to appear
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool {
			return containsTTY(b, "[3]")
		},
		teatest.WithDuration(3*time.Second),
	)

	// Toggle help
	tm.Type("h")
	tm.Send(tea.WindowSizeMsg{Width: 240, Height: 80})
	want := []byte("LEET")
	teatest.WaitFor(t, tm.Output(),
		func(b []byte) bool { return bytes.Contains(b, want) },
		teatest.WithDuration(3*time.Second),
	)
	tm.Type("h")

	// Quit
	tm.Type("q")
	tm.WaitFinished(t, teatest.WithFinalTimeout(2*time.Second))
}
