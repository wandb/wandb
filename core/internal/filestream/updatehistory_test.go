package filestream

import (
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestream/metricsbatch"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
)

func TestHistoryUpdatePreparesTypedRow(t *testing.T) {
	rh := runhistory.New()
	rh.SetString(pathtree.PathOf("valid"), "original")
	rh.SetString(pathtree.PathOf("invalid"), "\xff")
	rh.SetString(pathtree.PathOf("_step"), "not-an-int")
	update := &HistoryUpdate{Row: rh, Cells: 3}

	var requests []*FileStreamRequest
	require.NoError(t, update.Apply(UpdateContext{
		MakeRequest: func(req *FileStreamRequest) {
			requests = append(requests, req)
		},
		Logger:       observability.NewNoOpLogger(),
		typedHistory: true,
	}))
	require.Len(t, requests, 1)
	require.Empty(t, requests[0].HistoryLines)
	require.Len(t, requests[0].typedHistoryRows, 1)
	rh.SetString(pathtree.PathOf("valid"), "changed")
	b := metricsbatch.NewBuilder()
	b.Append(requests[0].typedHistoryRows[0])
	batch := b.Finish()
	require.Equal(t, []string{"valid"}, batch.Keys)
	require.Equal(t, []string{"original"}, batch.Strings)
	require.Equal(t, []bool{false}, batch.HasSeq)
}
