package leet_test

import (
	"path/filepath"
	"testing"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type stubHistorySource struct {
	msg tea.Msg
	err error

	chunkSize int
	maxTime   time.Duration
}

func (s *stubHistorySource) Read(chunkSize int, maxTime time.Duration) (tea.Msg, error) {
	s.chunkSize = chunkSize
	s.maxTime = maxTime
	return s.msg, s.err
}

func (s *stubHistorySource) Close() {}

func TestReadRecords_PassesThroughArguments(t *testing.T) {
	src := &stubHistorySource{msg: leet.ChunkedBatchMsg{}}

	_ = leet.ReadRecords(src, 17, 23*time.Millisecond)()

	require.Equal(t, 17, src.chunkSize)
	require.Equal(t, 23*time.Millisecond, src.maxTime)
}

func TestRun_ReadLiveBatchCmd_WrapsChunkedBatchAndUsesLiveLimits(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	r := leet.NewRun(&leet.RunParams{
		LocalRunParams: &leet.LocalRunParams{
			RunFile: "dummy",
		},
	}, cfg, logger)

	src := &stubHistorySource{
		msg: leet.ChunkedBatchMsg{
			Msgs: []tea.Msg{
				leet.HistoryMsg{
					RunPath: "dummy",
					Metrics: map[string]leet.MetricData{
						"loss": {X: []float64{1}, Y: []float64{0.5}},
					},
				},
			},
		},
	}

	msg := r.ReadLiveBatchCmd(src)()
	batch, ok := msg.(leet.BatchedRecordsMsg)
	require.True(t, ok)
	require.Len(t, batch.Msgs, 1)
	require.Equal(t, leet.LiveMonitorChunkSize, src.chunkSize)
	require.Equal(t, leet.LiveMonitorMaxTime, src.maxTime)
}

func TestRun_ReadLiveBatchCmd_DropsEmptyChunk(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	r := leet.NewRun(&leet.RunParams{
		LocalRunParams: &leet.LocalRunParams{
			RunFile: "dummy",
		},
	}, cfg, logger)

	src := &stubHistorySource{msg: leet.ChunkedBatchMsg{}}
	require.Nil(t, r.ReadLiveBatchCmd(src)())
}

func TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(leet.NewLocalWorkspaceBackend(t.TempDir(), logger), cfg, logger)

	src := &stubHistorySource{
		msg: leet.ChunkedBatchMsg{
			Msgs: []tea.Msg{
				leet.HistoryMsg{
					RunPath: "dummy",
					Metrics: map[string]leet.MetricData{
						"loss": {X: []float64{1}, Y: []float64{0.5}},
					},
				},
			},
		},
	}
	run := &leet.WorkspaceRun{Key: "run-1", Reader: src}

	msg := w.ReadAvailableCmd(run)()
	wrapped, ok := msg.(leet.WorkspaceBatchedRecordsMsg)
	require.True(t, ok)
	require.Equal(t, "run-1", wrapped.RunKey)
	require.Len(t, wrapped.Batch.Msgs, 1)
	require.Equal(t, leet.LiveMonitorChunkSize, src.chunkSize)
	require.Equal(t, leet.LiveMonitorMaxTime, src.maxTime)
}

func TestWorkspace_ReadAvailableCmd_DropsEmptyChunk(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(leet.NewLocalWorkspaceBackend(t.TempDir(), logger), cfg, logger)

	run := &leet.WorkspaceRun{Key: "run-1", Reader: &stubHistorySource{msg: leet.ChunkedBatchMsg{}}}
	require.Nil(t, w.ReadAvailableCmd(run)())
}

func TestParseHistory_UsesHistoryStepFallback(t *testing.T) {
	msg := leet.ParseHistory("dummy", &spb.HistoryRecord{
		Step: &spb.HistoryStep{Num: 7},
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.5"},
		},
	}).(leet.HistoryMsg)

	require.Equal(t, 7.0, msg.Metrics["loss"].X[0])
}
