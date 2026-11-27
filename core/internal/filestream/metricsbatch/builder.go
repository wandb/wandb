package metricsbatch

import (
	"slices"

	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
)

// Builder accumulates prepared rows into one MetricsBatch.
//
// Use NewBuilder to create one.
type Builder struct {
	ids   map[string]uint32
	batch *filestreamv1.MetricsBatch
	size  batchWireSize
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
	b.size = batchWireSize{unpacked: proto.Size(b.batch)}
}

// EncodedSize returns the number of bytes in the current batch's wire encoding.
func (b *Builder) EncodedSize() int {
	return b.size.total()
}

// EstimateAppendSize returns the exact encoded size after appending row
// without changing the builder.
func (b *Builder) EstimateAppendSize(row *Row) int {
	size := b.size
	nextID := uint32(len(b.batch.Keys))
	// Prepared rows contain each top-level key at most once.
	for i := range row.cells {
		c := &row.cells[i]
		id, exists := b.ids[c.key]
		if !exists {
			id = nextID
			nextID++
		}
		size.addCell(c, id, !exists)
	}
	size.addRow(row, uint32(len(b.batch.CellKinds)+len(row.cells)))
	return size.total()
}

// Append adds a prepared row to the batch.
//
// New keys get dictionary IDs in the order they appear.
func (b *Builder) Append(row *Row) {
	batch := b.batch
	b.reserve(row)
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
		b.size.addCell(c, id, !ok)

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
	rowEnd := uint32(len(batch.CellKinds))
	batch.RowEnds = append(batch.RowEnds, rowEnd)
	batch.Seqs = append(batch.Seqs, row.step)
	batch.HasSeq = append(batch.HasSeq, row.hasStep)
	b.size.addRow(row, rowEnd)
}

func (b *Builder) reserve(row *Row) {
	batch := b.batch
	batch.CellKeys = slices.Grow(batch.CellKeys, len(row.cells))
	batch.CellKinds = slices.Grow(batch.CellKinds, len(row.cells))
	batch.Floats = slices.Grow(batch.Floats, row.counts[filestreamv1.MetricsBatch_KIND_FLOAT])
	batch.Ints = slices.Grow(batch.Ints, row.counts[filestreamv1.MetricsBatch_KIND_INT])
	batch.Bools = slices.Grow(batch.Bools, row.counts[filestreamv1.MetricsBatch_KIND_BOOL])
	batch.Strings = slices.Grow(batch.Strings, row.counts[filestreamv1.MetricsBatch_KIND_STRING])
	batch.Jsons = slices.Grow(batch.Jsons, row.counts[filestreamv1.MetricsBatch_KIND_JSON])
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
