package runreader_test

import (
	"context"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestHistory_DistinguishesLiteralAndNestedKeys(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-keys.wandb")
	writeLog(t, path, &spb.Record{RecordType: &spb.Record_History{
		History: &spb.HistoryRecord{Item: []*spb.HistoryItem{
			{NestedKey: []string{"a", "b"}, ValueJson: "1"},
			{NestedKey: []string{"a.b"}, ValueJson: "2"},
			{Key: `a\.b`, ValueJson: "3"},
		}},
	}})
	ctx := context.Background()
	logger := observability.NewNoOpLogger()
	run, err := runreader.Open(path, logger)
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(ctx))
	want := []runreader.HistoryItem{
		{Key: "a.b", ValueJSON: "1"},
		{Key: `a\.b`, ValueJSON: "2"},
		{Key: `a\\\.b`, ValueJSON: "3"},
	}
	assert.ElementsMatch(t, []string{want[0].Key, want[1].Key, want[2].Key}, run.HistoryKeys())
	rows, err := runreader.ScanHistory(ctx, path, runreader.HistoryQuery{}, logger)
	require.NoError(t, err)
	require.Len(t, rows, 1)
	assert.Equal(t, want, rows[0].Items)
	for _, item := range want {
		rows, err := runreader.ScanHistory(ctx, path,
			runreader.HistoryQuery{Keys: []string{item.Key}}, logger)
		require.NoError(t, err)
		require.Len(t, rows, 1)
		assert.Equal(t, []runreader.HistoryItem{item}, rows[0].Items)
	}
}
