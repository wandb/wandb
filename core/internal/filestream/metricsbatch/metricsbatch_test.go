package metricsbatch

import (
	"errors"
	"fmt"
	"math"
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

// history builds a row through the production decoder.
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

func build(t *testing.T, rows ...*Row) *filestreamv1.MetricsBatch {
	t.Helper()
	b := NewBuilder()
	for _, row := range rows {
		b.Append(row)
	}
	return b.Finish()
}

// typedValue is a decoded cell with its kind.
type typedValue struct {
	kind  filestreamv1.MetricsBatch_Kind
	value any
}

// decode round-trips the batch through protobuf, checks each decoder
// rule of the wire proto, and returns the rows. A present step is under
// "_step" with KIND_INT.
func decode(t *testing.T, batch *filestreamv1.MetricsBatch) []map[string]typedValue {
	t.Helper()
	encoded, err := proto.Marshal(batch)
	require.NoError(t, err)
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(encoded, decoded))
	batch = decoded

	assert.Equal(t, seqKey, batch.SeqKey)
	cellCount := len(batch.CellKinds)
	require.Len(t, batch.CellKeys, cellCount)
	if len(batch.RowEnds) > 0 {
		require.EqualValues(t, cellCount, batch.RowEnds[len(batch.RowEnds)-1])
	} else {
		require.Zero(t, cellCount)
	}
	if len(batch.Seqs) > 0 || len(batch.HasSeq) > 0 {
		require.Len(t, batch.Seqs, len(batch.RowEnds))
		require.Len(t, batch.HasSeq, len(batch.RowEnds))
	}

	dictionary := make(map[string]bool)
	for _, key := range batch.Keys {
		require.NotEmpty(t, key)
		require.NotEqual(t, seqKey, key)
		require.False(t, dictionary[key], "duplicate dictionary key")
		dictionary[key] = true
	}

	counts := make(map[filestreamv1.MetricsBatch_Kind]int)
	for _, kind := range batch.CellKinds {
		_, known := filestreamv1.MetricsBatch_Kind_name[int32(kind)]
		require.True(t, known)
		require.NotEqual(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		counts[kind]++
	}
	require.Len(t, batch.Floats, counts[filestreamv1.MetricsBatch_KIND_FLOAT])
	require.Len(t, batch.Ints, counts[filestreamv1.MetricsBatch_KIND_INT])
	require.Len(t, batch.Bools, counts[filestreamv1.MetricsBatch_KIND_BOOL])
	require.Len(t, batch.Strings, counts[filestreamv1.MetricsBatch_KIND_STRING])
	require.Len(t, batch.Jsons, counts[filestreamv1.MetricsBatch_KIND_JSON])

	rows := make([]map[string]typedValue, len(batch.RowEnds))
	next := make(map[filestreamv1.MetricsBatch_Kind]int)
	var start uint32
	for i, end := range batch.RowEnds {
		require.GreaterOrEqual(t, end, start)
		row := make(map[string]typedValue)
		for j := start; j < end; j++ {
			id := batch.CellKeys[j]
			require.Less(t, int(id), len(batch.Keys))
			key := batch.Keys[id]
			_, repeated := row[key]
			require.False(t, repeated, "key repeated in a row")
			kind := batch.CellKinds[j]
			row[key] = typedValue{kind, payload(t, batch, kind, next[kind])}
			next[kind]++
		}
		if len(batch.HasSeq) > 0 && batch.HasSeq[i] {
			row[seqKey] = typedValue{filestreamv1.MetricsBatch_KIND_INT, batch.Seqs[i]}
		} else if len(batch.Seqs) > 0 {
			assert.Zero(t, batch.Seqs[i])
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
		switch value.(type) {
		case []any, map[string]any:
		default:
			require.Fail(t, "KIND_JSON cell holds a scalar")
		}
		return value
	default:
		return nil
	}
}

// assertSameValue compares floats by bits and JSON trees by parsed value,
// where numerically equal ints and floats match and NaN matches NaN.
func assertSameValue(t *testing.T, expected, actual any, json bool) {
	t.Helper()
	if json {
		assert.True(t, sameJSON(expected, actual),
			"expected %#v, got %#v", expected, actual)
		return
	}
	if f, ok := expected.(float64); ok {
		g, ok := actual.(float64)
		require.True(t, ok, "expected float64, got %T", actual)
		if math.IsNaN(f) {
			assert.True(t, math.IsNaN(g))
		} else {
			assert.Equal(t, math.Float64bits(f), math.Float64bits(g))
		}
		return
	}
	assert.Equal(t, expected, actual)
}

func sameJSON(a, b any) bool {
	if x, ok := asFloat(a); ok {
		y, ok := asFloat(b)
		return ok && (x == y || math.IsNaN(x) && math.IsNaN(y))
	}
	switch x := a.(type) {
	case []any:
		y, ok := b.([]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for i := range x {
			if !sameJSON(x[i], y[i]) {
				return false
			}
		}
		return true
	case map[string]any:
		y, ok := b.(map[string]any)
		if !ok || len(x) != len(y) {
			return false
		}
		for k, v := range x {
			w, exists := y[k]
			if !exists || !sameJSON(v, w) {
				return false
			}
		}
		return true
	default:
		return a == b
	}
}

func asFloat(v any) (float64, bool) {
	switch x := v.(type) {
	case int64:
		return float64(x), true
	case float64:
		return x, true
	}
	return 0, false
}

func joinedErrors(err error) []error {
	if err == nil {
		return nil
	}
	if joined, ok := err.(interface{ Unwrap() []error }); ok {
		return joined.Unwrap()
	}
	return []error{err}
}

// TestFixtures runs each T16 fixture through SetFromRecord, Prepare,
// Append, Finish and decode.
func TestFixtures(t *testing.T) {
	b := NewBuilder()
	for _, f := range fixtures {
		item := proto.Clone(f.item).(*spb.HistoryItem)
		item.Key = "metric"
		b.Append(prepared(t, item))
	}
	rows := decode(t, b.Finish())
	require.Len(t, rows, len(fixtures))

	seen := make(map[filestreamv1.MetricsBatch_Kind]bool)
	for i, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			got, present := rows[i]["metric"]
			if f.name == "json/empty object" {
				assert.False(t, present, "an empty object makes no cell")
				return
			}
			require.True(t, present)
			require.Len(t, rows[i], 1)
			assert.Equal(t, f.kind, got.kind)
			seen[got.kind] = true

			expected, err := simplejsonext.UnmarshalString(f.json)
			require.NoError(t, err)
			assertSameValue(t, expected, got.value,
				f.kind == filestreamv1.MetricsBatch_KIND_JSON)
		})
	}

	for value, name := range filestreamv1.MetricsBatch_Kind_name {
		kind := filestreamv1.MetricsBatch_Kind(value)
		if kind != filestreamv1.MetricsBatch_KIND_UNSPECIFIED {
			assert.True(t, seen[kind], "no fixture produces %s", name)
		}
	}
}

