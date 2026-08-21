package leet

// Measurement harness for LEET perf work. Generates synthetic .wandb
// transaction logs and drives the real ingest/render pipeline.
//
// Run the report (wall time, retained heap):
//
//	LEET_PERF=1 go test -run TestPerfReport -v ./core/internal/leet/
//
// Run the benchmarks:
//
//	go test -bench BenchmarkLeet -benchmem -run ^$ ./core/internal/leet/

import (
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type synthSpec struct {
	numMetrics   int
	numSteps     int
	statsEvery   int // emit a stats record every N steps (0 = never)
	numSysProbes int // system metrics per stats record
	logsEvery    int // emit an output_raw record every N steps (0 = never)
	withExit     bool
}

// writeSyntheticRun writes a realistic .wandb transaction log.
func writeSyntheticRun(tb testing.TB, path string, spec synthSpec) {
	tb.Helper()

	w, err := transactionlog.OpenWriter(path)
	if err != nil {
		tb.Fatalf("open writer: %v", err)
	}
	defer func() { _ = w.Close() }()

	write := func(rec *spb.Record) {
		if err := w.Write(rec); err != nil {
			tb.Fatalf("write record: %v", err)
		}
	}

	write(&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
		RunId:       "perf-run",
		DisplayName: "perf-run",
		Project:     "leet-perf",
		Config: &spb.ConfigRecord{Update: []*spb.ConfigItem{
			{NestedKey: []string{"lr"}, ValueJson: "0.001"},
			{NestedKey: []string{"batch_size"}, ValueJson: "256"},
		}},
	}}})

	metricNames := make([]string, spec.numMetrics)
	for m := range metricNames {
		metricNames[m] = fmt.Sprintf("train/metric_%03d", m)
	}

	base := time.Now().Add(-time.Duration(spec.numSteps) * time.Second)
	for step := 0; step < spec.numSteps; step++ {
		items := make([]*spb.HistoryItem, 0, spec.numMetrics+1)
		items = append(items, &spb.HistoryItem{
			NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", step),
		})
		for m, name := range metricNames {
			v := float64(step%97)/97.0 + float64(m)
			items = append(items, &spb.HistoryItem{
				Key: name, ValueJson: fmt.Sprintf("%.6f", v),
			})
		}
		write(&spb.Record{RecordType: &spb.Record_History{
			History: &spb.HistoryRecord{
				Step: &spb.HistoryStep{Num: int64(step)},
				Item: items,
			},
		}})

		if spec.statsEvery > 0 && step%spec.statsEvery == 0 {
			statItems := make([]*spb.StatsItem, 0, spec.numSysProbes)
			for p := 0; p < spec.numSysProbes; p++ {
				statItems = append(statItems, &spb.StatsItem{
					Key:       fmt.Sprintf("gpu.%d.memoryAllocated", p),
					ValueJson: fmt.Sprintf("%.2f", float64((step+p)%100)),
				})
			}
			write(&spb.Record{RecordType: &spb.Record_Stats{
				Stats: &spb.StatsRecord{
					Timestamp: timestamppb.New(base.Add(time.Duration(step) * time.Second)),
					Item:      statItems,
				},
			}})
		}

		if spec.logsEvery > 0 && step%spec.logsEvery == 0 {
			write(&spb.Record{RecordType: &spb.Record_OutputRaw{
				OutputRaw: &spb.OutputRawRecord{
					Line:      fmt.Sprintf("epoch %d: loss improved to %.4f\n", step, 1.0/float64(step+1)),
					Timestamp: timestamppb.New(base.Add(time.Duration(step) * time.Second)),
				},
			}})
		}
	}

	if spec.withExit {
		write(&spb.Record{RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{ExitCode: 0},
		}})
	}
}

func newPerfRun(tb testing.TB, runFile string) *Run {
	tb.Helper()
	logger := observability.NewNoOpLogger()
	cfg := NewConfigManager(filepath.Join(tb.TempDir(), "leet-config.json"), logger)
	r := NewRun(&RunParams{RunFile: runFile}, cfg, logger)
	r.Update(tea.WindowSizeMsg{Width: 220, Height: 60})
	return r
}

// bootLoad drives the production boot-load loop synchronously.
func bootLoad(tb testing.TB, r *Run, path string) (records int) {
	tb.Helper()
	src, err := NewLevelDBHistorySource(path, observability.NewNoOpLogger())
	if err != nil {
		tb.Fatalf("new source: %v", err)
	}
	tb.Cleanup(src.Close)
	r.historySource = src

	for {
		msg, err := src.Read(BootLoadChunkSize, BootLoadMaxTime)
		batch, ok := msg.(ChunkedBatchMsg)
		if !ok {
			tb.Fatalf("unexpected msg type %T (err=%v)", msg, err)
		}
		records += batch.Progress
		r.handleChunkedBatch(batch)
		if !batch.HasMore {
			return records
		}
	}
}

func retainedHeap() uint64 {
	runtime.GC()
	runtime.GC()
	var ms runtime.MemStats
	runtime.ReadMemStats(&ms)
	return ms.HeapAlloc
}

