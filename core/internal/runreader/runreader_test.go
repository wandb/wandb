package runreader_test

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func writeLog(t *testing.T, path string, records ...*spb.Record) {
	t.Helper()
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	for _, r := range records {
		require.NoError(t, w.Write(r))
	}
	require.NoError(t, w.Close())
}

func runRecord(id string, config map[string]string) *spb.Record {
	run := &spb.RunRecord{
		RunId: id, Project: "proj", Entity: "ent", DisplayName: "my-run",
		Tags: []string{"a", "b"}, Config: &spb.ConfigRecord{},
	}
	for k, v := range config {
		run.Config.Update = append(run.Config.Update, &spb.ConfigItem{Key: k, ValueJson: v})
	}
	return &spb.Record{RecordType: &spb.Record_Run{Run: run}}
}

func historyRecord(step int64, items map[string]string) *spb.Record {
	h := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: step}}
	for k, v := range items {
		h.Item = append(h.Item, &spb.HistoryItem{Key: k, ValueJson: v})
	}
	return &spb.Record{RecordType: &spb.Record_History{History: h}}
}

func summaryRecord(items map[string]string) *spb.Record {
	s := &spb.SummaryRecord{}
	for k, v := range items {
		s.Update = append(s.Update, &spb.SummaryItem{Key: k, ValueJson: v})
	}
	return &spb.Record{RecordType: &spb.Record_Summary{Summary: s}}
}

func outputRecord(line string, stderr bool, at time.Time) *spb.Record {
	kind := spb.OutputRawRecord_STDOUT
	if stderr {
		kind = spb.OutputRawRecord_STDERR
	}
	return &spb.Record{RecordType: &spb.Record_OutputRaw{OutputRaw: &spb.OutputRawRecord{
		OutputType: kind, Line: line, Timestamp: timestamppb.New(at),
	}}}
}

func exitRecord(code int32) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: code}}}
}

func TestRun_FoldsRecords(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	t0 := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	writeLog(t, path,
		runRecord("abc", map[string]string{"lr": "0.1"}),
		&spb.Record{RecordType: &spb.Record_Config{Config: &spb.ConfigRecord{
			Update: []*spb.ConfigItem{{Key: "batch", ValueJson: "32"}}}}},
		historyRecord(0, map[string]string{"loss": "1.0"}),
		historyRecord(1, map[string]string{"loss": "0.5", "acc": "0.9"}),
		summaryRecord(map[string]string{"loss": "0.5"}),
		outputRecord("epoch 1\n", false, t0),
		outputRecord("careful\n", true, t0.Add(time.Second)),
		exitRecord(0),
	)

	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))

	info := run.Info()
	assert.Equal(t, "abc", info.RunID)
	assert.Equal(t, "my-run", info.DisplayName)
	assert.Equal(t, []string{"a", "b"}, info.Tags)

	var config, summary map[string]any
	configJSON, err := run.ConfigJSON()
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(configJSON, &config))
	assert.Equal(t, map[string]any{"lr": 0.1, "batch": 32.0}, config)
	summaryJSON, err := run.SummaryJSON()
	require.NoError(t, err)
	require.NoError(t, json.Unmarshal(summaryJSON, &summary))
	assert.Equal(t, map[string]any{"loss": 0.5}, summary)

	assert.Equal(t, int64(1), run.LastStep())
	assert.Equal(t, []string{"acc", "loss"}, run.HistoryKeys())
	assert.Equal(t, []runreader.ConsoleLine{
		{Time: t0, Content: "epoch 1"},
		{Time: t0.Add(time.Second), Stderr: true, Content: "careful"},
	}, run.Console())
	assert.Equal(t, runreader.StateFinished, run.State())
}

func TestRun_StateWithoutExit(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	writeLog(t, path, runRecord("abc", nil), historyRecord(3, map[string]string{"loss": "1"}))

	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))
	assert.Equal(t, runreader.StateRunning, run.State())

	old := time.Now().Add(-time.Hour)
	require.NoError(t, os.Chtimes(path, old, old))
	assert.Equal(t, runreader.StateCrashed, run.State())
}

func TestRun_UpdateFollowsAppends(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.Write(runRecord("abc", nil)))
	require.NoError(t, w.Flush())

	ctx := context.Background()
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(ctx))
	assert.Equal(t, "abc", run.Info().RunID)
	assert.Equal(t, int64(-1), run.LastStep())

	require.NoError(t, w.Write(historyRecord(5, map[string]string{"loss": "1"})))
	require.NoError(t, w.Flush())
	// A torn last record reads as EOF until it is complete.
	full, err := os.ReadFile(path)
	require.NoError(t, err)
	require.NoError(t, os.Truncate(path, int64(len(full)-1)))
	require.NoError(t, run.Update(ctx))
	assert.Equal(t, int64(-1), run.LastStep())
	require.NoError(t, os.WriteFile(path, full, 0o644))
	require.NoError(t, run.Update(ctx))
	assert.Equal(t, int64(5), run.LastStep())

	require.NoError(t, w.Write(exitRecord(1)))
	require.NoError(t, w.Close())
	require.NoError(t, run.Update(ctx))
	assert.Equal(t, runreader.StateFailed, run.State())
}

