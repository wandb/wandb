package historycodec_test

import (
	"math"
	"testing"
	"unicode/utf8"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/structpb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestToExtendedJSON(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			encoded, err := historycodec.ToExtendedJSON(f.item)
			require.NoError(t, err)
			assert.Equal(t, f.json, string(encoded))
		})
	}
}

// TestRoundTrip serializes each fixture through the log wire format,
// converts the decoded item to extended JSON, and reconstructs a value
// from the parsed scalar and expected wire kind. It requires the
// normalized value after the trip.
func TestRoundTrip(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			source := f.item
			text, isText := source.Value.(*spb.HistoryItem_Text)
			if isText && !utf8.ValidString(text.Text) {
				// Protobuf string fields reject invalid UTF-8 on the log wire.
				encoded, err := historycodec.ToExtendedJSON(source)
				require.NoError(t, err)
				source = reconstruct(t, f, encoded)
			}
			raw, err := proto.Marshal(source)
			require.NoError(t, err)
			item := &spb.HistoryItem{}
			require.NoError(t, proto.Unmarshal(raw, item))

			kind, err := historycodec.WireKind(item)
			require.NoError(t, err)
			assert.Equal(t, f.kind, kind)

			encoded, err := historycodec.ToExtendedJSON(item)
			require.NoError(t, err)
			assert.Equal(t, f.json, string(encoded))

			assertSameValue(t, reconstruct(t, f, []byte(f.json)), reconstruct(t, f, encoded))
		})
	}
}

// TestMetricsBatchRoundTrip packs the fixture values into a minimal
// valid MetricsBatch, one row each, and requires every cell of the
// decoded batch to carry the expected normalized value.
func TestMetricsBatchRoundTrip(t *testing.T) {
	batch := &filestreamv1.MetricsBatch{
		Keys:   []string{"metric"},
		SeqKey: "_step",
	}
	for _, f := range fixtures {
		batch.RowEnds = append(batch.RowEnds, uint32(len(batch.CellKinds)+1))
		batch.CellKeys = append(batch.CellKeys, 0)
		kind, err := historycodec.WireKind(f.item)
		require.NoError(t, err)
		require.Equal(t, f.kind, kind)
		batch.CellKinds = append(batch.CellKinds, kind)
		encoded, err := historycodec.ToExtendedJSON(f.item)
		require.NoError(t, err)
		converted := reconstruct(t, f, encoded)

		switch v := converted.Value.(type) {
		case *spb.HistoryItem_None:
			// KIND_NULL cells have no payload.
		case *spb.HistoryItem_Boolean:
			batch.Bools = append(batch.Bools, v.Boolean)
		case *spb.HistoryItem_Integer:
			batch.Ints = append(batch.Ints, v.Integer)
		case *spb.HistoryItem_Number:
			batch.Floats = append(batch.Floats, v.Number)
		case *spb.HistoryItem_Text:
			batch.Strings = append(batch.Strings, v.Text)
		case *spb.HistoryItem_Json:
			batch.Jsons = append(batch.Jsons, v.Json)
		default:
			t.Fatalf("fixture %q has unhandled alternative %T",
				f.name, f.item.Value)
		}
	}

	raw, err := proto.Marshal(batch)
	require.NoError(t, err)
	decoded := &filestreamv1.MetricsBatch{}
	require.NoError(t, proto.Unmarshal(raw, decoded))

	// Cells of one kind take payloads from that kind's array in order.
	var floats, ints, bools, strs, jsons int
	require.Len(t, decoded.CellKinds, len(fixtures))
	for c, f := range fixtures {
		assert.EqualValues(t, c+1, decoded.RowEnds[c])
		assert.Zero(t, decoded.CellKeys[c])
		require.Equal(t, f.kind, decoded.CellKinds[c],
			"cell %d kind", c)

		got := &spb.HistoryItem{}
		switch f.kind {
		case filestreamv1.MetricsBatch_KIND_NULL:
			got.Value = &spb.HistoryItem_None{
				None: structpb.NullValue_NULL_VALUE}
		case filestreamv1.MetricsBatch_KIND_BOOL:
			got.Value = &spb.HistoryItem_Boolean{
				Boolean: decoded.Bools[bools]}
			bools++
		case filestreamv1.MetricsBatch_KIND_INT:
			got.Value = &spb.HistoryItem_Integer{
				Integer: decoded.Ints[ints]}
			ints++
		case filestreamv1.MetricsBatch_KIND_FLOAT:
			got.Value = &spb.HistoryItem_Number{
				Number: decoded.Floats[floats]}
			floats++
		case filestreamv1.MetricsBatch_KIND_STRING:
			got.Value = &spb.HistoryItem_Text{
				Text: decoded.Strings[strs]}
			strs++
		case filestreamv1.MetricsBatch_KIND_JSON:
			got.Value = &spb.HistoryItem_Json{
				Json: decoded.Jsons[jsons]}
			jsons++
		default:
			t.Fatalf("cell %d: unexpected kind %v",
				c, decoded.CellKinds[c])
		}
		assertSameValue(t, reconstruct(t, f, []byte(f.json)), got)
	}

	assert.Len(t, decoded.Floats, floats)
	assert.Len(t, decoded.Ints, ints)
	assert.Len(t, decoded.Bools, bools)
	assert.Len(t, decoded.Strings, strs)
	assert.Len(t, decoded.Jsons, jsons)
}