// TestOneofCoverage requires a fixture for every alternative of the
// HistoryItem.value oneof. A schema addition fails here until the
// mapping extends.
func TestOneofCoverage(t *testing.T) {
	oneof := (&spb.HistoryItem{}).ProtoReflect().
		Descriptor().Oneofs().ByName("value")
	require.NotNil(t, oneof)

	covered := make(map[string]int)
	for _, f := range fixtures {
		field := f.item.ProtoReflect().WhichOneof(oneof)
		require.NotNil(t, field)
		covered[string(field.Name())]++
	}

	fields := oneof.Fields()
	for i := range fields.Len() {
		name := string(fields.Get(i).Name())
		assert.NotZero(t, covered[name], "no fixture for value alternative %q", name)
		delete(covered, name)
	}
	assert.Empty(t, covered, "fixtures exist for alternatives not in the schema")
}

func TestTypedLegacyAndMixedItems(t *testing.T) {
	typed := []*spb.HistoryItem{
		{Key: "null", Value: &spb.HistoryItem_None{}},
		{Key: "bool", Value: &spb.HistoryItem_Boolean{Boolean: true}},
		{Key: "int", Value: &spb.HistoryItem_Integer{Integer: 7}},
		{Key: "float", Value: &spb.HistoryItem_Number{Number: 1.5}},
		{Key: "string", Value: &spb.HistoryItem_Text{Text: "s"}},
		{Key: "json", Value: &spb.HistoryItem_Json{Json: `[1,"x"]`}},
	}
	legacy := []*spb.HistoryItem{
		{Key: "null", ValueJson: "null"},
		{Key: "bool", ValueJson: "true"},
		{Key: "int", ValueJson: "7"},
		{Key: "float", ValueJson: "1.5"},
		{Key: "string", ValueJson: `"s"`},
		{Key: "json", ValueJson: `[1,"x"]`},
	}
	var mixed []*spb.HistoryItem
	for i := range typed {
		if i%2 == 0 {
			mixed = append(mixed, typed[i])
		} else {
			mixed = append(mixed, legacy[i])
		}
	}

	want := build(t, prepared(t, typed...))
	assert.Len(t, want.CellKinds, 6)
	assert.True(t, proto.Equal(want, build(t, prepared(t, legacy...))))
	assert.True(t, proto.Equal(want, build(t, prepared(t, mixed...))))
}

