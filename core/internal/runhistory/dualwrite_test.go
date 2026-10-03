package runhistory_test

import (
	"encoding/json"
	"math"
	"reflect"
	"testing"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type expectedMetric struct {
	path   []string
	kind   string
	typed  any
	legacy any
}

func metricKey(path []string) string {
	encoded, _ := json.Marshal(path)
	return string(encoded)
}

func decodedMetrics(history *runhistory.RunHistory) map[string]any {
	result := make(map[string]any)
	put := func(path pathtree.TreePath, value any) bool {
		result[metricKey(path.Labels())] = value
		return true
	}
	history.ForEach(
		func(path pathtree.TreePath, value float64) bool { return put(path, value) },
		func(path pathtree.TreePath, value int64) bool { return put(path, value) },
		put,
	)
	return result
}

func requireMetricValue(t *testing.T, want, got any) {
	t.Helper()
	require.Equal(t, reflect.TypeOf(want), reflect.TypeOf(got))
	switch want := want.(type) {
	case float64:
		actual := got.(float64)
		if math.IsNaN(want) {
			require.True(t, math.IsNaN(actual))
		} else {
			require.Equal(t, math.Float64bits(want), math.Float64bits(actual))
		}
	case []any:
		actual := got.([]any)
		require.Len(t, actual, len(want))
		for i := range want {
			requireMetricValue(t, want[i], actual[i])
		}
	case map[string]any:
		actual := got.(map[string]any)
		require.Len(t, actual, len(want))
		for key, value := range want {
			gotValue, exists := actual[key]
			require.True(t, exists, "missing object member %q", key)
			requireMetricValue(t, value, gotValue)
		}
	default:
		require.Equal(t, want, got)
	}
}

func requireHistoryValueKind(t *testing.T, item *spb.HistoryItem, wantKind string) {
	t.Helper()
	require.NotEmpty(t, item.ValueJson)
	require.NotNil(t, item.Value)

	switch item.Value.(type) {
	case *spb.HistoryItem_None:
		require.Equal(t, "none", wantKind)
	case *spb.HistoryItem_Boolean:
		require.Equal(t, "boolean", wantKind)
	case *spb.HistoryItem_Integer:
		require.Equal(t, "integer", wantKind)
	case *spb.HistoryItem_Number:
		require.Equal(t, "number", wantKind)
	case *spb.HistoryItem_Text:
		require.Equal(t, "text", wantKind)
	case *spb.HistoryItem_Json:
		require.Equal(t, "json", wantKind)
		require.Equal(t, item.ValueJson, item.GetJson())
	default:
		t.Fatalf("unexpected value alternative %T", item.Value)
	}
}

func requireDualWriteRow(t *testing.T, source *runhistory.RunHistory, expected []expectedMetric) {
	t.Helper()
	items, err := source.ToRecords(true, true)
	require.NoError(t, err)
	require.Len(t, items, len(expected))

	// Create a map of the expected metrics by path.
	wants := make(map[string]expectedMetric)
	for _, metric := range expected {
		wants[metricKey(metric.path)] = metric
	}

	// Round-trip the records through the codec.
	record := &spb.HistoryRecord{Item: items}
	data, err := proto.Marshal(record)
	require.NoError(t, err)
	decoded := new(spb.HistoryRecord)
	require.NoError(t, proto.Unmarshal(data, decoded))

	// Decode the records into two separate runhistories,
	// one for the typed values and one for the legacy values.
	typedRow := runhistory.New()
	legacyRow := runhistory.New()
	seen := make(map[string]bool)
	for _, item := range decoded.Item {
		key := metricKey(item.NestedKey)
		want, exists := wants[key]
		require.True(t, exists, "unexpected path %s", key)
		require.False(t, seen[key], "duplicate path %s", key)
		seen[key] = true
		requireHistoryValueKind(t, item, want.kind)
		typedItem := proto.Clone(item).(*spb.HistoryItem)
		typedItem.ValueJson = ""
		require.NoError(t, typedRow.SetFromRecord(typedItem))
		legacyItem := proto.Clone(item).(*spb.HistoryItem)
		legacyItem.Value = nil
		require.NoError(t, legacyRow.SetFromRecord(legacyItem))
	}
	require.Len(t, seen, len(wants))

	// Verify that the decoded values for each runhistory (typed and legacy)
	// are equivalent to the original values.
	for _, row := range []struct {
		name   string
		values map[string]any
		typed  bool
	}{
		{"typed", decodedMetrics(typedRow), true},
		{"legacy", decodedMetrics(legacyRow), false},
	} {
		t.Run(row.name, func(t *testing.T) {
			require.Len(t, row.values, len(wants))
			for key, want := range wants {
				got, exists := row.values[key]
				require.True(t, exists, "missing path %s", key)
				if row.typed {
					requireMetricValue(t, want.typed, got)
				} else {
					requireMetricValue(t, want.legacy, got)
				}
			}
		})
	}
}

func TestDualWriteIndependentDecoding(t *testing.T) {
	rh := runhistory.New()
	metrics := []expectedMetric{
		// Cases where the typed and json values differ.
		{[]string{"integral_float"}, "number", 1.0, int64(1)},
		{[]string{"positive_zero"}, "number", 0.0, int64(0)},
		{[]string{"negative_zero"}, "number", math.Copysign(0, -1), int64(0)},

		// Cases where the typed and json values are the same.
		{[]string{"zero_int"}, "integer", int64(0), int64(0)},
		{[]string{"negative_int"}, "integer", int64(-7), int64(-7)},
		{[]string{"wide_int"}, "integer", int64(1<<53 + 1), int64(1<<53 + 1)},
		{[]string{"min_int"}, "integer", int64(math.MinInt64), int64(math.MinInt64)},
		{[]string{"max_int"}, "integer", int64(math.MaxInt64), int64(math.MaxInt64)},
		{[]string{"fraction"}, "number", 1.25, 1.25},
		{[]string{"small_float"}, "number", math.SmallestNonzeroFloat64,
			math.SmallestNonzeroFloat64},
		{[]string{"large_float"}, "number", math.MaxFloat64, math.MaxFloat64},
		{[]string{"nan"}, "number", math.NaN(), math.NaN()},
		{[]string{"positive_inf"}, "number", math.Inf(1), math.Inf(1)},
		{[]string{"negative_inf"}, "number", math.Inf(-1), math.Inf(-1)},
		{[]string{"empty_text"}, "text", "", ""},
		{[]string{"unicode_text"}, "text", "café \"\\\n", "café \"\\\n"},
		{[]string{"nested", "value"}, "integer", int64(4), int64(4)},
		{[]string{"nested.value"}, "integer", int64(5), int64(5)},
		{[]string{"null"}, "none", nil, nil},
		{[]string{"true"}, "boolean", true, true},
		{[]string{"false"}, "boolean", false, false},
		{[]string{"empty_array"}, "json", []any{}, []any{}},
		{[]string{"array"}, "json",
			[]any{
				int64(1),
				map[string]any{"big": int64(1<<53 + 1), "nan": math.NaN()},
				nil,
				math.Inf(-1),
			},
			[]any{
				int64(1),
				map[string]any{"big": int64(1<<53 + 1), "nan": math.NaN()},
				nil,
				math.Inf(-1),
			},
		},
	}
	for _, metric := range metrics {
		path := pathtree.PathOf(metric.path[0], metric.path[1:]...)
		switch value := metric.typed.(type) {
		case int64:
			rh.SetInt(path, value)
		case float64:
			rh.SetFloat(path, value)
		case string:
			rh.SetString(path, value)
		}
	}
	for _, input := range []*spb.HistoryItem{
		{Key: "null", ValueJson: "null"},
		{Key: "true", ValueJson: "true"},
		{Key: "false", ValueJson: "false"},
		{Key: "array", ValueJson: `[1,{"big":9007199254740993,"nan":NaN},null,-Infinity]`},
		{Key: "empty_array", ValueJson: `[]`},
		{Key: "empty_object", ValueJson: `{}`},
	} {
		require.NoError(t, rh.SetFromRecord(input))
	}
	requireDualWriteRow(t, rh, metrics)
}

func TestDualWriteSparseRows(t *testing.T) {
	rows := []struct {
		items []*spb.HistoryItem
		want  []expectedMetric
	}{
		{
			[]*spb.HistoryItem{
				{Key: "a", ValueJson: "1"},
				{Key: "b", ValueJson: "null"},
			},
			[]expectedMetric{
				{[]string{"a"}, "integer", int64(1), int64(1)},
				{[]string{"b"}, "none", nil, nil},
			},
		},
		{
			[]*spb.HistoryItem{
				{Key: "b", ValueJson: "false"},
				{Key: "c", ValueJson: `""`},
			},
			[]expectedMetric{
				{[]string{"b"}, "boolean", false, false},
				{[]string{"c"}, "text", "", ""},
			},
		},
		{
			[]*spb.HistoryItem{{Key: "a", ValueJson: "0"}},
			[]expectedMetric{{[]string{"a"}, "integer", int64(0), int64(0)}},
		},
		{nil, nil},
	}
	for _, test := range rows {
		rh := runhistory.New()
		for _, item := range test.items {
			require.NoError(t, rh.SetFromRecord(item))
		}
		requireDualWriteRow(t, rh, test.want)
	}
}

func TestDualWriteIntegralFloatRenderer(t *testing.T) {
	rh := runhistory.New()
	rh.SetFloat(pathtree.PathOf("metric"), 1.0)
	requireDualWriteRow(t, rh, []expectedMetric{{[]string{"metric"}, "number", 1.0, int64(1)}})
	items, err := rh.ToRecords(true, true)
	require.NoError(t, err)
	require.Equal(t, "1", items[0].ValueJson)
	line, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	require.Equal(t, `{"metric":1}`, string(line))
}

func TestDualWriteNegativeZeroLosesLegacySign(t *testing.T) {
	rh := runhistory.New()
	rh.SetFloat(pathtree.PathOf("metric"), math.Copysign(0, -1))
	requireDualWriteRow(t, rh, []expectedMetric{{
		[]string{"metric"}, "number", math.Copysign(0, -1), int64(0),
	}})
	items, err := rh.ToRecords(true, true)
	require.NoError(t, err)
	require.Equal(t, "-0", items[0].ValueJson)
}
