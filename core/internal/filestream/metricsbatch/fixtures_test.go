package metricsbatch

import (
	"math"

	"google.golang.org/protobuf/types/known/structpb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// A fixture declares one test value with its expected wire kind and
// extended JSON text, independent of the implementation.
type fixture struct {
	name string
	item *spb.HistoryItem
	kind filestreamv1.MetricsBatch_Kind
	json string

	// absent is true when RunHistory stores nothing for the value,
	// so the row has no cell.
	absent bool
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
		name: "text/numeric",
		item: &spb.HistoryItem{Value: &spb.HistoryItem_Text{
			Text: "007"}},
		kind: filestreamv1.MetricsBatch_KIND_STRING,
		json: `"007"`,
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
		absent: true,
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