func TestPresence(t *testing.T) {
	rows := decode(t, build(t, prepared(t,
		&spb.HistoryItem{Key: "null", Value: &spb.HistoryItem_None{}},
		&spb.HistoryItem{Key: "false", Value: &spb.HistoryItem_Boolean{Boolean: false}},
		&spb.HistoryItem{Key: "zero", Value: &spb.HistoryItem_Integer{Integer: 0}},
		&spb.HistoryItem{Key: "empty", Value: &spb.HistoryItem_Text{Text: ""}},
	)))

	assert.Equal(t, []map[string]typedValue{{
		"null":  {filestreamv1.MetricsBatch_KIND_NULL, nil},
		"false": {filestreamv1.MetricsBatch_KIND_BOOL, false},
		"zero":  {filestreamv1.MetricsBatch_KIND_INT, int64(0)},
		"empty": {filestreamv1.MetricsBatch_KIND_STRING, ""},
	}}, rows)
}

func TestSteps(t *testing.T) {
	stepItem := func(step int64) *spb.HistoryItem {
		return &spb.HistoryItem{Key: "_step", Value: &spb.HistoryItem_Integer{Integer: step}}
	}
	batch := build(t,
		prepared(t, &spb.HistoryItem{Key: "a", ValueJson: "1"}),
		prepared(t, stepItem(-2)),
		prepared(t, stepItem(math.MaxInt64)),
		prepared(t, &spb.HistoryItem{Key: "_step", ValueJson: "3"}),
	)

	assert.Equal(t, []int64{0, -2, math.MaxInt64, 3}, batch.Seqs)
	assert.Equal(t, []bool{false, true, true, true}, batch.HasSeq)
	assert.Equal(t, []string{"a"}, batch.Keys)
	decode(t, batch)
}

func TestMalformedSteps(t *testing.T) {
	for _, text := range []string{`"secret"`, "null", "true", "1.5", "[1]", `{"child":1}`} {
		t.Run(text, func(t *testing.T) {
			row, err := Prepare(history(t,
				&spb.HistoryItem{Key: "_step", ValueJson: text},
				&spb.HistoryItem{Key: "a", ValueJson: "1"},
			))

			require.Error(t, err)
			assert.Len(t, joinedErrors(err), 1)
			assert.NotContains(t, err.Error(), "secret")
			assert.NotContains(t, err.Error(), "child")
			batch := build(t, row)
			assert.Equal(t, []bool{false}, batch.HasSeq)
			assert.Equal(t, []int64{0}, batch.Seqs)
			assert.Equal(t, []string{"a"}, batch.Keys)
			decode(t, batch)
		})
	}
}

func TestEmptyRows(t *testing.T) {
	batch := build(t,
		prepared(t, &spb.HistoryItem{Key: "a", ValueJson: "1"}),
		prepared(t),
		prepared(t, &spb.HistoryItem{Key: "_step", ValueJson: "5"}),
	)
	assert.Equal(t, []uint32{1, 1, 1}, batch.RowEnds)
	decode(t, batch)

	empty := NewBuilder().Finish()
	assert.Equal(t, seqKey, empty.SeqKey)
	assert.Empty(t, empty.RowEnds)
	assert.Empty(t, decode(t, empty))
}

