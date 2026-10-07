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

type wantedMetric struct {
	path  []string
	kind  string
	typed any
	json  any
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

func requireHistoryRecordMetrics(
	t *testing.T,
	gotItems []*spb.HistoryItem,
	wantKinds map[string]string,
) {
	t.Helper()
	seen := make(map[string]bool)
	for _, item := range gotItems {
		key := metricKey(item.NestedKey)
		wantKind, exists := wantKinds[key]
		require.True(t, exists, "unexpected path %s", key)
		require.False(t, seen[key], "duplicate path %s", key)
		seen[key] = true
		requireHistoryValueKind(t, item, wantKind)
	}
	require.Len(t, seen, len(wantKinds))
}

func requireMetricsEqual(t *testing.T, got, want map[string]any) {
	t.Helper()
	require.Len(t, got, len(want))
	for key, wantValue := range want {
		gotValue, exists := got[key]
		require.True(t, exists, "missing path %s", key)
		requireMetricValue(t, wantValue, gotValue)
	}
}

func requireRoundTrip(t *testing.T, source *runhistory.RunHistory) *spb.HistoryRecord {
	t.Helper()
	items, err := source.ToRecords(true, true)
	require.NoError(t, err)
	record := &spb.HistoryRecord{Item: items}
	data, err := proto.Marshal(record)
	require.NoError(t, err)
	decoded := new(spb.HistoryRecord)
	require.NoError(t, proto.Unmarshal(data, decoded))
	return decoded
}

func decodeToTyped(t *testing.T, record *spb.HistoryRecord) *runhistory.RunHistory {
	t.Helper()
	seen := make(map[string]bool)
	typedRow := runhistory.New()
	for _, item := range record.Item {
		key := metricKey(item.NestedKey)
		require.False(t, seen[key], "duplicate path %s", key)
		seen[key] = true
		typedItem := proto.Clone(item).(*spb.HistoryItem)
		typedItem.ValueJson = ""
		require.NoError(t, typedRow.SetFromRecord(typedItem))
	}
	return typedRow
}

func decodeToJson(t *testing.T, record *spb.HistoryRecord) *runhistory.RunHistory {
	t.Helper()
	seen := make(map[string]bool)
	jsonRow := runhistory.New()
	for _, item := range record.Item {
		key := metricKey(item.NestedKey)
		require.False(t, seen[key], "duplicate path %s", key)
		seen[key] = true
		jsonItem := proto.Clone(item).(*spb.HistoryItem)
		jsonItem.Value = nil
		require.NoError(t, jsonRow.SetFromRecord(jsonItem))
	}
	return jsonRow
}

func requireTypedAndJsonEqual(t *testing.T, got *runhistory.RunHistory, want []wantedMetric) {
	t.Helper()

	wantKinds := make(map[string]string)
	wantJson := make(map[string]any)
	wantTyped := make(map[string]any)
	for _, metric := range want {
		wantKinds[metricKey(metric.path)] = metric.kind
		wantJson[metricKey(metric.path)] = metric.json
		wantTyped[metricKey(metric.path)] = metric.typed
	}

	dualHistoryRecord := requireRoundTrip(t, got)
	require.Len(t, dualHistoryRecord.Item, len(want))
	requireHistoryRecordMetrics(t, dualHistoryRecord.Item, wantKinds)

	typedRunHistory := decodeToTyped(t, dualHistoryRecord)
	typedMetrics := decodedMetrics(typedRunHistory)
	requireMetricsEqual(t, typedMetrics, wantTyped)

	jsonRunHistory := decodeToJson(t, dualHistoryRecord)
	jsonMetrics := decodedMetrics(jsonRunHistory)
	requireMetricsEqual(t, jsonMetrics, wantJson)
}

func TestTypedAndJsonDecoding(t *testing.T) {
	rh := runhistory.New()
	metrics := []wantedMetric{
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
	requireTypedAndJsonEqual(t, rh, metrics)
}

func TestTypedAndJsonSparseRows(t *testing.T) {
	rows := []struct {
		items []*spb.HistoryItem
		want  []wantedMetric
	}{
		{
			[]*spb.HistoryItem{
				{Key: "a", ValueJson: "1"},
				{Key: "b", ValueJson: "null"},
			},
			[]wantedMetric{
				{[]string{"a"}, "integer", int64(1), int64(1)},
				{[]string{"b"}, "none", nil, nil},
			},
		},
		{
			[]*spb.HistoryItem{
				{Key: "b", ValueJson: "false"},
				{Key: "c", ValueJson: `""`},
			},
			[]wantedMetric{
				{[]string{"b"}, "boolean", false, false},
				{[]string{"c"}, "text", "", ""},
			},
		},
		{
			[]*spb.HistoryItem{{Key: "a", ValueJson: "0"}},
			[]wantedMetric{{[]string{"a"}, "integer", int64(0), int64(0)}},
		},
		{nil, nil},
	}
	for _, test := range rows {
		rh := runhistory.New()
		for _, item := range test.items {
			require.NoError(t, rh.SetFromRecord(item))
		}
		requireTypedAndJsonEqual(t, rh, test.want)
	}
}

func TestTypedAndJsonIntFloatDifferences(t *testing.T) {
	rh := runhistory.New()
	rh.SetFloat(pathtree.PathOf("metric"), 1.0)
	requireTypedAndJsonEqual(t, rh, []wantedMetric{{[]string{"metric"}, "number", 1.0, int64(1)}})
	items, err := rh.ToRecords(true, true)
	require.NoError(t, err)
	require.Equal(t, "1", items[0].ValueJson)
	line, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	require.Equal(t, `{"metric":1}`, string(line))
}

func TestTypedAndJsonNegativeZero(t *testing.T) {
	rh := runhistory.New()
	rh.SetFloat(pathtree.PathOf("metric"), math.Copysign(0, -1))
	requireTypedAndJsonEqual(t, rh, []wantedMetric{{
		[]string{"metric"}, "number", math.Copysign(0, -1), int64(0),
	}})
	items, err := rh.ToRecords(true, true)
	require.NoError(t, err)
	require.Equal(t, "-0", items[0].ValueJson)
}
