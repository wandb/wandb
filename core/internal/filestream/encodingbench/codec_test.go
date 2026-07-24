package encodingbench

import (
	"encoding/json"
	"math"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/filestream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestHistoryValueConversions(t *testing.T) {
	values := []Value{
		{Kind: KindNull},
		{Kind: KindBool, Bool: true},
		{Kind: KindNumber, Number: 42.5},
		{Kind: KindNumber, Number: math.NaN()},
		{Kind: KindNumber, Number: math.Inf(1)},
		{Kind: KindNumber, Number: math.Inf(-1)},
		{Kind: KindString, String: "snowman ☃ 日本語"},
		{Kind: KindJSON, JSON: []byte(`[1,true,"x"]`)},
		{Kind: KindJSON, JSON: []byte(`{"nested":{"value":1}}`)},
	}
	for _, mode := range []ValueMode{JSONValue, TypedValue} {
		for _, value := range values {
			item, err := itemFromValue("metric", nil, value, mode)
			require.NoError(t, err)
			actual, err := valueFromItem(item)
			require.NoError(t, err)
			require.Truef(t, valuesEqual(value, actual), "%v != %v", value, actual)
		}
	}
}

func TestTypedValueTakesPrecedence(t *testing.T) {
	item := &spb.HistoryItem{
		Key:       "metric",
		ValueJson: "not JSON",
		Value: &spb.HistoryValue{
			Kind:        spb.HistoryValue_KIND_STRING,
			StringValue: "typed",
		},
	}
	value, err := valueFromItem(item)
	require.NoError(t, err)
	require.Equal(t, Value{Kind: KindString, String: "typed"}, value)
}

func TestInvalidTypedValueFallsBackToValueJSON(t *testing.T) {
	item := &spb.HistoryItem{
		Key:       "metric",
		ValueJson: "42.5",
		Value:     &spb.HistoryValue{},
	}
	value, err := valueFromItem(item)
	require.NoError(t, err)
	require.Equal(t, Value{Kind: KindNumber, Number: 42.5}, value)
}

func TestJSONEnvelopeWireShape(t *testing.T) {
	content := []string{`{"x":1}`}
	encoded, err := marshalJSONEnvelope(content)
	require.NoError(t, err)
	require.JSONEq(t,
		`{"files":{"wandb-history.jsonl":{"offset":0,"content":["{\"x\":1}"]}}}`,
		string(encoded),
	)

	state := &filestream.FileStreamState{MaxRequestSizeBytes: 1 << 20}
	production, hasMore := state.Pop(
		&filestream.FileStreamRequest{HistoryLines: content},
		nil,
		nil,
	)
	require.False(t, hasMore)
	productionJSON, err := json.Marshal(production)
	require.NoError(t, err)
	require.JSONEq(t, string(productionJSON), string(encoded))
}

func TestJSONEnvelopeContentFraming(t *testing.T) {
	records, err := recordsFromRows(
		[]Row{
			{Cells: []Cell{{Key: "x", Value: Value{Kind: KindNumber, Number: 1}}}},
			{Cells: []Cell{{Key: "x", Value: Value{Kind: KindNumber, Number: 2}}}},
		},
		TypedValue,
	)
	require.NoError(t, err)
	rowEncoded, err := (JSONRowProtoEnvelopeCodec{}).Encode(records)
	require.NoError(t, err)
	rowContent, err := unmarshalJSONEnvelope(rowEncoded.Data)
	require.NoError(t, err)
	require.Len(t, rowContent, len(records))

	columnEncoded, err := (JSONColumnProtoEnvelopeCodec{}).Encode(records)
	require.NoError(t, err)
	columnContent, err := unmarshalJSONEnvelope(columnEncoded.Data)
	require.NoError(t, err)
	require.Len(t, columnContent, 1)
}

func TestLegacyNestedKeySemantics(t *testing.T) {
	record := &spb.HistoryRecord{Item: []*spb.HistoryItem{{
		NestedKey: []string{"model", "loss"},
		ValueJson: "0.25",
	}}}
	line, err := recordToExtendedJSON(record)
	require.NoError(t, err)
	require.JSONEq(t, `{"model":{"loss":0.25}}`, string(line))
}

func TestCodecsRejectInvalidTypedKind(t *testing.T) {
	records := []*spb.HistoryRecord{{Item: []*spb.HistoryItem{{
		Key:   "metric",
		Value: &spb.HistoryValue{},
	}}}}
	_, err := (ProtoColumnEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "unknown typed value kind")
	_, err = (LegacyJSONEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "unknown typed value kind")
}

func TestCodecsRejectMalformedValueJSON(t *testing.T) {
	records := []*spb.HistoryRecord{
		{Item: []*spb.HistoryItem{{Key: "metric", ValueJson: "not JSON"}}},
	}
	_, err := (ProtoColumnEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "decode value_json")
	_, err = (LegacyJSONEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "decode value_json")
}
