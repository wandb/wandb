package historycodec_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/structpb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/historycodec"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// A fixture declares one test value with its expected wire kind and
// extended JSON text, independent of the implementation.
type fixture struct {
	name  string
	field string // The item's oneof field name.
	item  *spb.HistoryItem
	kind  filestreamv1.MetricsBatch_Kind
	json  string
}

var fixtures = []fixture{
	{
		name:  "none/null",
		field: "none",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_None{
			None: structpb.NullValue_NULL_VALUE}},
		kind: filestreamv1.MetricsBatch_KIND_NULL,
		json: "null",
	},

	{
		name:  "boolean/false",
		field: "boolean",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{
			Boolean: false}},
		kind: filestreamv1.MetricsBatch_KIND_BOOL,
		json: "false",
	},
	{
		name:  "boolean/true",
		field: "boolean",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{
			Boolean: true}},
		kind: filestreamv1.MetricsBatch_KIND_BOOL,
		json: "true",
	},

	{
		name:  "integer/zero",
		field: "integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: 0}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "0",
	},
	{
		name:  "integer/negative",
		field: "integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: -12345}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "-12345",
	},
	{
		name:  "integer/max int64",
		field: "integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: math.MaxInt64}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "9223372036854775807",
	},
	{
		name:  "integer/min int64",
		field: "integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: math.MinInt64}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "-9223372036854775808",
	},
	{
		name:  "integer/above 2^53",
		field: "integer",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Integer{
			Integer: 1<<53 + 1}},
		kind: filestreamv1.MetricsBatch_KIND_INT,
		json: "9007199254740993",
	},

	{
		name:  "number/integral value",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 1.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "1.0",
	},
	{
		name:  "number/positive zero",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 0.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "0.0",
	},
	{
		name:  "number/negative zero",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Copysign(0, -1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "-0.0",
	},
	{
		name:  "number/fraction",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: 1.0 / 3.0}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "0.3333333333333333",
	},
	{
		name:  "number/smallest subnormal",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.SmallestNonzeroFloat64}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "5e-324",
	},
	{
		name:  "number/largest finite",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.MaxFloat64}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "1.7976931348623157e+308",
	},

	{
		name:  "number/NaN",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.NaN()}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "NaN",
	},
	{
		name:  "number/+Infinity",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Inf(1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "Infinity",
	},
	{
		name:  "number/-Infinity",
		field: "number",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Number{
			Number: math.Inf(-1)}},
		kind: filestreamv1.MetricsBatch_KIND_FLOAT,
		json: "-Infinity",
	},

	{
		name:  "text/empty",
		field: "text",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: ""}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `""`,
	},
	{
		name:  "text/unicode",
		field: "text",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: "héllo 🌍"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"héllo 🌍"`,
	},
	{
		name:  "text/escapes",
		field: "text",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: "a\"b\\c\n\t\x01"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"a\"b\\c\n\t\u0001"`,
	},

	{
		name:  "json/object",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"a": 1, "b": "x"}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"a": 1, "b": "x"}`,
	},
	{
		name:  "json/array",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `[1, 2.5, "three", null]`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `[1, 2.5, "three", null]`,
	},
	{
		name:  "json/empty object",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{}`,
	},
	{
		name:  "json/empty array",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `[]`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `[]`,
	},
	{
		name:  "json/scalar text",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `"scalar"`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `"scalar"`,
	},
	{
		name:  "json/whitespace",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: "  {  \"a\" :\n\t [ 1 , 2 ] }  "}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: "  {  \"a\" :\n\t [ 1 , 2 ] }  ",
	},
	{
		name:  "json/nested non-finite",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"nan": NaN, "pos": Infinity, "neg": -Infinity}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"nan": NaN, "pos": Infinity, "neg": -Infinity}`,
	},
	{
		name:  "json/int wider than int64",
		field: "json",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Json{
			Json: `{"big": 123456789012345678901234567890}`}},
		kind: filestreamv1.MetricsBatch_KIND_JSON,
		json: `{"big": 123456789012345678901234567890}`,
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
		covered[f.field]++
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

func TestWireKind(t *testing.T) {
	for _, f := range fixtures {
		t.Run(f.name, func(t *testing.T) {
			kind, err := historycodec.WireKind(f.item)
			require.NoError(t, err)
			assert.Equal(t, f.kind, kind)
		})
	}
}

func TestInvalidValues(t *testing.T) {
	cases := []struct {
		name string
		item *spb.HistoryItem
	}{
		{"nil item", nil},
		{"unset oneof", &spb.HistoryItem{}},
		// An absent typed field is not null even when value_json is set:
		// fallback is the caller's responsibility.
		{"unset oneof with value_json",
			&spb.HistoryItem{ValueJson: "1.0"}},
		{"none payload is not NULL_VALUE",
			&spb.HistoryItem{Value: &spb.HistoryItem_None{
				None: structpb.NullValue(42)}}},
		{"nil none wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_None)(nil)}},
		{"nil boolean wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_Boolean)(nil)}},
		{"nil integer wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_Integer)(nil)}},
		{"nil number wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_Number)(nil)}},
		{"nil text wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_Text)(nil)}},
		{"nil json wrapper",
			&spb.HistoryItem{Value: (*spb.HistoryItem_Json)(nil)}},
	}

	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			kind, err := historycodec.WireKind(c.item)
			assert.Error(t, err)
			assert.Equal(t, filestreamv1.MetricsBatch_KIND_UNSPECIFIED, kind,
				"an invalid value must never map to a wire kind")

			_, err = historycodec.ToExtendedJSON(c.item)
			assert.Error(t, err)
		})
	}
}
