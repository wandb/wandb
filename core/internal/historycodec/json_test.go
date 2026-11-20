package historycodec_test

import (
	"math"
	"math/big"
	"reflect"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
)

func TestNormalizeFixtures(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			v, present := fixtureValue(t, f)
			if !present {
				return
			}
			normalized, err := historycodec.Normalize(v)
			require.NoError(t, err)
			want := parseJSON(t, []byte(f.json))
			assertValue(t, want, normalized, false)
			if f.kind == filestreamv1.MetricsBatch_KIND_JSON {
				encoded, err := simplejsonext.Marshal(normalized)
				require.NoError(t, err)
				assertValue(t, want, parseJSON(t, encoded), true)
			}
		})
	}
}

func TestMetricsBatchRoundTrip(t *testing.T) {
	batch := &filestreamv1.MetricsBatch{Keys: []string{"metric"}, SeqKey: "_step"}
	var included []fixture
	for _, f := range fixtures {
		v, present := fixtureValue(t, f)
		if !present {
			continue
		}
		kind, err := historycodec.Kind(v)
		require.NoError(t, err)
		require.Equal(t, f.kind, kind)
		batch.RowEnds = append(batch.RowEnds, uint32(len(batch.CellKinds)+1))
		batch.CellKeys = append(batch.CellKeys, 0)
		batch.CellKinds = append(batch.CellKinds, kind)
		packValue(t, batch, v)
		included = append(included, f)
	}

	raw, err := proto.Marshal(batch)
	require.NoError(t, err)
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(raw, decoded))
	require.Len(t, decoded.CellKinds, len(included))
	offsets := make(map[filestreamv1.MetricsBatch_Kind]int)
	for i, f := range included {
		assert.EqualValues(t, i+1, decoded.RowEnds[i])
		assert.Zero(t, decoded.CellKeys[i])
		kind := decoded.CellKinds[i]
		require.Equal(t, f.kind, kind)
		got := unpackValue(t, decoded, kind, offsets[kind])
		offsets[kind]++
		assertValue(t, parseJSON(t, []byte(f.json)), got,
			kind == filestreamv1.MetricsBatch_KIND_JSON)
	}
	assert.Len(t, decoded.Bools, offsets[filestreamv1.MetricsBatch_KIND_BOOL])
	assert.Len(t, decoded.Ints, offsets[filestreamv1.MetricsBatch_KIND_INT])
	assert.Len(t, decoded.Floats, offsets[filestreamv1.MetricsBatch_KIND_FLOAT])
	assert.Len(t, decoded.Strings, offsets[filestreamv1.MetricsBatch_KIND_STRING])
	assert.Len(t, decoded.Jsons, offsets[filestreamv1.MetricsBatch_KIND_JSON])
}

func packValue(t *testing.T, batch *filestreamv1.MetricsBatch, v any) {
	t.Helper()
	switch v := v.(type) {
	case nil:
	case bool:
		batch.Bools = append(batch.Bools, v)
	case int64:
		batch.Ints = append(batch.Ints, v)
	case float64:
		batch.Floats = append(batch.Floats, v)
	case string:
		batch.Strings = append(batch.Strings, historycodec.NormalizeString(v))
	case []any, map[string]any:
		normalized, err := historycodec.Normalize(v)
		require.NoError(t, err)
		encoded, err := simplejsonext.Marshal(normalized)
		require.NoError(t, err)
		batch.Jsons = append(batch.Jsons, string(encoded))
	default:
		t.Fatalf("unexpected type %T", v)
	}
}

func unpackValue(
	t *testing.T,
	b *filestreamv1.MetricsBatch,
	kind filestreamv1.MetricsBatch_Kind,
	offset int,
) any {
	t.Helper()
	switch kind {
	case filestreamv1.MetricsBatch_KIND_NULL:
		return nil
	case filestreamv1.MetricsBatch_KIND_BOOL:
		return b.Bools[offset]
	case filestreamv1.MetricsBatch_KIND_INT:
		return b.Ints[offset]
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		return b.Floats[offset]
	case filestreamv1.MetricsBatch_KIND_STRING:
		return b.Strings[offset]
	case filestreamv1.MetricsBatch_KIND_JSON:
		return parseJSON(t, []byte(b.Jsons[offset]))
	default:
		t.Fatalf("unexpected kind %v", kind)
		return nil
	}
}