func TestDictionary(t *testing.T) {
	b := NewBuilder()
	b.Append(prepared(t,
		&spb.HistoryItem{Key: "z", ValueJson: "1"},
		&spb.HistoryItem{Key: "m", ValueJson: `"s"`},
	))
	b.Append(prepared(t,
		&spb.HistoryItem{Key: "z", ValueJson: `"now a string"`},
		&spb.HistoryItem{Key: "b", ValueJson: "true"},
		&spb.HistoryItem{Key: "a", ValueJson: "1.5"},
	))
	assert.Equal(t, 2, b.Rows())
	batch := b.Finish()

	assert.Equal(t, []string{"m", "z", "a", "b"}, batch.Keys)
	assert.Equal(t, []uint32{0, 1, 2, 3, 1}, batch.CellKeys)
	assert.Equal(t, []filestreamv1.MetricsBatch_Kind{
		filestreamv1.MetricsBatch_KIND_STRING,
		filestreamv1.MetricsBatch_KIND_INT,
		filestreamv1.MetricsBatch_KIND_FLOAT,
		filestreamv1.MetricsBatch_KIND_BOOL,
		filestreamv1.MetricsBatch_KIND_STRING,
	}, batch.CellKinds)
	assert.Equal(t, []uint32{2, 5}, batch.RowEnds)
	decode(t, batch)
}

func TestNestedValues(t *testing.T) {
	rows := decode(t, build(t, prepared(t,
		&spb.HistoryItem{NestedKey: []string{"a", "b"}, ValueJson: "1.0"},
		&spb.HistoryItem{NestedKey: []string{"a", "_step"}, ValueJson: "7"},
		&spb.HistoryItem{Key: "a.b", ValueJson: "false"},
		&spb.HistoryItem{Key: "obj", ValueJson: `{"x":{"y":"z"}}`},
		&spb.HistoryItem{Key: "arr", Value: &spb.HistoryItem_Json{Json: `[1,{"k":null}]`}},
		&spb.HistoryItem{Key: "image", Value: &spb.HistoryItem_Json{
			Json: `{"_type":"image-file","path":"media/image.png","width":32}`}},
	)))
	require.Len(t, rows, 1)
	row := rows[0]

	json := filestreamv1.MetricsBatch_KIND_JSON
	assert.Equal(t, typedValue{json, map[string]any{"b": int64(1), "_step": int64(7)}}, row["a"])
	assert.Equal(t, typedValue{filestreamv1.MetricsBatch_KIND_BOOL, false}, row["a.b"])
	assert.Equal(t, typedValue{json, map[string]any{"x": map[string]any{"y": "z"}}}, row["obj"])
	assert.Equal(t, typedValue{json, []any{int64(1), map[string]any{"k": nil}}}, row["arr"])
	assert.Equal(t, typedValue{json, map[string]any{
		"_type": "image-file", "path": "media/image.png", "width": int64(32),
	}}, row["image"])
	assert.Len(t, row, 5)
	assert.NotContains(t, row, seqKey)
}

func TestInvalidUTF8(t *testing.T) {
	rh := history(t,
		&spb.HistoryItem{Key: "bad-key\xff", ValueJson: "1"},
		&spb.HistoryItem{Key: "text", Value: &spb.HistoryItem_Text{Text: "a\xff"}},
		&spb.HistoryItem{NestedKey: []string{"nested-key", "k\xfe"}, ValueJson: "1"},
		&spb.HistoryItem{
			NestedKey: []string{"nested-text", "k"},
			Value:     &spb.HistoryItem_Text{Text: "v\xfe"},
		},
		&spb.HistoryItem{Key: "good", ValueJson: "2"},
	)

	row, err := Prepare(rh)

	require.Error(t, err)
	assert.Len(t, joinedErrors(err), 4)
	for _, e := range joinedErrors(err) {
		assert.Equal(t, "metricsbatch: invalid UTF-8", e.Error())
	}
	batch := build(t, row)
	_, err = proto.Marshal(batch)
	require.NoError(t, err)
	assert.Equal(t, []map[string]typedValue{{
		"good": {filestreamv1.MetricsBatch_KIND_INT, int64(2)},
	}}, decode(t, batch))
}