func TestRun_UnreadableFileIsAnError(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	require.NoError(t, os.WriteFile(path, []byte("this is not a transaction log at all\n"), 0o644))
	logger := observability.NewNoOpLogger()

	done := make(chan error, 3)
	go func() {
		run, err := runreader.Open(path, logger)
		if err == nil {
			err = run.Update(context.Background())
			run.Close()
		}
		done <- err
		_, err = runreader.Probe(path, logger)
		done <- err
		_, err = runreader.ScanHistory(context.Background(), path, runreader.HistoryQuery{}, logger)
		done <- err
	}()
	for range 3 {
		select {
		case err := <-done:
			assert.Error(t, err)
		case <-time.After(5 * time.Second):
			t.Fatal("reading an unreadable file did not return")
		}
	}
}

func TestScanHistory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	var records []*spb.Record
	for step := range int64(5) {
		records = append(records, historyRecord(step, map[string]string{"loss": "1", "acc": "2"}))
	}
	writeLog(t, path, append([]*spb.Record{runRecord("abc", nil)}, records...)...)
	logger := observability.NewNoOpLogger()

	rows, err := runreader.ScanHistory(context.Background(), path,
		runreader.HistoryQuery{Keys: []string{"loss"}, Last: 2}, logger)
	require.NoError(t, err)
	assert.Equal(t, []runreader.HistoryRow{
		{Step: 3, Items: []runreader.HistoryItem{{Key: "loss", ValueJSON: "1"}}},
		{Step: 4, Items: []runreader.HistoryItem{{Key: "loss", ValueJSON: "1"}}},
	}, rows)

	minStep, maxStep := int64(1), int64(2)
	rows, err = runreader.ScanHistory(context.Background(), path,
		runreader.HistoryQuery{MinStep: &minStep, MaxStep: &maxStep}, logger)
	require.NoError(t, err)
	require.Len(t, rows, 2)
	assert.Equal(t, int64(1), rows[0].Step)
	assert.Len(t, rows[0].Items, 2)
}

func TestProbe(t *testing.T) {
	dir := t.TempDir()
	logger := observability.NewNoOpLogger()

	renamed := runRecord("s", nil)
	renamed.GetRun().DisplayName = "renamed"
	small := filepath.Join(dir, "small.wandb")
	writeLog(t, small, runRecord("s", nil), renamed, exitRecord(1))
	result, err := runreader.Probe(small, logger)
	require.NoError(t, err)
	assert.Equal(t, "s", result.Info.RunID)
	assert.Equal(t, "renamed", result.Info.DisplayName)
	assert.Equal(t, runreader.StateFailed, result.State)

	// Enough history to span many 32 KiB blocks, so the exit record is
	// found from the tail rather than by reading everything.
	big := []*spb.Record{runRecord("b", nil)}
	for step := range int64(100) {
		big = append(big, historyRecord(step, map[string]string{"text": strings.Repeat("x", 8000)}))
	}
	late := runRecord("b", nil)
	late.GetRun().DisplayName = "late"
	finished := filepath.Join(dir, "finished.wandb")
	writeLog(t, finished, append(big, late, exitRecord(0))...)
	result, err = runreader.Probe(finished, logger)
	require.NoError(t, err)
	assert.Equal(t, "b", result.Info.RunID)
	assert.Equal(t, "late", result.Info.DisplayName)
	assert.Equal(t, runreader.StateFinished, result.State)

	running := filepath.Join(dir, "running.wandb")
	writeLog(t, running, big...)
	result, err = runreader.Probe(running, logger)
	require.NoError(t, err)
	assert.Equal(t, runreader.StateRunning, result.State)

	// The exit record is not in the last block when records follow it.
	trailing := filepath.Join(dir, "trailing.wandb")
	writeLog(t, trailing, append(big, exitRecord(0),
		summaryRecord(map[string]string{"text": `"` + strings.Repeat("y", 40000) + `"`}))...)
	result, err = runreader.Probe(trailing, logger)
	require.NoError(t, err)
	assert.Equal(t, runreader.StateFinished, result.State)
}

func TestListRunDirs(t *testing.T) {
	dir := t.TempDir()
	// Directory names carry a start time, and a "-N" suffix when the name
	// was already taken; the transaction log is always run-<run_id>.wandb.
	for runDir, file := range map[string]string{
		"run-20250101_000001-aaa":         "run-aaa.wandb",
		"offline-run-20250102_000000-bbb": "run-bbb.wandb",
		"run-20250103_000000-aaa-1":       "run-aaa.wandb",
		"run-20250104_000000-nolog":       "",
		"junk":                            "run-junk.wandb",
	} {
		require.NoError(t, os.Mkdir(filepath.Join(dir, runDir), 0o755))
		if file != "" {
			require.NoError(t, os.WriteFile(filepath.Join(dir, runDir, file), nil, 0o644))
		}
	}

	dirs, err := runreader.ListRunDirs(dir)
	require.NoError(t, err)
	require.Len(t, dirs, 3)
	assert.Equal(t, "aaa", dirs[0].RunID)
	assert.Equal(t,
		filepath.Join(dir, "run-20250103_000000-aaa-1", "run-aaa.wandb"), dirs[0].WandbFile)
	assert.Equal(t, "bbb", dirs[1].RunID)
	assert.True(t, dirs[1].Offline)
	assert.Equal(t, "aaa", dirs[2].RunID)
	assert.False(t, dirs[2].Offline)
	assert.Equal(t, dirs[2], runreader.ParseRunDir(dirs[2].WandbFile))
}
