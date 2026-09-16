package filestream_test

import (
	"strconv"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runencodestats"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// applyHistory runs a HistoryUpdate and returns the queued requests.
func applyHistory(
	t *testing.T,
	row *runhistory.RunHistory,
	s *settings.Settings,
	stats *runencodestats.Stats,
) []*FileStreamRequest {
	t.Helper()

	var requests []*FileStreamRequest
	err := (&HistoryUpdate{Row: row}).Apply(UpdateContext{
		MakeRequest: func(r *FileStreamRequest) {
			requests = append(requests, r)
		},
		Settings:    s,
		Logger:      observabilitytest.NewTestLogger(t),
		Printer:     observability.NewPrinter(0),
		EncodeStats: stats,
	})
	require.NoError(t, err)
	return requests
}

func historyRow(t *testing.T, items ...*spb.HistoryItem) *runhistory.RunHistory {
	t.Helper()
	row := runhistory.New()
	for _, item := range items {
		require.NoError(t, row.SetFromRecord(item))
	}
	return row
}

func TestHistoryUpdate_RecordsRowStats(t *testing.T) {
	stats := runencodestats.New()
	row := historyRow(t,
		&spb.HistoryItem{Key: "loss", ValueJson: "1.5"},
		&spb.HistoryItem{NestedKey: []string{"train", "acc"}, ValueJson: "0.9"},
	)

	requests := applyHistory(t, row, settings.New(), stats)

	require.Len(t, requests, 1)
	require.Len(t, requests[0].HistoryLines, 1)

	attrs := stats.Attributes()
	require.NotNil(t, attrs)
	assert.Equal(t, "1", attrs["rows"])
	assert.Equal(t, "2", attrs["cells"])
	assert.Equal(t, "0", attrs["skipped_oversize_rows"])

	// Row bytes must match the line that is actually queued.
	assert.Equal(t,
		itoa(len(requests[0].HistoryLines[0])),
		attrs["row_bytes"])
}

func TestHistoryUpdate_OversizeRowIsCountedAndDropped(t *testing.T) {
	stats := runencodestats.New()
	row := historyRow(t,
		&spb.HistoryItem{Key: "loss", ValueJson: "1.5"},
	)

	// One byte is smaller than any rendered line, so the row is skipped.
	s := settings.From(&spb.Settings{
		XFileStreamMaxLineBytes: wrapperspb.Int32(1),
	})

	requests := applyHistory(t, row, s, stats)

	assert.Empty(t, requests, "an oversize row must not be queued")

	attrs := stats.Attributes()
	require.NotNil(t, attrs)
	assert.Equal(t, "1", attrs["skipped_oversize_rows"])
	assert.Equal(t, "0", attrs["rows"])
	assert.Equal(t, "0", attrs["cells"])
}

func TestHistoryUpdate_NilStatsIsNoOp(t *testing.T) {
	row := historyRow(t, &spb.HistoryItem{Key: "loss", ValueJson: "1.5"})

	assert.NotPanics(t, func() {
		applyHistory(t, row, settings.New(), nil)
	})
}

func itoa(n int) string {
	return strconv.Itoa(n)
}
