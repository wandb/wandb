package wbapi

import (
	"context"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writeLocalRun writes a finished run into a wandb directory and returns
// the path of its transaction log.
func writeLocalRun(t *testing.T, wandbDir string) string {
	t.Helper()
	runDir := filepath.Join(wandbDir, "run-20260101_120000-abc")
	require.NoError(t, os.MkdirAll(runDir, 0o755))
	path := filepath.Join(runDir, "run-abc.wandb")

	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	at := time.Date(2026, 1, 1, 12, 0, 0, 0, time.UTC)
	records := []*spb.Record{
		{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
			RunId: "abc", Project: "proj", DisplayName: "first",
			Config: &spb.ConfigRecord{Update: []*spb.ConfigItem{{Key: "lr", ValueJson: "0.1"}}},
		}}},
		{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: 0},
			Item: []*spb.HistoryItem{
				{Key: "loss", ValueJson: "1.0"}, {Key: "acc", ValueJson: "0.5"}},
		}}},
		{RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Step: &spb.HistoryStep{Num: 1},
			Item: []*spb.HistoryItem{{Key: "loss", ValueJson: "0.5"}},
		}}},
		{RecordType: &spb.Record_Summary{Summary: &spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "loss", ValueJson: "0.5"}},
		}}},
		{RecordType: &spb.Record_OutputRaw{OutputRaw: &spb.OutputRawRecord{
			OutputType: spb.OutputRawRecord_STDOUT,
			Line:       "one\ntwo\n",
			Timestamp:  timestamppb.New(at),
		}}},
		{RecordType: &spb.Record_OutputRaw{OutputRaw: &spb.OutputRawRecord{
			OutputType: spb.OutputRawRecord_STDERR,
			Line:       "bad\n",
			Timestamp:  timestamppb.New(at),
		}}},
		{RecordType: &spb.Record_Exit{Exit: &spb.RunExitRecord{ExitCode: 0}}},
	}
	for _, r := range records {
		require.NoError(t, w.Write(r))
	}
	require.NoError(t, w.Close())
	return path
}

func TestLocalRunHandler(t *testing.T) {
	wandbDir := t.TempDir()
	path := writeLocalRun(t, wandbDir)
	// A run that has not written its record yet: only the file header exists.
	headerOnly := filepath.Join(wandbDir, "offline-run-20250101_000000-hdr")
	require.NoError(t, os.MkdirAll(headerOnly, 0o755))
	w, err := transactionlog.OpenWriter(filepath.Join(headerOnly, "run-hdr.wandb"))
	require.NoError(t, err)
	require.NoError(t, w.Close())

	h := NewLocalRunHandler(observability.NewNoOpLogger())
	defer h.Close()
	ctx := context.Background()

	list := h.HandleListLocalRuns(ctx, &spb.ListLocalRunsRequest{WandbDir: wandbDir}).
		GetListLocalRunsResponse()
	require.Len(t, list.GetRuns(), 2)
	assert.Equal(t, "abc", list.Runs[0].GetRunId())
	assert.Equal(t, path, list.Runs[0].GetWandbFile())
	assert.Equal(t, "finished", list.Runs[0].GetState())
	assert.Equal(t, "hdr", list.Runs[1].GetRunId())
	assert.True(t, list.Runs[1].GetOffline())
	assert.Equal(t, "pending", list.Runs[1].GetState())

	run := h.HandleReadLocalRun(ctx, &spb.ReadLocalRunRequest{WandbFile: path}).
		GetReadLocalRunResponse()
	require.NotNil(t, run)
	assert.Equal(t, "first", run.GetInfo().GetDisplayName())
	assert.JSONEq(t, `{"lr": 0.1}`, run.GetConfigJson())
	assert.JSONEq(t, `{"loss": 0.5}`, run.GetSummaryJson())
	assert.Equal(t, int64(1), run.GetLastStep())
	assert.Equal(t, []string{"acc", "loss"}, run.GetHistoryKeys())
	require.NotNil(t, run.ExitCode)
	assert.Equal(t, int32(0), run.GetExitCode())

	last := int32(1)
	history := h.HandleReadLocalRunHistory(ctx, &spb.ReadLocalRunHistoryRequest{
		WandbFile: path, Keys: []string{"loss"}, Last: &last,
	}).GetReadLocalRunHistoryResponse()
	require.Len(t, history.GetRows(), 1)
	assert.Equal(t, int64(1), history.Rows[0].GetStep())
	assert.Equal(t, "loss", history.Rows[0].Items[0].GetKey())
	assert.Equal(t, "0.5", history.Rows[0].Items[0].GetValueJson())

	tail := h.HandleReadLocalRunConsoleLogs(ctx, &spb.ReadLocalRunConsoleLogsRequest{
		WandbFile: path, Last: &last,
	}).GetReadLocalRunConsoleLogsResponse()
	assert.Equal(t, int64(3), tail.GetTotalLines())
	require.Len(t, tail.GetLines(), 1)
	assert.Equal(t, int64(2), tail.Lines[0].GetNumber())
	assert.Equal(t, "bad", tail.Lines[0].GetContent())
	assert.Equal(t, "error", tail.Lines[0].GetLevel())
	assert.Equal(t, "2026-01-01T12:00:00Z", tail.Lines[0].GetTimestamp())

	all := h.HandleReadLocalRunConsoleLogs(ctx, &spb.ReadLocalRunConsoleLogsRequest{
		WandbFile: path,
	}).GetReadLocalRunConsoleLogsResponse()
	require.Len(t, all.GetLines(), 3)
	assert.Equal(t, "two", all.Lines[1].GetContent())

	missing := h.HandleReadLocalRun(ctx, &spb.ReadLocalRunRequest{
		WandbFile: filepath.Join(wandbDir, "nope.wandb"),
	})
	assert.NotNil(t, missing.GetApiErrorResponse())

	// A cached run whose directory is deleted is reported as missing.
	require.NoError(t, os.RemoveAll(filepath.Dir(path)))
	deleted := h.HandleReadLocalRun(ctx, &spb.ReadLocalRunRequest{WandbFile: path})
	assert.NotNil(t, deleted.GetApiErrorResponse())
}
