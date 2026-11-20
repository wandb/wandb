package historycodec_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/structpb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// A fixture declares one test value with its expected wire kind and
// extended JSON text, independent of the implementation.
type fixture struct {
	name string
	item *spb.HistoryItem
	kind filestreamv1.MetricsBatch_Kind
	json string
}

var fixtures = []fixture{
	{
		name: "json/negative integer zero",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `-0`}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "0",
	},
	{
		name: "json/nested",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"b":1.0,"a":[1.0,-0.0,NaN,{"z":9007199254740993,"y":"x\ud800"}],"c":{}}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"a":[1.0,-0.0,NaN,{"y":"x�","z":9007199254740993}],"b":1.0}`,
	},
	{
		name: "json/float",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `1.0`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `1.0`,
	},
	{
		name: "json/exact integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `9007199254740993`}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: `9007199254740993`,
	},
	{
		name: "json/wide integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `99999999999999999999`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `1e+20`,
	},
	{
		name: "json/min int64",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `-9223372036854775808`}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: `-9223372036854775808`,
	},
	{
		name: "json/null",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `null`}},
		kind: filestreamv1.MetricsBatch_KIND_NULL,
		json: `null`,
	},
	{
		name: "json/true",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `true`}},
		kind: filestreamv1.MetricsBatch_KIND_BOOL,
		json: `true`,
	},
	{
		name: "json/string",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `"s"`}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"s"`,
	},
	{
		name: "json/surrogate",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `"\ud800"`}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"�"`,
	},
	{
		name: "json/NaN",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `NaN`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `NaN`,
	},
	{
		name: "json/whitespace scalar",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: ` 1 `}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: `1`,
	},
	{
		name: "json/fraction",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `1.50`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `1.5`,
	},
	{
		name: "json/exponent",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `1e2`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `100.0`,
	},
	{
		name: "json/Infinity",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `Infinity`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `Infinity`,
	},
	{
		name: "json/-Infinity",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `-Infinity`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `-Infinity`,
	},
	{
		name: "json/overflow boundary",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `9223372036854775808`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `9.223372036854776e+18`,
	},
	{
		name: "json/negative overflow",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: `-9223372036854775809`}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: `-9.223372036854776e+18`,
	},
	{
		name: "text/invalid UTF-8",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{Text: "a\xff\xfeb"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"a��b"`,
	},
	{
		name: "none/null",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_None{
			None: structpb.NullValue_NULL_VALUE}},
		kind: filestreamv1.MetricsBatch_KIND_NULL,
		json: "null",
	},

	{
		name: "boolean/false",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{
			Boolean: false}},
		kind: filestreamv1.MetricsBatch_KIND_BOOL,
		json: "false",
	},
	{
		name: "boolean/true",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{
			Boolean: true}},
		kind: filestreamv1.MetricsBatch_KIND_BOOL,
		json: "true",
	},

	{
		name: "integer/zero",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: 0}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "0",
	},
	{
		name: "integer/negative",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: -12345}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "-12345",
	},
	{
		name: "integer/max int64",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: math.MaxInt64}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "9223372036854775807",
	},
	{
		name: "integer/min int64",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: math.MinInt64}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "-9223372036854775808",
	},
	{
		name: "integer/above 2^53",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: 1<<53 + 1}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "9007199254740993",
	},

	{
		name: "number/integral value",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 1.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "1.0",
	},
	{
		name: "number/positive zero",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 0.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "0.0",
	},
	{
		name: "number/negative zero",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Copysign(0, -1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "-0.0",
	},
	{
		name: "number/fraction",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 1.0 / 3.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "0.3333333333333333",
	},
	{
		name: "number/smallest subnormal",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.SmallestNonzeroFloat64}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "5e-324",
	},
	{
		name: "number/largest finite",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.MaxFloat64}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "1.7976931348623157e+308",
	},

	{
		name: "number/NaN",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.NaN()}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "NaN",
	},
	{
		name: "number/+Infinity",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Inf(1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "Infinity",
	},
	{
		name: "number/-Infinity",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Inf(-1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "-Infinity",
	},

	{
		name: "text/empty",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: ""}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `""`,
	},
	{
		name: "text/unicode",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: "héllo 🌍"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"héllo 🌍"`,
	},
	{
		name: "text/escapes",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: "a\"b\\c\n\t\x01"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"a\"b\\c\n\t\u0001"`,
	},

	{
		name: "json/object",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"a": 1, "b": "x"}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"a":1,"b":"x"}`,
	},
	{
		name: "json/array",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `[1, 2.5, "three", null]`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `[1,2.5,"three",null]`,
	},
	{
		name: "json/empty object",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{}`,
	},
	{
		name: "json/empty array",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `[]`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `[]`,
	},
	{
		name: "json/scalar text",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `"scalar"`}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"scalar"`,
	},
	{
		name: "json/whitespace",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: "  {  \"a\" :\n\t [ 1 , 2 ] }  "}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"a":[1,2]}`,
	},
	{
		name: "json/nested non-finite",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"nan": NaN, "pos": Infinity, "neg": -Infinity}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"nan":NaN,"neg":-Infinity,"pos":Infinity}`,
	},
	{
		name: "json/int wider than int64",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"big": 123456789012345678901234567890}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"big":1.2345678901234568e+29}`,
	},
}