func parseJSON(t *testing.T, b []byte) any {
	t.Helper()
	v, err := simplejsonext.Unmarshal(b)
	require.NoError(t, err)
	return v
}

func assertValue(t *testing.T, want, got any, jsonCell bool) {
	t.Helper()
	if jsonCell && assertJSONNumbers(t, want, got) {
		return
	}
	require.IsType(t, want, got)
	switch w := want.(type) {
	case float64:
		assertFloat(t, w, got.(float64))
	case []any:
		g := got.([]any)
		require.Len(t, g, len(w))
		for i := range w {
			assertValue(t, w[i], g[i], jsonCell)
		}
	case map[string]any:
		g := got.(map[string]any)
		require.Len(t, g, len(w))
		for key, v := range w {
			require.Contains(t, g, key)
			assertValue(t, v, g[key], jsonCell)
		}
	default:
		assert.Equal(t, want, got)
	}
}

func assertFloat(t *testing.T, want, got float64) {
	t.Helper()
	if math.IsNaN(want) {
		assert.True(t, math.IsNaN(got))
	} else {
		assert.Equal(t, math.Float64bits(want), math.Float64bits(got))
	}
}

func TestNestedValues(t *testing.T) {
	v := map[string]any{
		"b": 1.0,
		"a": []any{1.0, math.Copysign(0, -1), math.NaN(), map[string]any{
			"z":         int64(9007199254740993),
			"y":         "x\xff",
			"x\xff\xfe": math.Inf(-1),
		}},
		"c": map[string]any{},
	}
	want := `{"a":[1.0,-0.0,NaN,{"x��":-Infinity,"y":"x�","z":9007199254740993}],"b":1.0,"c":{}}`
	normalized, err := historycodec.Normalize(v)
	require.NoError(t, err)
	got, err := simplejsonext.Marshal(normalized)
	require.NoError(t, err)
	assertValue(t, parseJSON(t, []byte(want)), parseJSON(t, got), true)
}

