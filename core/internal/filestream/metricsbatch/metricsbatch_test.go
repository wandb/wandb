package metricsbatch

import (
	"fmt"
	"maps"
	"math"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func history(t *testing.T, items ...*spb.HistoryItem) *runhistory.RunHistory {
	t.Helper()
	rh := runhistory.New()
	for _, item := range items {
		require.NoError(t, rh.SetFromRecord(item))
	}
	return rh
}

func prepared(t *testing.T, items ...*spb.HistoryItem) *Row {
	t.Helper()
	row, err := Prepare(history(t, items...))
	require.NoError(t, err)
	return row
}

func finish(t *testing.T, b *Builder) *filestreamv1.MetricsBatch {
	t.Helper()
	batch := b.Finish()
	validate(t, batch)
	return batch
}

func validate(t *testing.T, batch *filestreamv1.MetricsBatch) {
	t.Helper()
	assert.Equal(t, "_step", batch.SeqKey)
	require.Len(t, batch.CellKeys, len(batch.CellKinds))
	require.Len(t, batch.Seqs, len(batch.RowEnds))
	require.Len(t, batch.HasSeq, len(batch.RowEnds))
	keys := make(map[string]bool)
	for _, key := range batch.Keys {
		assert.NotEmpty(t, key)
		assert.NotEqual(t, "_step", key)
		assert.False(t, keys[key])
		keys[key] = true
	}
	validateRows(t, batch)
	validatePayloads(t, batch)
}

func validateRows(t *testing.T, batch *filestreamv1.MetricsBatch) {
	t.Helper()
	var start uint32
	for _, end := range batch.RowEnds {
		require.GreaterOrEqual(t, end, start)
		require.LessOrEqual(t, uint64(end), uint64(len(batch.CellKinds)))
		seen := make(map[uint32]bool)
		for _, id := range batch.CellKeys[start:end] {
			require.Less(t, uint64(id), uint64(len(batch.Keys)))
			assert.False(t, seen[id])
			seen[id] = true
		}
		start = end
	}
	assert.Equal(t, uint64(len(batch.CellKinds)), uint64(start))
}

func validatePayloads(t *testing.T, batch *filestreamv1.MetricsBatch) {
	t.Helper()
	counts := make(map[filestreamv1.MetricsBatch_Kind]int)
	for _, kind := range batch.CellKinds {
		_, known := filestreamv1.MetricsBatch_Kind_name[int32(kind)]
		require.True(t, known)
		require.NotEqual(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		counts[kind]++
	}
	assert.Len(t, batch.Floats, counts[filestreamv1.MetricsBatch_KIND_FLOAT])
	assert.Len(t, batch.Ints, counts[filestreamv1.MetricsBatch_KIND_INT])
	assert.Len(t, batch.Bools, counts[filestreamv1.MetricsBatch_KIND_BOOL])
	assert.Len(t, batch.Strings, counts[filestreamv1.MetricsBatch_KIND_STRING])
	assert.Len(t, batch.Jsons, counts[filestreamv1.MetricsBatch_KIND_JSON])
}

func TestKindsAndPresence(t *testing.T) {
	tests := []struct {
		name  string
		items []*spb.HistoryItem
	}{
		{"typed", []*spb.HistoryItem{
			{Key: "null", Value: &spb.HistoryItem_None{}},
			{Key: "bool", Value: &spb.HistoryItem_Boolean{Boolean: false}},
			{Key: "int", Value: &spb.HistoryItem_Integer{Integer: 0}},
			{Key: "float", Value: &spb.HistoryItem_Number{Number: 0}},
			{Key: "string", Value: &spb.HistoryItem_Text{Text: ""}},
			{Key: "json", Value: &spb.HistoryItem_Json{Json: "[1]"}},
		}},
		{"legacy", []*spb.HistoryItem{
			{Key: "null", ValueJson: "null"}, {Key: "bool", ValueJson: "false"},
			{Key: "int", ValueJson: "0"}, {Key: "float", ValueJson: "0.0"},
			{Key: "string", ValueJson: `""`}, {Key: "json", ValueJson: "[1]"},
		}},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			b := NewBuilder()
			require.NoError(t, b.Append(prepared(t, tt.items...)))
			batch := finish(t, b)
			seen := make(map[int32]bool)
			for _, kind := range batch.CellKinds {
				seen[int32(kind)] = true
			}
			for kind := range filestreamv1.MetricsBatch_Kind_name {
				assert.Equal(t, kind != 0, seen[kind])
			}
			assert.NotContains(t, batch.Keys, "absent")
			assert.Equal(t, []bool{false}, batch.Bools)
			assert.Equal(t, []int64{0}, batch.Ints)
			assert.Equal(t, []string{""}, batch.Strings)
			assert.Len(t, batch.CellKinds, 6)
		})
	}
}

