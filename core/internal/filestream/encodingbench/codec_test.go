package encodingbench

import (
	"encoding/base64"
	"encoding/json"
	"math"
	"testing"

	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/filestream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/proto"
)

func TestEnvelopeCodecRoundTrips(t *testing.T) {
	for _, workload := range SyntheticWorkloads() {
		fixtures, err := recordFixtures(workload.Rows)
		require.NoError(t, err)
		for _, fixture := range fixtures {
			for _, codec := range benchmarkCodecs() {
				t.Run(workload.Name+"/"+string(fixture.Mode)+"/"+codec.Name(), func(t *testing.T) {
					encoded, err := codec.Encode(fixture.Records)
					require.NoError(t, err)
					require.NotEmpty(t, encoded.Data)
					require.Positive(t, encoded.BodyBytes)

					decoded, err := codec.Decode(encoded.Data, fixture.Mode)
					require.NoError(t, err)
					requireRecordsSemanticallyEqual(t, fixture.Records, decoded)
					requireRecordMode(t, decoded, fixture.Mode)
				})
			}
		}
	}
}

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
	records, err := recordsFromRows([]Row{{Cells: []Cell{{Key: "x", Value: Value{Kind: KindNumber, Number: 1}}}}, {Cells: []Cell{{Key: "x", Value: Value{Kind: KindNumber, Number: 2}}}}}, TypedValue)
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

func TestNestedKeysSurviveProtobufTransports(t *testing.T) {
	records := []*spb.HistoryRecord{{Item: []*spb.HistoryItem{{
		NestedKey: []string{"model", "loss"},
		Value:     &spb.HistoryValue{Kind: spb.HistoryValue_KIND_NUMBER, NumberValue: 0.25},
	}}}}
	for _, codec := range []EnvelopeCodec{
		JSONRowProtoEnvelopeCodec{},
		ProtoRowEnvelopeCodec{},
		JSONColumnProtoEnvelopeCodec{},
		ProtoColumnEnvelopeCodec{},
	} {
		encoded, err := codec.Encode(records)
		require.NoError(t, err)
		decoded, err := codec.Decode(encoded.Data, TypedValue)
		require.NoError(t, err)
		require.Equal(t, []string{"model", "loss"}, decoded[0].Item[0].NestedKey)
		require.Empty(t, decoded[0].Item[0].Key)
	}
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

func TestJSONProtoCodecsRejectInvalidBase64(t *testing.T) {
	data, err := marshalJSONEnvelope([]string{"%%%"})
	require.NoError(t, err)
	_, err = (JSONRowProtoEnvelopeCodec{}).Decode(data, TypedValue)
	require.ErrorContains(t, err, "base64")
	_, err = (JSONColumnProtoEnvelopeCodec{}).Decode(data, TypedValue)
	require.ErrorContains(t, err, "base64")
}

func TestJSONRowProtoRejectsTruncatedRecord(t *testing.T) {
	data, err := marshalJSONEnvelope([]string{base64.StdEncoding.EncodeToString([]byte{0xff})})
	require.NoError(t, err)
	_, err = (JSONRowProtoEnvelopeCodec{}).Decode(data, TypedValue)
	require.ErrorContains(t, err, "unmarshal row")
}

func TestJSONColumnProtoRejectsTruncatedBatch(t *testing.T) {
	data, err := marshalJSONEnvelope([]string{base64.StdEncoding.EncodeToString([]byte{0xff})})
	require.NoError(t, err)
	_, err = (JSONColumnProtoEnvelopeCodec{}).Decode(data, TypedValue)
	require.ErrorContains(t, err, "unmarshal columnar batch")
}

func TestProtoEnvelopeRejectsMissingContent(t *testing.T) {
	data, err := proto.Marshal(&BenchmarkFileStreamRequest{FileName: historyFileName})
	require.NoError(t, err)
	_, err = (ProtoRowEnvelopeCodec{}).Decode(data, TypedValue)
	require.ErrorContains(t, err, "missing history content")
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
	records := []*spb.HistoryRecord{{Item: []*spb.HistoryItem{{Key: "metric", ValueJson: "not JSON"}}}}
	_, err := (ProtoColumnEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "decode value_json")
	_, err = (LegacyJSONEnvelopeCodec{}).Encode(records)
	require.ErrorContains(t, err, "decode value_json")
}

func TestColumnProtoRejectsInvalidIndexes(t *testing.T) {
	batch := &ColumnarHistoryBatch{
		RowCount:    1,
		Keys:        []*HistoryKey{{Key: "metric"}},
		RowIndex:    []uint32{0},
		KeyIndex:    []uint32{42},
		Kind:        []ColumnarHistoryBatch_Kind{ColumnarHistoryBatch_KIND_NUMBER},
		ValueIndex:  []uint32{0},
		NumberValue: []float64{1},
	}
	_, err := recordsFromColumnarBatch(batch, TypedValue)
	require.ErrorContains(t, err, "key index")
}

func TestColumnProtoRejectsInvalidJSON(t *testing.T) {
	batch := &ColumnarHistoryBatch{
		RowCount:   1,
		Keys:       []*HistoryKey{{Key: "metric"}},
		RowIndex:   []uint32{0},
		KeyIndex:   []uint32{0},
		Kind:       []ColumnarHistoryBatch_Kind{ColumnarHistoryBatch_KIND_JSON},
		ValueIndex: []uint32{0},
		JsonValue:  [][]byte{[]byte("not JSON")},
	}
	_, err := recordsFromColumnarBatch(batch, TypedValue)
	require.ErrorContains(t, err, "invalid JSON")
}

func requireRecordsSemanticallyEqual(t *testing.T, expected, actual []*spb.HistoryRecord) {
	t.Helper()
	expectedRows, err := rowsFromRecords(expected)
	require.NoError(t, err)
	actualRows, err := rowsFromRecords(actual)
	require.NoError(t, err)
	requireRowsEqual(t, expectedRows, actualRows)
}

func requireRecordMode(t *testing.T, records []*spb.HistoryRecord, mode ValueMode) {
	t.Helper()
	for _, record := range records {
		for _, item := range record.Item {
			switch mode {
			case JSONValue:
				require.Nil(t, item.Value)
				require.NotEmpty(t, item.ValueJson)
			case TypedValue:
				require.NotNil(t, item.Value)
				require.Empty(t, item.ValueJson)
			}
		}
	}
}

func requireRowsEqual(t *testing.T, expected, actual []Row) {
	t.Helper()
	expected, err := normalizedRows(expected)
	require.NoError(t, err)
	actual, err = normalizedRows(actual)
	require.NoError(t, err)
	require.Len(t, actual, len(expected))
	for rowIndex := range expected {
		require.Len(t, actual[rowIndex].Cells, len(expected[rowIndex].Cells))
		for cellIndex := range expected[rowIndex].Cells {
			expectedCell := expected[rowIndex].Cells[cellIndex]
			actualCell := actual[rowIndex].Cells[cellIndex]
			require.Equal(t, expectedCell.Key, actualCell.Key)
			require.Equal(t, expectedCell.NestedKey, actualCell.NestedKey)
			require.Truef(
				t,
				valuesEqual(expectedCell.Value, actualCell.Value),
				"row %d key %q values differ: %#v != %#v",
				rowIndex,
				expectedCell.Key,
				expectedCell.Value,
				actualCell.Value,
			)
		}
	}
}
