package historycodec_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/proto"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
)

func TestAppendJSON(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			v, present := fixtureValue(t, f)
			if !present {
				return
			}
			encoded, err := historycodec.AppendJSON([]byte("prefix:"), v)
			require.NoError(t, err)
			assert.Equal(t, "prefix:"+f.json, string(encoded))
			got := parseJSON(t, encoded[len("prefix:"):])
			assertValue(t, parseJSON(t, []byte(f.json)), got)
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
		assertValue(t, parseJSON(t, []byte(f.json)), got)
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
		encoded, err := historycodec.AppendJSON(nil, v)
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

func assertValue(t *testing.T, want, got any) {
	t.Helper()
	require.IsType(t, want, got)
	switch w := want.(type) {
	case float64:
		assertFloat(t, w, got.(float64))
	case []any:
		g := got.([]any)
		require.Len(t, g, len(w))
		for i := range w {
			assertValue(t, w[i], g[i])
		}
	case map[string]any:
		g := got.(map[string]any)
		require.Len(t, g, len(w))
		for key, v := range w {
			require.Contains(t, g, key)
			assertValue(t, v, g[key])
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
	got, err := historycodec.AppendJSON(nil, v)
	require.NoError(t, err)
	assert.Equal(t, want, string(got))
	assertValue(t, parseJSON(t, []byte(want)), parseJSON(t, got))
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
		got, err := historycodec.AppendJSON(nil, c.v)
		require.NoError(t, err)
		assert.Equal(t, c.json, string(got))
	}
}

func TestAppendKey(t *testing.T) {
	for _, s := range []string{
		"", "héllo 🌍", "a\xff\xfeb", "\"\\/\b\f\n\r\t\x00\x01\x1f",
		"<>&\u2028\u2029", "�",
	} {
		want, err := simplejsonext.Marshal(historycodec.NormalizeString(s))
		require.NoError(t, err)
		got := historycodec.AppendKey([]byte("prefix:"), s)
		assert.Equal(t, "prefix:"+string(want), string(got))
		encoded, err := historycodec.AppendJSON(nil, s)
		require.NoError(t, err)
		assert.Equal(t, string(want), string(encoded))
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

func TestAppendJSONReusesBuffer(t *testing.T) {
	dst := make([]byte, 0, 1024)
	var v any = []any{1.0, int64(9007199254740993), "valid", true, nil}
	assert.Zero(t, testing.AllocsPerRun(100, func() {
		_, err := historycodec.AppendJSON(dst, v)
		if err != nil {
			panic(err)
		}
	}))
}