func TestStepsAndEmptyRows(t *testing.T) {
	tests := []struct {
		name    string
		item    *spb.HistoryItem
		step    int64
		present bool
	}{
		{name: "absent"},
		{"negative", &spb.HistoryItem{Key: "_step", ValueJson: "-2"}, -2, true},
		{
			"max",
			&spb.HistoryItem{Key: "_step", Value: &spb.HistoryItem_Integer{Integer: math.MaxInt64}},
			math.MaxInt64,
			true,
		},
	}
	b := NewBuilder()
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			var items []*spb.HistoryItem
			if tt.item != nil {
				items = append(items, tt.item)
			}
			require.NoError(t, b.Append(prepared(t, items...)))
			validate(t, b.batch)
			assert.Equal(t, tt.step, b.batch.Seqs[b.Rows()-1])
			assert.Equal(t, tt.present, b.batch.HasSeq[b.Rows()-1])
		})
	}
	assert.Equal(t, 3, b.Rows())
	assert.Equal(t, []uint32{0, 0, 0}, finish(t, b).RowEnds)
	assert.Zero(t, b.Rows())
	assert.Empty(t, finish(t, b).RowEnds)
}

func TestPrepareErrors(t *testing.T) {
	for _, text := range []string{`"secret"`, "null", "true", "1.0", "[]", `{"child":1}`} {
		t.Run(text, func(t *testing.T) {
			row, err := Prepare(history(t, &spb.HistoryItem{Key: "_step", ValueJson: text}))
			require.Error(t, err)
			assert.Nil(t, row)
			assert.NotContains(t, err.Error(), "secret")
		})
	}
	row, err := Prepare(history(t, &spb.HistoryItem{NestedKey: []string{""}, ValueJson: "1"}))
	require.Error(t, err)
	assert.Nil(t, row)
	for _, value := range []any{int(1234567), []any{int(1234567)}} {
		_, err := prepareCell("private-key", value)
		require.Error(t, err)
		assert.NotContains(t, err.Error(), "private-key")
		assert.NotContains(t, err.Error(), "1234567")
	}
}

func TestDictionaryAndNestedCells(t *testing.T) {
	b := NewBuilder()
	require.NoError(t, b.Append(prepared(t,
		&spb.HistoryItem{Key: "z", ValueJson: "1"},
		&spb.HistoryItem{Key: "m", Value: &spb.HistoryItem_Text{Text: "s"}},
	)))
	require.NoError(t, b.Append(prepared(t,
		&spb.HistoryItem{Key: "z", ValueJson: "2"},
		&spb.HistoryItem{NestedKey: []string{"a", "b"}, ValueJson: "1.0"},
		&spb.HistoryItem{NestedKey: []string{"a", "_step"}, ValueJson: "7"},
		&spb.HistoryItem{Key: "a.b", ValueJson: "false"},
	)))
	batch := finish(t, b)
	assert.Equal(t, []string{"m", "z", "a", "a.b"}, batch.Keys)
	assert.Equal(t, []uint32{0, 1, 2, 3, 1}, batch.CellKeys)
	assert.Equal(t, []uint32{2, 5}, batch.RowEnds)
	parsed, err := simplejsonext.UnmarshalString(batch.Jsons[0])
	require.NoError(t, err)
	assert.Equal(t, map[string]any{"b": int64(1), "_step": int64(7)}, parsed)
}

