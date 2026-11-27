package filestream

import (
	"google.golang.org/protobuf/encoding/protowire"

	"github.com/wandb/wandb/core/internal/filestream/metricsbatch"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

type sealedHistoryBatch struct {
	batch       *filestreamv1.MetricsBatch
	batchBytes  int
	budgetBytes int
}

type historyAccumulator struct {
	maxHistoryBytes int
	open            *metricsbatch.Builder
	sealed          []*sealedHistoryBatch
}

func newHistoryAccumulator(maxHistoryBytes int) *historyAccumulator {
	return &historyAccumulator{
		maxHistoryBytes: maxHistoryBytes,
		open:            metricsbatch.NewBuilder(),
	}
}

func (a *historyAccumulator) Append(row *metricsbatch.Row) {
	if rows := a.open.Rows(); rows != 0 {
		projected := historyBudgetBytes(a.open.EstimateAppendSize(row), rows+1)
		if projected > a.maxHistoryBytes {
			a.Seal()
		}
	}
	a.open.Append(row)
	if a.openBudgetBytes() > a.maxHistoryBytes {
		a.Seal()
	}
}

func (a *historyAccumulator) Seal() {
	if a.open.Rows() == 0 {
		return
	}
	batchBytes := a.open.EncodedSize()
	a.sealed = append(a.sealed, &sealedHistoryBatch{
		budgetBytes: historyBudgetBytes(batchBytes, a.open.Rows()),
		batchBytes:  batchBytes,
		batch:       a.open.Finish(),
	})
}

func (a *historyAccumulator) hasMore() bool {
	return a != nil && (len(a.sealed) > 0 || a.open.Rows() > 0)
}

func (a *historyAccumulator) openBudgetBytes() int {
	if a.open.Rows() == 0 {
		return 0
	}
	return historyBudgetBytes(a.open.EncodedSize(), a.open.Rows())
}

func historyBudgetBytes(batchBytes, rows int) int {
	// Charge the widest possible offset, including its tag, before it is assigned.
	chunkBytes := protowire.SizeTag(1) + 10 +
		protowire.SizeTag(2) + protowire.SizeVarint(uint64(rows)) +
		protowire.SizeTag(3) + protowire.SizeBytes(batchBytes)
	return protowire.SizeTag(2) + protowire.SizeBytes(chunkBytes)
}

func (a *historyAccumulator) PopSealed() *sealedHistoryBatch {
	if len(a.sealed) == 0 {
		return nil
	}
	batch := a.sealed[0]
	a.sealed[0] = nil
	a.sealed = a.sealed[1:]
	if len(a.sealed) == 0 {
		a.sealed = nil
	}
	return batch
}