// TestPerfReport prints wall time and retained heap for a large realistic run.
// Gated behind LEET_PERF=1 so it doesn't slow down normal test runs.
func TestPerfReport(t *testing.T) {
	if os.Getenv("LEET_PERF") == "" {
		t.Skip("set LEET_PERF=1 to run")
	}

	specs := []struct {
		name string
		spec synthSpec
	}{
		{"20metrics_x_50k_steps", synthSpec{
			numMetrics: 20, numSteps: 50_000,
			statsEvery: 15, numSysProbes: 24, logsEvery: 50, withExit: true}},
		{"200metrics_x_2k_steps", synthSpec{
			numMetrics: 200, numSteps: 2_000,
			statsEvery: 15, numSysProbes: 24, logsEvery: 50, withExit: true}},
	}

	for _, s := range specs {
		t.Run(s.name, func(t *testing.T) {
			path := filepath.Join(t.TempDir(), "perf.wandb")
			writeSyntheticRun(t, path, s.spec)
			fi, _ := os.Stat(path)

			before := retainedHeap()
			r := newPerfRun(t, path)
			start := time.Now()
			records := bootLoad(t, r, path)
			loadTime := time.Since(start)

			start = time.Now()
			const frames = 20
			for range frames {
				_ = r.View()
			}
			renderTime := time.Since(start) / frames

			after := retainedHeap()
			t.Logf("file=%.1fMB records=%d load=%v render/frame=%v retained=%.1fMB",
				float64(fi.Size())/1e6, records, loadTime, renderTime,
				float64(after-before)/1e6)
			runtime.KeepAlive(r)
		})
	}
}

// BenchmarkLeetBootLoad measures the full ingest pipeline (read + parse +
// chart building + per-chunk redraws).
func BenchmarkLeetBootLoad(b *testing.B) {
	path := filepath.Join(b.TempDir(), "boot.wandb")
	writeSyntheticRun(b, path, synthSpec{
		numMetrics: 20, numSteps: 5_000,
		statsEvery: 15, numSysProbes: 24, logsEvery: 50, withExit: true,
	})

	b.ReportAllocs()
	for b.Loop() {
		r := newPerfRun(b, path)
		bootLoad(b, r, path)
	}
}

// BenchmarkLeetLiveBatch measures the incremental live-update path: one new
// point per metric arrives, then the visible page is redrawn.
func BenchmarkLeetLiveBatch(b *testing.B) {
	for _, points := range []int{1_000, 100_000} {
		b.Run(fmt.Sprintf("%dpts", points), func(b *testing.B) {
			path := filepath.Join(b.TempDir(), "live.wandb")
			writeSyntheticRun(b, path, synthSpec{
				numMetrics: 20, numSteps: points, withExit: false,
			})
			r := newPerfRun(b, path)
			bootLoad(b, r, path)

			step := points
			b.ReportAllocs()
			b.ResetTimer()
			for b.Loop() {
				metrics := make(map[string]MetricData, 20)
				x := []float64{float64(step)}
				for m := 0; m < 20; m++ {
					metrics[fmt.Sprintf("train/metric_%03d", m)] = MetricData{
						X: x, Y: []float64{float64(step % 97)},
					}
				}
				r.handleRecordsBatch([]tea.Msg{HistoryMsg{
					RunPath: path, Metrics: metrics,
				}}, true)
				step++
			}
		})
	}
}

// BenchmarkLeetRenderFrame measures a full View() render of the run view.
func BenchmarkLeetRenderFrame(b *testing.B) {
	path := filepath.Join(b.TempDir(), "render.wandb")
	writeSyntheticRun(b, path, synthSpec{
		numMetrics: 20, numSteps: 10_000,
		statsEvery: 15, numSysProbes: 24, logsEvery: 50, withExit: true,
	})
	r := newPerfRun(b, path)
	bootLoad(b, r, path)

	b.ReportAllocs()
	b.ResetTimer()
	for b.Loop() {
		_ = r.View()
	}
}

// BenchmarkLeetWorkspaceIngest measures multi-run workspace ingestion.
func BenchmarkLeetWorkspaceIngest(b *testing.B) {
	logger := observability.NewNoOpLogger()

	dir := b.TempDir()
	path := filepath.Join(dir, "ws.wandb")
	writeSyntheticRun(b, path, synthSpec{
		numMetrics: 20, numSteps: 2_000, withExit: true,
	})

	b.ReportAllocs()
	for b.Loop() {
		cfg := NewConfigManager(filepath.Join(b.TempDir(), "cfg.json"), logger)
		w := NewWorkspace(dir, cfg, logger)
		w.handleWindowResize(220, 60)

		for i := 0; i < 4; i++ {
			key := fmt.Sprintf("run-20260818_10000%d-abc%d", i, i)
			src, err := NewLevelDBHistorySource(path, logger)
			if err != nil {
				b.Fatal(err)
			}
			run := &WorkspaceRun{Key: key, Reader: src, wandbPath: path}
			w.runsByKey[key] = run
			w.selectedRuns[key] = true
			for {
				msg, _ := src.Read(BootLoadChunkSize, BootLoadMaxTime)
				batch := msg.(ChunkedBatchMsg)
				w.handleWorkspaceChunkedBatch(WorkspaceChunkedBatchMsg{
					RunKey: key, Batch: batch,
				})
				if !batch.HasMore {
					break
				}
			}
			src.Close()
		}
	}
}