func TestUTF8AndCollisions(t *testing.T) {
	rh := history(t,
		&spb.HistoryItem{Key: "bad\xfe", ValueJson: "1"},
		&spb.HistoryItem{Key: "bad\xff", ValueJson: "2"},
		&spb.HistoryItem{Key: "text", Value: &spb.HistoryItem_Text{Text: "a\xff\xfeb"}},
		&spb.HistoryItem{
			NestedKey: []string{"json", "key\xff"},
			Value:     &spb.HistoryItem_Text{Text: "x\xff"},
		},
	)
	b := NewBuilder()
	require.NoError(t, b.Append(mustPrepare(t, rh)))
	batch := finish(t, b)
	assert.Equal(t, []string{"bad�", "json", "text"}, batch.Keys)
	assert.Equal(t, []int64{2}, batch.Ints)
	assert.Equal(t, []string{"a��b"}, batch.Strings)
	parsed, err := simplejsonext.UnmarshalString(batch.Jsons[0])
	require.NoError(t, err)
	assert.Equal(t, map[string]any{"key�": "x�"}, parsed)
	encoded, err := proto.Marshal(batch)
	require.NoError(t, err)
	assert.Contains(t, string(encoded), "�")
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(encoded, decoded))
	validate(t, decoded)
}

func mustPrepare(t *testing.T, rh *runhistory.RunHistory) *Row {
	t.Helper()
	row, err := Prepare(rh)
	require.NoError(t, err)
	return row
}

func TestAppendLimitsAtomic(t *testing.T) {
	for _, mode := range []string{"dictionary", "cells"} {
		t.Run(mode, func(t *testing.T) {
			b := NewBuilder()
			b.limit = 2
			require.NoError(t, b.Append(prepared(t, &spb.HistoryItem{Key: "a", ValueJson: "1"})))
			before := proto.Clone(b.batch)
			dictionary := maps.Clone(b.dictionary)
			var row *Row
			if mode == "dictionary" {
				// Make the dictionary the only overflowing count.
				b.limit = 3
				row = prepared(t,
					&spb.HistoryItem{Key: "b", ValueJson: "2"},
					&spb.HistoryItem{Key: "c", ValueJson: "3"},
					&spb.HistoryItem{Key: "d", ValueJson: "4"},
				)
				b.batch.CellKeys = nil
				b.batch.CellKinds = nil
				b.batch.Ints = nil
				b.batch.RowEnds[0] = 0
				before = proto.Clone(b.batch)
			} else {
				row = prepared(t,
					&spb.HistoryItem{Key: "a", ValueJson: "2"},
					&spb.HistoryItem{Key: "b", ValueJson: "3"},
				)
			}
			require.Error(t, b.Append(row))
			assert.True(t, proto.Equal(before, b.batch))
			assert.Equal(t, dictionary, b.dictionary)
			validate(t, b.batch)
			require.NoError(t, b.Append(prepared(t, &spb.HistoryItem{Key: "b", ValueJson: "4"})))
			validate(t, finish(t, b))
		})
	}
}

func TestOwnership(t *testing.T) {
	rh := history(t, &spb.HistoryItem{Key: "a", ValueJson: "[1,2]"})
	row := mustPrepare(t, rh)
	rh.WireCells(func(_ string, value any) bool {
		value.([]any)[0] = "changed"
		return true
	})
	rh.SetString(pathtree.PathOf("a"), "changed")
	first, second := NewBuilder(), NewBuilder()
	require.NoError(t, first.Append(row))
	require.NoError(t, second.Append(row))
	batch := finish(t, first)
	assert.Equal(t, []string{"[1,2]"}, batch.Jsons)
	before := proto.Clone(batch)
	require.NoError(t, first.Append(prepared(t, &spb.HistoryItem{Key: "new", ValueJson: "3"})))
	finish(t, first)
	assert.True(t, proto.Equal(before, batch))
	assert.True(t, proto.Equal(batch, finish(t, second)))
}

func TestWideRow(t *testing.T) {
	items := make([]*spb.HistoryItem, 10000)
	for i := range items {
		items[i] = &spb.HistoryItem{Key: fmt.Sprintf("key-%05d", i), ValueJson: "1"}
	}
	b := NewBuilder()
	require.NoError(t, b.Append(prepared(t, items...)))
	batch := finish(t, b)
	assert.Len(t, batch.Keys, 10000)
	assert.Equal(t, []uint32{10000}, batch.RowEnds)
}