func TestEmptyFirstLabel(t *testing.T) {
	items := []*spb.HistoryItem{
		{NestedKey: []string{""}, ValueJson: "1"},
		{NestedKey: []string{"", "b"}, ValueJson: "1"},
		{NestedKey: []string{"a", ""}, ValueJson: "2"},
		{Key: "c", ValueJson: "3"},
	}
	rh := runhistory.New()
	var errs []error
	for _, item := range items {
		errs = append(errs, rh.SetFromRecord(item))
	}

	assert.Error(t, errs[0])
	assert.Error(t, errs[1])
	assert.NoError(t, errs[2])
	assert.NoError(t, errs[3])
	row, err := Prepare(rh)
	require.NoError(t, err)
	assert.Equal(t, []map[string]typedValue{{
		"a": {filestreamv1.MetricsBatch_KIND_JSON, map[string]any{"": int64(2)}},
		"c": {filestreamv1.MetricsBatch_KIND_INT, int64(3)},
	}}, decode(t, build(t, row)))
}

func TestMalformedCells(t *testing.T) {
	rh := history(t, &spb.HistoryItem{Key: "good", ValueJson: "1"})
	rh.SetFloat(pathtree.PathOf(""), 1234567)
	rh.SetString(pathtree.PathOf("_step"), "private-value")

	row, err := Prepare(rh)

	errs := joinedErrors(err)
	require.Len(t, errs, 2)
	assert.Equal(t, "metricsbatch: empty key", errs[0].Error())
	assert.Equal(t, "metricsbatch: sequence must be int64", errs[1].Error())
	assert.NotContains(t, err.Error(), "1234567")
	assert.NotContains(t, err.Error(), "private-value")
	assert.Equal(t, []map[string]typedValue{{
		"good": {filestreamv1.MetricsBatch_KIND_INT, int64(1)},
	}}, decode(t, build(t, row)))
}

func TestUnsupportedTypes(t *testing.T) {
	cases := []struct {
		value any
		err   string
	}{
		{int(1234567), "metricsbatch: unsupported value type"},
		{struct{ Secret string }{"private-value"}, "metricsbatch: unsupported value type"},
		{
			map[string]any{"private-key": struct{ Secret string }{"private-value"}},
			"metricsbatch: JSON encoding failed",
		},
		{[]any{make(chan int)}, "metricsbatch: JSON encoding failed"},
	}
	for i, c := range cases {
		t.Run(fmt.Sprint(i), func(t *testing.T) {
			_, err := encodeCell("private-key", c.value)

			require.EqualError(t, err, c.err)
		})
	}

	// simplejsonext encodes these Go types inside a JSON cell.
	c, err := encodeCell("k", []any{int(1), uint(2), float32(0.5), errors.New("e")})
	require.NoError(t, err)
	assert.Equal(t, `[1,2,0.5,"e"]`, c.text)
}

func TestOwnership(t *testing.T) {
	rh := history(t,
		&spb.HistoryItem{Key: "arr", ValueJson: "[1,2]"},
		&spb.HistoryItem{Key: "obj", ValueJson: `{"x":1}`},
	)
	row, err := Prepare(rh)
	require.NoError(t, err)
	rh.ForEachTopLevel(func(_ string, value any) bool {
		if array, ok := value.([]any); ok {
			array[0] = "changed"
		}
		return true
	})
	rh.SetString(pathtree.PathOf("obj", "x"), "changed")
	rh.SetString(pathtree.PathOf("new"), "changed")

	first, second := NewBuilder(), NewBuilder()
	first.Append(row)
	second.Append(row)
	batch := first.Finish()
	assert.Equal(t, []string{"[1,2]", `{"x":1}`}, batch.Jsons)

	before := proto.Clone(batch)
	first.Append(prepared(t, &spb.HistoryItem{Key: "arr", ValueJson: "3"}))
	first.Finish()
	assert.True(t, proto.Equal(before, batch))
	assert.True(t, proto.Equal(batch, second.Finish()))
}

func TestWideRow(t *testing.T) {
	items := make([]*spb.HistoryItem, 10000)
	for i := range items {
		items[i] = &spb.HistoryItem{
			Key:   fmt.Sprintf("key-%05d", i),
			Value: &spb.HistoryItem_Integer{Integer: int64(i)},
		}
	}

	batch := build(t, prepared(t, items...))

	assert.Len(t, batch.Keys, 10000)
	assert.Equal(t, []uint32{10000}, batch.RowEnds)
	decode(t, batch)
}
