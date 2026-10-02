package runreader_test

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strconv"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runreader"
	"github.com/wandb/wandb/core/internal/transactionlog"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// writeHistoryLog writes rows history records with a loss value, an acc
// value on every tenth row and a nested val/loss value on row 7, interleaved
// with a stats record per row.
func writeHistoryLog(t testing.TB, path string, rows int, extraKeys int) {
	t.Helper()
	w, err := transactionlog.OpenWriter(path)
	require.NoError(t, err)
	require.NoError(t, w.Write(runRecord("abc", nil)))
	for step := range int64(rows) {
		items := map[string]string{"_step": strconv.FormatInt(step, 10), "loss": fmt.Sprintf("%g", float64(step)/2)}
		if step%10 == 0 {
			items["acc"] = "0.9"
		}
		for i := range extraKeys {
			items[fmt.Sprintf("m%d", i)] = "1.5"
		}
		record := historyRecord(step, items)
		if step == 7 {
			record.GetHistory().Item = append(record.GetHistory().Item,
				&spb.HistoryItem{NestedKey: []string{"val", "loss"}, ValueJson: "0.25"})
		}
		require.NoError(t, w.Write(record))
		require.NoError(t, w.Write(&spb.Record{RecordType: &spb.Record_Stats{Stats: &spb.StatsRecord{
			Item: []*spb.StatsItem{{Key: "cpu", ValueJson: "1"}},
		}}}))
	}
	require.NoError(t, w.Close())
}

// readAll runs the query, following pages, and returns the decoded rows.
func readAll(t *testing.T, run *runreader.Run, query runreader.HistoryQuery) []map[string]any {
	t.Helper()
	var rows []map[string]any
	for {
		page, err := run.History(context.Background(), query)
		require.NoError(t, err)
		decoder := json.NewDecoder(bytes.NewReader(page.Rows))
		for decoder.More() {
			var row map[string]any
			require.NoError(t, decoder.Decode(&row))
			rows = append(rows, row)
		}
		if page.NextOffset == 0 {
			return rows
		}
		query.Offset = page.NextOffset
	}
}

func TestRun_History(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	writeHistoryLog(t, path, 250, 0)
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))
	steps := func(rows []map[string]any) []float64 {
		var steps []float64
		for _, row := range rows {
			steps = append(steps, row["_step"].(float64))
		}
		return steps
	}
	step := func(n int64) *int64 { return &n }

	rows := readAll(t, run, runreader.HistoryQuery{})
	require.Len(t, rows, 250)
	assert.Equal(t, map[string]any{"_step": 0.0, "loss": 0.0, "acc": 0.9}, rows[0])
	assert.Equal(t, 0.25, rows[7]["val.loss"])

	rows = readAll(t, run, runreader.HistoryQuery{Keys: []string{"acc"}})
	require.Len(t, rows, 25)
	assert.Equal(t, map[string]any{"_step": 240.0, "acc": 0.9}, rows[24])

	rows = readAll(t, run, runreader.HistoryQuery{MinStep: step(150), MaxStep: step(152)})
	assert.Equal(t, []float64{150, 151, 152}, steps(rows))

	rows = readAll(t, run, runreader.HistoryQuery{Keys: []string{"acc"}, Last: 12})
	assert.Equal(t, []float64{130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240}, steps(rows))

	page, err := run.History(context.Background(), runreader.HistoryQuery{Limit: 100})
	require.NoError(t, err)
	assert.Equal(t, 100, bytes.Count(page.Rows, []byte("\n")))
	assert.NotZero(t, page.NextOffset)
	rows = readAll(t, run, runreader.HistoryQuery{Limit: 100, Offset: page.NextOffset})
	assert.Equal(t, 150, len(rows))
	assert.Equal(t, 100.0, rows[0]["_step"])
}

func BenchmarkHistory(b *testing.B) {
	path := filepath.Join(b.TempDir(), "run-abc.wandb")
	writeHistoryLog(b, path, 20_000, 20)
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(b, err)
	defer run.Close()
	require.NoError(b, run.Update(context.Background()))
	minStep := int64(19_990)
	for name, query := range map[string]runreader.HistoryQuery{
		"all":     {},
		"one_key": {Keys: []string{"acc"}},
		"last_10": {Last: 10},
		"tail_10": {MinStep: &minStep},
		"page_1k": {Limit: 1000},
	} {
		b.Run(name, func(b *testing.B) {
			for b.Loop() {
				if _, err := run.History(context.Background(), query); err != nil {
					b.Fatal(err)
				}
			}
		})
	}
}