// TestOneofCoverage requires a fixture, and therefore a declared mapping
// and conversion, for every alternative of the HistoryItem.value oneof.
// A schema addition fails here until the contract extends.
func TestOneofCoverage(t *testing.T) {
	oneof := (&spb.HistoryItem{}).ProtoReflect().
		Descriptor().Oneofs().ByName("value")
	require.NotNil(t, oneof, "HistoryItem has no value oneof")

	covered := make(map[string]int)
	for _, f := range fixtures {
		field := f.item.ProtoReflect().WhichOneof(oneof)
		require.NotNil(t, field)
		covered[string(field.Name())]++
	}

	fields := oneof.Fields()
	for i := 0; i < fields.Len(); i++ {
		name := string(fields.Get(i).Name())
		assert.NotZero(t, covered[name],
			"no fixture for value alternative %q", name)
		delete(covered, name)
	}
	assert.Empty(t, covered,
		"fixtures exist for alternatives not in the schema")
}

func TestKind(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			v, present := fixtureValue(t, f)
			if !present {
				return
			}
			kind, err := historycodec.Kind(v)
			require.NoError(t, err)
			assert.Equal(t, f.kind, kind)
			assert.NotEqual(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		})
	}
}

// fixtureValue gets a top-level wire cell from the production decoder
// without serializing floats through RunHistory's JSONL encoder.
func fixtureValue(t *testing.T, f fixture) (any, bool) {
	t.Helper()
	item := proto.Clone(f.item).(*spb.HistoryItem)
	item.Key = "metric"
	rh := runhistory.New()
	require.NoError(t, rh.SetFromRecord(item))
	if rh.IsEmpty() {
		require.Equal(t, "json/empty object", f.name)
		return nil, false // Empty objects do not create cells.
	}

	root := make(map[string]any)
	rh.WireCells(func(key string, v any) bool {
		kind, err := historycodec.Kind(v)
		require.NoError(t, err)
		require.NotEqual(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		_, err = historycodec.Normalize(v)
		require.NoError(t, err)
		root[key] = v
		return true
	})
	require.Len(t, root, 1)
	return root["metric"], true
}

func TestUnsupportedValues(t *testing.T) {
	for _, v := range []any{int(1234567), float32(1234567), struct{ Secret string }{"private-value"}} {
		kind, err := historycodec.Kind(v)
		require.Error(t, err)
		assert.Equal(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind)
		assert.NotContains(t, err.Error(), "1234567")
		assert.NotContains(t, err.Error(), "private-value")
		for _, nested := range []any{v, []any{v}, map[string]any{"private-key": v}} {
			_, err := historycodec.Normalize(nested)
			require.Error(t, err)
			assert.NotContains(t, err.Error(), "1234567")
			assert.NotContains(t, err.Error(), "private-value")
			assert.NotContains(t, err.Error(), "private-key")
		}
	}
}
