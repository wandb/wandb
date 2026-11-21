package metricsbatch

import (
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

// Builder accumulates prepared rows into one MetricsBatch.
//
// Use NewBuilder to create one.
type Builder struct {
	ids   map[string]uint32
	batch *filestreamv1.MetricsBatch
}

// NewBuilder returns an empty builder for history rows.
func NewBuilder() *Builder {
	b := &Builder{}
	b.reset()
	return b
}

func (b *Builder) reset() {
	b.ids = make(map[string]uint32)
	b.batch = &filestreamv1.MetricsBatch{SeqKey: seqKey}
}

// Append adds a prepared row to the batch.
//
// New keys get dictionary IDs in the order they appear.
func (b *Builder) Append(row *Row) {
	batch := b.batch
	for i := range row.cells {
		c := &row.cells[i]
		id, ok := b.ids[c.key]
		if !ok {
			id = uint32(len(batch.Keys))
			b.ids[c.key] = id
			batch.Keys = append(batch.Keys, c.key)
		}
		batch.CellKeys = append(batch.CellKeys, id)
		batch.CellKinds = append(batch.CellKinds, c.kind)

		switch c.kind {
		case filestreamv1.MetricsBatch_KIND_FLOAT:
			batch.Floats = append(batch.Floats, c.float)
		case filestreamv1.MetricsBatch_KIND_INT:
			batch.Ints = append(batch.Ints, c.int)
		case filestreamv1.MetricsBatch_KIND_BOOL:
			batch.Bools = append(batch.Bools, c.bool)
		case filestreamv1.MetricsBatch_KIND_STRING:
			batch.Strings = append(batch.Strings, c.text)
		case filestreamv1.MetricsBatch_KIND_JSON:
			batch.Jsons = append(batch.Jsons, c.text)
		}
	}
	batch.RowEnds = append(batch.RowEnds, uint32(len(batch.CellKinds)))
	batch.Seqs = append(batch.Seqs, row.step)
	batch.HasSeq = append(batch.HasSeq, row.hasStep)
}

// Rows returns the number of rows in the current batch.
func (b *Builder) Rows() int {
	return len(b.batch.RowEnds)
}

// Finish returns the batch and starts a new one.
//
// Later appends do not change the returned batch. An empty batch has
// SeqKey set and no rows.
func (b *Builder) Finish() *filestreamv1.MetricsBatch {
	batch := b.batch
	b.reset()
	return batch
}
