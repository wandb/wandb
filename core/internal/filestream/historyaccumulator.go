package filestream

import (
	"github.com/wandb/wandb/core/internal/filestream/metricsbatch"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

type sealedHistoryBatch struct {
	batch      *filestreamv1.MetricsBatch
	batchBytes int
}

type historyAccumulator struct {
	maxBatchBytes int
	open          *metricsbatch.Builder
	sealed        []*sealedHistoryBatch
}

func newHistoryAccumulator(maxBatchBytes int) *historyAccumulator {
	return &historyAccumulator{
		maxBatchBytes: maxBatchBytes,
		open:          metricsbatch.NewBuilder(),
	}
}

func (a *historyAccumulator) Append(row *metricsbatch.Row) {
	if a.open.Rows() != 0 && a.open.EstimateAppendSize(row) > a.maxBatchBytes {
		a.Seal()
	}
	a.open.Append(row)
	if a.open.EncodedSize() > a.maxBatchBytes {
		a.Seal()
	}
}

func (a *historyAccumulator) Seal() {
	if a.open.Rows() == 0 {
		return
	}
	batchBytes := a.open.EncodedSize()
	a.sealed = append(a.sealed, &sealedHistoryBatch{
		batch:      a.open.Finish(),
		batchBytes: batchBytes,
	})
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
