package filestream

import (
	"fmt"
	"strings"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/filestream/metricsbatch"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
)

func TestHistoryAccumulatorExactFitAndRollover(t *testing.T) {
	first := historyRow(t, 1, "overlap", "a")
	second := historyRow(t, 2, "overlap", "b")
	third := historyRow(t, 3, "new", "c")

	oracle := metricsbatch.NewBuilder()
	oracle.Append(first)
	oracle.Append(second)
	batchBytes := proto.Size(oracle.Finish())
	batchLimit := historyBudgetBytes(batchBytes, 2)

	a := newHistoryAccumulator(batchLimit)
	a.Seal()
	require.Nil(t, a.PopSealed())
	a.Append(first)
	a.Append(second)
	require.Equal(t, batchBytes, a.open.EncodedSize())
	require.Equal(t, batchLimit, a.openBudgetBytes())
	require.Nil(t, a.PopSealed())
	a.Append(third)
	sealed := popHistoryBatchForTest(t, a)
	require.Equal(t, batchBytes, sealed.batchBytes)
	require.Equal(t, batchLimit, sealed.budgetBytes)
	require.Equal(t, []int64{1, 2}, sealed.batch.Seqs)
	require.Equal(t, []string{"overlap"}, sealed.batch.Keys)
	require.Equal(t, []string{"a", "b"}, sealed.batch.Strings)
	require.Nil(t, a.PopSealed())

	a.Append(historyRow(t, 4, "new", "d"))
	a.Seal()
	a.Seal()
	remaining := popHistoryBatchForTest(t, a)
	require.Equal(t, []int64{3, 4}, remaining.batch.Seqs)
	require.Equal(t, []string{"new"}, remaining.batch.Keys)
	require.Equal(t, []uint32{0, 0}, remaining.batch.CellKeys)
	require.Nil(t, a.PopSealed())
	require.Equal(t, []int64{1, 2}, sealed.batch.Seqs)
	require.Equal(t, []string{"a", "b"}, sealed.batch.Strings)
}

func TestHistoryAccumulatorOversizedSingleton(t *testing.T) {
	for _, batchLimit := range []int{8 << 20, 19 << 19} {
		t.Run(fmt.Sprint(batchLimit), func(t *testing.T) {
			a := newHistoryAccumulator(batchLimit)
			a.Append(&metricsbatch.Row{})
			a.Append(historyRow(t, 1, "wide", strings.Repeat("x", batchLimit)))
			head := popHistoryBatchForTest(t, a)
			require.Equal(t, []uint32{0}, head.batch.RowEnds)
			require.Equal(t, []bool{false}, head.batch.HasSeq)
			oversized := popHistoryBatchForTest(t, a)
			require.Greater(t, oversized.batchBytes, batchLimit)
			require.Equal(t, []int64{1}, oversized.batch.Seqs)
			require.Len(t, oversized.batch.Strings[0], batchLimit)
			a.Append(historyRow(t, 2, "small", "tail"))
			a.Seal()
			tail := popHistoryBatchForTest(t, a)
			require.Equal(t, []int64{2}, tail.batch.Seqs)
			require.Equal(t, []string{"tail"}, tail.batch.Strings)
			require.Nil(t, a.PopSealed())
		})
	}
}

func historyRow(t *testing.T, step int64, key, value string) *metricsbatch.Row {
	t.Helper()
	rh := runhistory.New()
	rh.SetInt(pathtree.PathOf("_step"), step)
	rh.SetString(pathtree.PathOf(key), value)
	row, err := metricsbatch.Prepare(rh)
	require.NoError(t, err)
	return row
}

func popHistoryBatchForTest(t *testing.T, a *historyAccumulator) *sealedHistoryBatch {
	t.Helper()
	batch := a.PopSealed()
	require.NotNil(t, batch)
	require.Equal(t, proto.Size(batch.batch), batch.batchBytes)
	wire, err := proto.Marshal(batch.batch)
	require.NoError(t, err)
	// A negative int64 occupies the maximum possible offset width.
	envelope := &filestreamv1.FileStreamUpload{
		History: &filestreamv1.MetricsBatchChunk{
			Offset:   -1,
			RowCount: int64(len(batch.batch.RowEnds)),
			Batch:    batch.batch,
		},
	}
	require.Equal(t, proto.Size(envelope), batch.budgetBytes)
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(wire, decoded))
	require.True(t, proto.Equal(batch.batch, decoded))
	return batch
}