func TestEmptyValues(t *testing.T) {
	cases := []struct {
		v    any
		json string
	}{
		{nil, "null"},
		{[]any(nil), "[]"},
		{[]any{}, "[]"},
		{map[string]any(nil), "{}"},
		{map[string]any{}, "{}"},
		{"", `""`},
	}
	for _, c := range cases {
		kind, err := historycodec.Kind(c.v)
		require.NoError(t, err)
		assert.NotEqual(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		normalized, err := historycodec.Normalize(c.v)
		require.NoError(t, err)
		got, err := simplejsonext.Marshal(normalized)
		require.NoError(t, err)
		assert.Equal(t, c.json, string(got))
	}
}

func TestNormalizeString(t *testing.T) {
	assert.Equal(t, "a��b", historycodec.NormalizeString("a\xff\xfeb"))
	assert.Equal(t, "", historycodec.NormalizeString(""))
	valid := "héllo 🌍 �"
	assert.Equal(t, valid, historycodec.NormalizeString(valid))
	assert.Zero(t, testing.AllocsPerRun(100, func() {
		_ = historycodec.NormalizeString(valid)
	}))
}

func jsonNumber(v any) *big.Rat {
	switch v := v.(type) {
	case int64:
		return new(big.Rat).SetInt64(v)
	case float64:
		return new(big.Rat).SetFloat64(v)
	default:
		return nil
	}
}

func assertJSONNumbers(t *testing.T, want, got any) bool {
	t.Helper()
	w, g := jsonNumber(want), jsonNumber(got)
	if w == nil || g == nil {
		return false
	}
	assert.Zero(t, w.Cmp(g), "different numeric values: %v and %v", want, got)
	return true
}

func TestNormalizeUnchanged(t *testing.T) {
	var v any = map[string]any{
		"array": []any{nil, true, int64(9007199254740993), 1.0, "héllo"},
		"map":   map[string]any{"nan": math.NaN(), "inf": math.Inf(1)},
	}
	got, err := historycodec.Normalize(v)
	require.NoError(t, err)
	assert.Equal(t, reflect.ValueOf(v).Pointer(), reflect.ValueOf(got).Pointer())
	assert.Zero(t, testing.AllocsPerRun(100, func() {
		_, err := historycodec.Normalize(v)
		if err != nil {
			panic(err)
		}
	}))

	slice := v.(map[string]any)["array"]
	got, err = historycodec.Normalize(slice)
	require.NoError(t, err)
	assert.Equal(t, reflect.ValueOf(slice).Pointer(), reflect.ValueOf(got).Pointer())
}

func TestNormalizeCopyOnWrite(t *testing.T) {
	unchanged := map[string]any{"valid": "héllo"}
	leaf := map[string]any{"bad\xff\xfe": "a\xff\xfeb", "untouched": unchanged}
	array := []any{leaf, unchanged}
	input := map[string]any{"array": array, "unchanged": unchanged}
	got, err := historycodec.Normalize(input)
	require.NoError(t, err)
	result := got.(map[string]any)
	repairedArray := result["array"].([]any)
	repairedLeaf := repairedArray[0].(map[string]any)
	assert.Equal(t, "a��b", repairedLeaf["bad��"])
	assert.NotContains(t, repairedLeaf, "bad\xff\xfe")

	assert.Equal(t, "a\xff\xfeb", leaf["bad\xff\xfe"])
	assert.NotContains(t, leaf, "bad��")
	assert.Equal(t, reflect.ValueOf(leaf).Pointer(), reflect.ValueOf(array[0]).Pointer())
	assert.Equal(t, reflect.ValueOf(array).Pointer(), reflect.ValueOf(input["array"]).Pointer())
	assert.NotEqual(t, reflect.ValueOf(input).Pointer(), reflect.ValueOf(result).Pointer())
	assert.NotEqual(t, reflect.ValueOf(array).Pointer(), reflect.ValueOf(repairedArray).Pointer())
	assert.NotEqual(t, reflect.ValueOf(leaf).Pointer(), reflect.ValueOf(repairedLeaf).Pointer())
	unchangedPointer := reflect.ValueOf(unchanged).Pointer()
	assert.Equal(t, unchangedPointer, reflect.ValueOf(result["unchanged"]).Pointer())
	assert.Equal(t, unchangedPointer, reflect.ValueOf(repairedArray[1]).Pointer())
	assert.Equal(t, unchangedPointer, reflect.ValueOf(repairedLeaf["untouched"]).Pointer())
}

func TestNormalizeKeyCollisions(t *testing.T) {
	input := map[string]any{
		"key\xfe": "first",
		"key�":    "valid",
		"key\xff": "last\xff",
	}
	for i := 0; i < 100; i++ {
		got, err := historycodec.Normalize(input)
		require.NoError(t, err)
		assert.Equal(t, map[string]any{"key�": "last�"}, got)
	}
	assert.Equal(t, "last\xff", input["key\xff"])
	assert.Len(t, input, 3)
}

func TestNormalizeKeysOnly(t *testing.T) {
	child := []any{"unchanged"}
	input := map[string]any{"bad\xff": child}
	got, err := historycodec.Normalize(input)
	require.NoError(t, err)
	result := got.(map[string]any)
	assert.Contains(t, result, "bad�")
	assert.Contains(t, input, "bad\xff")
	assert.NotEqual(t, reflect.ValueOf(input).Pointer(), reflect.ValueOf(result).Pointer())
	assert.Equal(t, reflect.ValueOf(child).Pointer(), reflect.ValueOf(result["bad�"]).Pointer())
}

func TestNormalizeJSONNumbers(t *testing.T) {
	v := []any{1.0, math.Copysign(0, -1), math.NaN()}
	normalized, err := historycodec.Normalize(v)
	require.NoError(t, err)
	got, err := simplejsonext.Marshal(normalized)
	require.NoError(t, err)
	assert.Equal(t, "[1,-0,NaN]", string(got))
	assertValue(t, v, parseJSON(t, got), true)
}
