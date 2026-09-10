package runreader_test

import (
	"context"
	"encoding/json"
	"fmt"
	"path/filepath"
	"strconv"
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
			Timestamp: timestamppb.New(time.Unix(1_700_000_000+step, 0)),
			Item:      []*spb.StatsItem{{Key: "cpu", ValueJson: "1"}},
		}}}))
	}
	require.NoError(t, w.Close())
}

// readAll runs the query, following pages, and returns the rows as maps
// with int64, float64 and decoded JSON values.
func readAll(t *testing.T, run *runreader.Run, query runreader.HistoryQuery) []map[string]any {
	t.Helper()
	var rows []map[string]any
	for {
		page, err := run.History(context.Background(), query)
		require.NoError(t, err)
		for _, chunk := range page.Chunks {
			chunkRows := make([]map[string]any, chunk.Rows)
			for i := range chunkRows {
				chunkRows[i] = map[string]any{}
			}
			for _, col := range chunk.Columns {
				n := len(col.Ints) + len(col.Floats) + len(col.JSON)
				for i := range n {
					row := i
					if col.RowIndex != nil {
						row = int(col.RowIndex[i])
					}
					switch {
					case col.Ints != nil:
						chunkRows[row][col.Key] = col.Ints[i]
					case col.Floats != nil:
						chunkRows[row][col.Key] = col.Floats[i]
					default:
						var v any
						require.NoError(t, json.Unmarshal([]byte(col.JSON[i]), &v))
						chunkRows[row][col.Key] = v
					}
				}
			}
			rows = append(rows, chunkRows...)
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
	steps := func(rows []map[string]any) []int64 {
		var steps []int64
		for _, row := range rows {
			steps = append(steps, row["_step"].(int64))
		}
		return steps
	}
	step := func(n int64) *int64 { return &n }

	page, err := run.History(context.Background(), runreader.HistoryQuery{})
	require.NoError(t, err)
	require.Len(t, page.Chunks, 1)
	chunk := page.Chunks[0]
	assert.Equal(t, 250, chunk.Rows)
	columns := map[string]*runreader.Column{}
	for _, col := range chunk.Columns {
		columns[col.Key] = col
	}
	// _step is a dense int column; loss starts as the integer 0 and becomes
	// a float column at 0.5; acc and val.loss are sparse.
	assert.Len(t, columns["_step"].Ints, 250)
	assert.Nil(t, columns["_step"].RowIndex)
	assert.Len(t, columns["loss"].Floats, 250)
	assert.Equal(t, []uint32{0, 10, 20}, columns["acc"].RowIndex[:3])
	assert.Equal(t, &runreader.Column{Key: "val.loss", Floats: []float64{0.25}, RowIndex: []uint32{7}},
		columns["val.loss"])

	rows := readAll(t, run, runreader.HistoryQuery{})
	require.Len(t, rows, 250)
	assert.Equal(t, map[string]any{"_step": int64(0), "loss": 0.0, "acc": 0.9}, rows[0])

	rows = readAll(t, run, runreader.HistoryQuery{Keys: []string{"acc"}})
	require.Len(t, rows, 25)
	assert.Equal(t, map[string]any{"_step": int64(240), "acc": 0.9}, rows[24])

	rows = readAll(t, run, runreader.HistoryQuery{MinStep: step(150), MaxStep: step(152)})
	assert.Equal(t, []int64{150, 151, 152}, steps(rows))

	rows = readAll(t, run, runreader.HistoryQuery{SystemMetrics: true, Last: 2})
	assert.Equal(t, []map[string]any{
		{"_timestamp": 1_700_000_248.0, "system.cpu": int64(1)},
		{"_timestamp": 1_700_000_249.0, "system.cpu": int64(1)},
	}, rows)

	rows = readAll(t, run, runreader.HistoryQuery{Keys: []string{"acc"}, Last: 12})
	assert.Equal(t, []int64{130, 140, 150, 160, 170, 180, 190, 200, 210, 220, 230, 240}, steps(rows))

	page, err = run.History(context.Background(), runreader.HistoryQuery{Limit: 100})
	require.NoError(t, err)
	pageRows := 0
	for _, chunk := range page.Chunks {
		pageRows += chunk.Rows
	}
	assert.Equal(t, 100, pageRows)
	assert.NotZero(t, page.NextOffset)
	rows = readAll(t, run, runreader.HistoryQuery{Limit: 100, Offset: page.NextOffset})
	assert.Equal(t, 150, len(rows))
	assert.Equal(t, int64(100), rows[0]["_step"])
}

func TestRun_HistoryPagesAcrossDecodeBatches(t *testing.T) {
	path := filepath.Join(t.TempDir(), "run-abc.wandb")
	writeHistoryLog(t, path, 20_000, 20)
	run, err := runreader.Open(path, observability.NewNoOpLogger())
	require.NoError(t, err)
	defer run.Close()
	require.NoError(t, run.Update(context.Background()))

	var steps []int64
	var pages, chunks int
	query := runreader.HistoryQuery{Keys: []string{"acc"}, Limit: 700}
	for {
		page, err := run.History(context.Background(), query)
		require.NoError(t, err)
		pages++
		chunks += len(page.Chunks)
		for _, chunk := range page.Chunks {
			for _, col := range chunk.Columns {
				if col.Key == "_step" {
					steps = append(steps, col.Ints...)
				}
			}
		}
		if page.NextOffset == 0 {
			break
		}
		query.Offset = page.NextOffset
	}
	require.Len(t, steps, 2000)
	for i, step := range steps {
		require.Equal(t, int64(10*i), step)
	}
	assert.Equal(t, 3, pages)
	assert.Greater(t, chunks, pages, "a page should span several decode batches")

	maxStep := int64(19_005)
	rows := readAll(t, run, runreader.HistoryQuery{MinStep: &maxStep, MaxStep: &maxStep})
	require.Len(t, rows, 1)
	assert.Equal(t, int64(19_005), rows[0]["_step"])
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
		"all":            {},
		"one_key":        {Keys: []string{"acc"}},
		"last_10":        {Last: 10},
		"system_last_10": {SystemMetrics: true, Last: 10},
		"tail_10":        {MinStep: &minStep},
		"page_1k":        {Limit: 1000},
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