// reconstruct parses encoded extended JSON and wraps the scalar in the
// fixture's expected wire kind: the same information a batch decoder
// has from the cell kind.
func reconstruct(
	t *testing.T,
	f fixture,
	encoded []byte,
) *spb.HistoryItem {
	t.Helper()

	// Raw JSON is not parsed back; the source kind comes from the cell
	// kind, and the text must be identical.
	if f.kind == filestreamv1.MetricsBatch_KIND_JSON {
		return &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: string(encoded)}}
	}

	parsed, err := simplejsonext.Unmarshal(encoded)
	require.NoError(t, err)

	switch f.kind {
	case filestreamv1.MetricsBatch_KIND_NULL:
		require.Nil(t, parsed)
		return &spb.HistoryItem{Value: &spb.HistoryItem_None{
			None: structpb.NullValue_NULL_VALUE}}
	case filestreamv1.MetricsBatch_KIND_BOOL:
		v, ok := parsed.(bool)
		require.True(t, ok, "expected bool, got %T", parsed)
		return &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{
			Boolean: v}}
	case filestreamv1.MetricsBatch_KIND_INT:
		v, ok := parsed.(int64)
		require.True(t, ok,
			"integer text must not parse as a float, got %T", parsed)
		return &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: v}}
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		v, ok := parsed.(float64)
		require.True(t, ok,
			"float text lost its kind, parsed as %T", parsed)
		return &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: v}}
	case filestreamv1.MetricsBatch_KIND_STRING:
		v, ok := parsed.(string)
		require.True(t, ok, "expected string, got %T", parsed)
		return &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: v}}
	default:
		t.Fatalf("no reconstruction for kind %v", f.kind)
		return nil
	}
}

// assertSameValue requires got to hold the same alternative as want and
// an equal scalar. Floats compare by bits, including signed zero. All
// NaNs are equal; JSON does not preserve payload bits.
func assertSameValue(t *testing.T, want, got *spb.HistoryItem) {
	t.Helper()
	require.IsType(t, want.Value, got.Value,
		"reconstructed a different alternative")

	switch w := want.Value.(type) {
	case *spb.HistoryItem_None:
		assert.Equal(t, structpb.NullValue_NULL_VALUE, got.GetNone())
	case *spb.HistoryItem_Boolean:
		assert.Equal(t, w.Boolean, got.GetBoolean())
	case *spb.HistoryItem_Integer:
		assert.Equal(t, w.Integer, got.GetInteger())
	case *spb.HistoryItem_Number:
		if g := got.GetNumber(); math.IsNaN(w.Number) {
			assert.True(t, math.IsNaN(g), "want NaN, got %v", g)
		} else {
			assert.Equal(t,
				math.Float64bits(w.Number), math.Float64bits(g))
		}
	case *spb.HistoryItem_Text:
		assert.Equal(t, w.Text, got.GetText())
	case *spb.HistoryItem_Json:
		assert.Equal(t, w.Json, got.GetJson())
	default:
		t.Fatalf("unhandled alternative %T", want.Value)
	}
}
