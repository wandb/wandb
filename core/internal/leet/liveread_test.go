package leet_test

import (
	"errors"
	"path/filepath"
	"testing"
	"testing/synctest"
	"time"

	tea "charm.land/bubbletea/v2"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runmetric"
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
		RunFile: "dummy",
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
		RunFile: "dummy",
	}, cfg, logger)

	src := &stubHistorySource{msg: leet.ChunkedBatchMsg{}}
	require.Nil(t, r.ReadLiveBatchCmd(src)())
}

func TestWorkspace_ReadAvailableCmd_WrapsChunkedBatch(t *testing.T) {
	logger := observability.NewNoOpLogger()
	cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

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
	w := leet.NewWorkspace(t.TempDir(), cfg, logger)

	run := &leet.WorkspaceRun{Key: "run-1", Reader: &stubHistorySource{msg: leet.ChunkedBatchMsg{}}}
	require.Nil(t, w.ReadAvailableCmd(run)())
}

func TestRun_ReadErrorDrawsPendingHistory(t *testing.T) {
	// Keep both boot chunks inside the redraw interval.
	synctest.Test(t, func(t *testing.T) {
		r, _ := newTestRun(t, 160, 50, nil)
		defer r.Cleanup()
		r.Update(leet.ChunkedBatchMsg{HasMore: true, Msgs: []tea.Msg{
			leet.RunMsg{ID: "run-1"},
			leet.HistoryMsg{Metrics: map[string]leet.MetricData{
				"loss": {X: []float64{0, 1}, Y: []float64{0, 1}},
			}},
		}})
		r.Update(leet.ChunkedBatchMsg{HasMore: true, Msgs: []tea.Msg{
			leet.HistoryMsg{Metrics: map[string]leet.MetricData{
				"loss": {X: []float64{2, 3}, Y: []float64{5, 10}},
			}},
		}})

		r.Update(leet.ErrorMsg{Err: errors.New("truncated transaction log")})
		view := r.View().Content
		require.Contains(t, stripANSI(view), "loss")
		require.Contains(t, stripANSI(view), "Error: truncated transaction log")

		// Forcing a redraw must not reveal history omitted by the error handler.
		r.Update(tea.WindowSizeMsg{Width: 160, Height: 50})
		require.Equal(t, r.View().Content, view)
	})
}

func TestWorkspace_ReadErrorDrawsPendingHistory(t *testing.T) {
	// Keep both boot chunks inside the redraw interval.
	synctest.Test(t, func(t *testing.T) {
		logger := observability.NewNoOpLogger()
		cfg := leet.NewConfigManager(filepath.Join(t.TempDir(), "config.json"), logger)
		w := leet.NewWorkspace(t.TempDir(), cfg, logger)
		defer w.Cleanup()
		w.Update(tea.WindowSizeMsg{Width: 160, Height: 50})
		w.TestAttachRun(&leet.WorkspaceRun{Key: "run-1"}, true)
		w.Update(leet.WorkspaceChunkedBatchMsg{RunKey: "run-1", Batch: leet.ChunkedBatchMsg{
			HasMore: true,
			Msgs: []tea.Msg{leet.HistoryMsg{Metrics: map[string]leet.MetricData{
				"loss": {X: []float64{0, 1}, Y: []float64{0, 1}},
			}}},
		}})
		w.Update(leet.WorkspaceChunkedBatchMsg{RunKey: "run-1", Batch: leet.ChunkedBatchMsg{
			HasMore: true,
			Msgs: []tea.Msg{leet.HistoryMsg{Metrics: map[string]leet.MetricData{
				"loss": {X: []float64{2, 3}, Y: []float64{5, 10}},
			}}},
		}})

		w.Update(
			leet.WorkspaceRunReadErrMsg{
				RunKey: "run-1",
				Err:    errors.New("truncated transaction log"),
			},
		)
		view := w.View().Content
		require.Contains(t, stripANSI(view), "loss")

		// Forcing a redraw must not reveal history omitted by the error handler.
		w.Update(tea.WindowSizeMsg{Width: 160, Height: 50})
		require.Equal(t, w.View().Content, view)
	})
}

func TestParseHistory_UsesHistoryStepFallback(t *testing.T) {
	msg := leet.ParseHistory("dummy", &spb.HistoryRecord{
		Step: &spb.HistoryStep{Num: 7},
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.5"},
		},
	}, runmetric.New()).(leet.HistoryMsg)

	require.Equal(t, 7.0, msg.Metrics["loss"].X[0])
}