func TestRoundTrip(t *testing.T) {
	items := [][]*spb.HistoryItem{
		{
			{Key: "_step", ValueJson: "-1"},
			{Key: "null", ValueJson: "null"}, {Key: "bool", ValueJson: "false"},
			{Key: "int", Value: &spb.HistoryItem_Integer{Integer: 9007199254740993}},
			{Key: "float", Value: &spb.HistoryItem_Number{Number: math.Copysign(0, -1)}},
			{Key: "text", Value: &spb.HistoryItem_Text{Text: "value"}},
			{Key: "json", ValueJson: `{"a":[1,true,null],"b":"x"}`},
		},
		{{Key: "float", ValueJson: "NaN"}, {Key: "positive", ValueJson: "0.0"}},
		{{Key: "float", ValueJson: "Infinity"}, {Key: "negative", ValueJson: "-Infinity"}},
		{},
	}
	b := NewBuilder()
	var expected []map[string]any
	for _, records := range items {
		rh := history(t, records...)
		expected = append(expected, inputValues(rh))
		require.NoError(t, b.Append(mustPrepare(t, rh)))
	}
	batch := finish(t, b)
	encoded, err := proto.Marshal(batch)
	require.NoError(t, err)
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(encoded, decoded))
	validate(t, decoded)
	actual := reconstruct(t, decoded)
	require.Len(t, actual, len(expected))
	for i := range expected {
		compareRow(t, expected[i], actual[i])
	}
}

func inputValues(rh *runhistory.RunHistory) map[string]any {
	values := make(map[string]any)
	rh.WireCells(func(key string, value any) bool {
		values[key] = value
		return true
	})
	if step, ok := rh.GetInt(pathtree.PathOf("_step")); ok {
		values["_step"] = step
	}
	return values
}

func reconstruct(t *testing.T, batch *filestreamv1.MetricsBatch) []map[string]any {
	t.Helper()
	rows := make([]map[string]any, len(batch.RowEnds))
	indices := make(map[filestreamv1.MetricsBatch_Kind]int)
	var start uint32
	for i, end := range batch.RowEnds {
		row := make(map[string]any)
		for j := start; j < end; j++ {
			kind := batch.CellKinds[j]
			row[batch.Keys[batch.CellKeys[j]]] = payload(t, batch, kind, indices[kind])
			indices[kind]++
		}
		if batch.HasSeq[i] {
			row["_step"] = batch.Seqs[i]
		}
		rows[i] = row
		start = end
	}
	return rows
}

func payload(
	t *testing.T,
	batch *filestreamv1.MetricsBatch,
	kind filestreamv1.MetricsBatch_Kind,
	i int,
) any {
	t.Helper()
	switch kind {
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		return batch.Floats[i]
	case filestreamv1.MetricsBatch_KIND_INT:
		return batch.Ints[i]
	case filestreamv1.MetricsBatch_KIND_BOOL:
		return batch.Bools[i]
	case filestreamv1.MetricsBatch_KIND_STRING:
		return batch.Strings[i]
	case filestreamv1.MetricsBatch_KIND_JSON:
		value, err := simplejsonext.UnmarshalString(batch.Jsons[i])
		require.NoError(t, err)
		return value
	default:
		return nil
	}
}

func compareRow(t *testing.T, expected, actual map[string]any) {
	t.Helper()
	require.Len(t, actual, len(expected))
	for key, value := range expected {
		got, exists := actual[key]
		require.True(t, exists)
		if f, ok := value.(float64); ok {
			g, ok := got.(float64)
			require.True(t, ok)
			if math.IsNaN(f) {
				assert.True(t, math.IsNaN(g))
			} else {
				assert.Equal(t, math.Float64bits(f), math.Float64bits(g))
			}
		} else {
			assert.Equal(t, value, got)
		}
	}
}

func TestErrorDoesNotLeakJSON(t *testing.T) {
	_, err := encodeJSON(map[string]any{"private-key": strings.NewReader("private-value")})
	require.Error(t, err)
	assert.NotContains(t, err.Error(), "private-key")
	assert.NotContains(t, err.Error(), "private-value")
}
