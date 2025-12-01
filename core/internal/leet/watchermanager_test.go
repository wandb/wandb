package leet_test

import (
	"fmt"
	"path/filepath"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/leet"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestWatcherManager_FileChangeDetection(t *testing.T) {
	logger := observability.NewNoOpLogger()
	watcherChan := make(chan tea.Msg, 10)
	wm := leet.NewWatcherManager(watcherChan, logger)
	require.False(t, wm.IsStarted())

	path := filepath.Join(t.TempDir(), "test.wandb")
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)

	err = wm.Start(path)
	require.NoError(t, err)
	require.True(t, wm.IsStarted())

	for i := range 3 {
		require.NoError(t, w.Write(&spb.Record{
			RecordType: &spb.Record_History{
				History: &spb.HistoryRecord{
					Item: []*spb.HistoryItem{
						{NestedKey: []string{"_step"}, ValueJson: fmt.Sprintf("%d", i)},
					},
				},
			},
		}))
		time.Sleep(10 * time.Millisecond)
		require.NoError(t, w.Flush())
	}
	require.NoError(t, w.Close())

	msg := wm.WaitForMsg()
	_, ok := msg.(leet.FileChangedMsg)
	require.True(t, ok, "expected FileChangedMsg, got %T", msg)

	wm.Finish()
	require.False(t, wm.IsStarted())
}
