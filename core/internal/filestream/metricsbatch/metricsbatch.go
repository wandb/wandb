// Package metricsbatch builds MetricsBatch messages from RunHistory rows.
// Only top-level keys become cells; a nested subtree is one JSON cell.
// JSON uses simplejsonext's float spelling (so 1.0 becomes 1).
// Prepare validates and encodes values; Append only fails on uint32 limits.
package metricsbatch

import (
	"errors"
	"math"
	"slices"

	"github.com/wandb/simplejsonext"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
)

type cell struct {
	key   string
	kind  filestreamv1.MetricsBatch_Kind
	value any
}

// Row is an immutable, validated row. It may be appended to several builders.
type Row struct {
	cells   []cell
	step    int64
	hasStep bool
}

// Prepare validates and encodes a row independently of any builder.
// Repaired keys that collide use the lexically last original key's value.
// The returned Row does not retain mutable RunHistory values.
func Prepare(rh *runhistory.RunHistory) (*Row, error) {
	row := &Row{}
	var err error
	row.step, row.hasStep, err = prepareStep(rh)
	if err != nil {
		return nil, err
	}
	indices := make(map[string]int)
	rh.WireCells(func(key string, value any) bool {
		key = historycodec.NormalizeString(key)
		if key == "" {
			err = errors.New("metricsbatch: empty key")
			return false
		}
		var c cell
		c, err = prepareCell(key, value)
		if err != nil {
			return false
		}
		if i, exists := indices[key]; exists {
			row.cells[i] = c
		} else {
			indices[key] = len(row.cells)
			row.cells = append(row.cells, c)
		}
		return true
	})
	if err != nil {
		return nil, err
	}
	return row, nil
}

func prepareStep(rh *runhistory.RunHistory) (int64, bool, error) {
	if step, ok := rh.GetInt(pathtree.PathOf("_step")); ok {
		return step, true, nil
	}
	invalid := false
	rh.ForEachKey(func(path pathtree.TreePath) bool {
		invalid = path.Labels()[0] == "_step"
		return !invalid
	})
	if invalid {
		return 0, false, errors.New("metricsbatch: sequence must be int64")
	}
	return 0, false, nil
}

func prepareCell(key string, value any) (cell, error) {
	kind, err := historycodec.Kind(value)
	if err != nil {
		return cell{}, err
	}
	switch kind {
	case filestreamv1.MetricsBatch_KIND_STRING:
		value = historycodec.NormalizeString(value.(string))
	case filestreamv1.MetricsBatch_KIND_JSON:
		value, err = encodeJSON(value)
	}
	return cell{key: key, kind: kind, value: value}, err
}

func encodeJSON(value any) (string, error) {
	normalized, err := historycodec.Normalize(value)
	if err != nil {
		return "", err
	}
	encoded, err := simplejsonext.Marshal(normalized)
	if err != nil {
		return "", errors.New("metricsbatch: JSON encoding failed")
	}
	return string(encoded), nil
}

// Builder accumulates prepared rows. Use NewBuilder to initialize it.
type Builder struct {
	dictionary map[string]uint32
	batch      *filestreamv1.MetricsBatch
	limit      uint64
}

// NewBuilder returns an empty builder with the history sequence key set.
func NewBuilder() *Builder {
	b := &Builder{limit: math.MaxUint32}
	b.reset()
	return b
}

func (b *Builder) reset() {
	b.dictionary = make(map[string]uint32)
	b.batch = &filestreamv1.MetricsBatch{SeqKey: "_step"}
}

// Append adds a prepared row. On a uint32 limit error, nothing is changed.
func (b *Builder) Append(row *Row) error {
	newKeys := make([]string, 0)
	for _, c := range row.cells {
		if _, exists := b.dictionary[c.key]; !exists {
			newKeys = append(newKeys, c.key)
		}
	}
	if uint64(len(b.dictionary))+uint64(len(newKeys)) > b.limit ||
		uint64(len(b.batch.CellKinds))+uint64(len(row.cells)) > b.limit {
		return errors.New("metricsbatch: uint32 limit exceeded")
	}
	b.grow(row, len(newKeys))
	for _, key := range newKeys {
		b.dictionary[key] = uint32(len(b.batch.Keys))
		b.batch.Keys = append(b.batch.Keys, key)
	}
	for _, c := range row.cells {
		b.batch.CellKeys = append(b.batch.CellKeys, b.dictionary[c.key])
		b.batch.CellKinds = append(b.batch.CellKinds, c.kind)
		b.appendPayload(c)
	}
	b.batch.RowEnds = append(b.batch.RowEnds, uint32(len(b.batch.CellKinds)))
	b.batch.Seqs = append(b.batch.Seqs, row.step)
	b.batch.HasSeq = append(b.batch.HasSeq, row.hasStep)
	return nil
}

func (b *Builder) grow(row *Row, keys int) {
	var counts [7]int
	for _, c := range row.cells {
		counts[c.kind]++
	}
	p := b.batch
	p.Keys = slices.Grow(p.Keys, keys)
	p.CellKeys = slices.Grow(p.CellKeys, len(row.cells))
	p.CellKinds = slices.Grow(p.CellKinds, len(row.cells))
	p.Floats = slices.Grow(p.Floats, counts[filestreamv1.MetricsBatch_KIND_FLOAT])
	p.Ints = slices.Grow(p.Ints, counts[filestreamv1.MetricsBatch_KIND_INT])
	p.Bools = slices.Grow(p.Bools, counts[filestreamv1.MetricsBatch_KIND_BOOL])
	p.Strings = slices.Grow(p.Strings, counts[filestreamv1.MetricsBatch_KIND_STRING])
	p.Jsons = slices.Grow(p.Jsons, counts[filestreamv1.MetricsBatch_KIND_JSON])
	p.RowEnds = slices.Grow(p.RowEnds, 1)
	p.Seqs = slices.Grow(p.Seqs, 1)
	p.HasSeq = slices.Grow(p.HasSeq, 1)
}

func (b *Builder) appendPayload(c cell) {
	switch c.kind {
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		b.batch.Floats = append(b.batch.Floats, c.value.(float64))
	case filestreamv1.MetricsBatch_KIND_INT:
		b.batch.Ints = append(b.batch.Ints, c.value.(int64))
	case filestreamv1.MetricsBatch_KIND_BOOL:
		b.batch.Bools = append(b.batch.Bools, c.value.(bool))
	case filestreamv1.MetricsBatch_KIND_STRING:
		b.batch.Strings = append(b.batch.Strings, c.value.(string))
	case filestreamv1.MetricsBatch_KIND_JSON:
		b.batch.Jsons = append(b.batch.Jsons, c.value.(string))
	}
}

// Rows returns the number of rows currently accumulated.
func (b *Builder) Rows() int { return len(b.batch.RowEnds) }

// Finish transfers ownership of the batch to the caller and resets the builder.
// An empty builder returns a batch with SeqKey set and no rows.
func (b *Builder) Finish() *filestreamv1.MetricsBatch {
	batch := b.batch
	b.reset()
	return batch
}
