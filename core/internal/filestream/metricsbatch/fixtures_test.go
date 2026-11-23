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

const (
	kNull   = filestreamv1.MetricsBatch_KIND_NULL
	kBool   = filestreamv1.MetricsBatch_KIND_BOOL
	kInt    = filestreamv1.MetricsBatch_KIND_INT
	kFloat  = filestreamv1.MetricsBatch_KIND_FLOAT
	kString = filestreamv1.MetricsBatch_KIND_STRING
	kJSON   = filestreamv1.MetricsBatch_KIND_JSON
)

func fx(
	name string,
	item *spb.HistoryItem,
	kind filestreamv1.MetricsBatch_Kind,
	json string,
) fixture {
	return fixture{name: name, item: item, kind: kind, json: json}
}

func jsonv(s string) *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_Json{Json: s}}
}

func none() *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_None{None: structpb.NullValue_NULL_VALUE}}
}

func boolean(b bool) *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_Boolean{Boolean: b}}
}

func integer(i int64) *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_Integer{Integer: i}}
}

func number(f float64) *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_Number{Number: f}}
}

func text(s string) *spb.HistoryItem {
	return &spb.HistoryItem{Value: &spb.HistoryItem_Text{Text: s}}
}

var fixtures = []fixture{
	fx("json/negative integer zero", jsonv(`-0`), kInt, `0`),
	fx("json/nested",
		jsonv(`{"b":1.0,"a":[1.0,-0.0,NaN,{"z":9007199254740993,"y":"x\ud800"}],"c":{}}`),
		kJSON, `{"a":[1.0,-0.0,NaN,{"y":"x�","z":9007199254740993}],"b":1.0}`),
	fx("json/float", jsonv(`1.0`), kFloat, `1.0`),
	fx("json/exact integer", jsonv(`9007199254740993`), kInt, `9007199254740993`),
	fx("json/wide integer", jsonv(`99999999999999999999`), kFloat, `1e+20`),
	fx("json/min int64", jsonv(`-9223372036854775808`), kInt, `-9223372036854775808`),
	fx("json/null", jsonv(`null`), kNull, `null`),
	fx("json/true", jsonv(`true`), kBool, `true`),
	fx("json/string", jsonv(`"s"`), kString, `"s"`),
	fx("json/surrogate", jsonv(`"\ud800"`), kString, `"�"`),
	fx("json/NaN", jsonv(`NaN`), kFloat, `NaN`),
	fx("json/whitespace scalar", jsonv(` 1 `), kInt, `1`),
	fx("json/fraction", jsonv(`1.50`), kFloat, `1.5`),
	fx("json/exponent", jsonv(`1e2`), kFloat, `100.0`),
	fx("json/Infinity", jsonv(`Infinity`), kFloat, `Infinity`),
	fx("json/-Infinity", jsonv(`-Infinity`), kFloat, `-Infinity`),
	fx("json/overflow boundary", jsonv(`9223372036854775808`), kFloat, `9.223372036854776e+18`),
	fx("json/negative overflow", jsonv(`-9223372036854775809`), kFloat, `-9.223372036854776e+18`),

	fx("none/null", none(), kNull, `null`),

	fx("boolean/false", boolean(false), kBool, `false`),
	fx("boolean/true", boolean(true), kBool, `true`),

	fx("integer/zero", integer(0), kInt, `0`),
	fx("integer/negative", integer(-12345), kInt, `-12345`),
	fx("integer/max int64", integer(math.MaxInt64), kInt, `9223372036854775807`),
	fx("integer/min int64", integer(math.MinInt64), kInt, `-9223372036854775808`),
	fx("integer/above 2^53", integer(1<<53+1), kInt, `9007199254740993`),

	fx("number/integral value", number(1.0), kFloat, `1.0`),
	fx("number/positive zero", number(0.0), kFloat, `0.0`),
	fx("number/negative zero", number(math.Copysign(0, -1)), kFloat, `-0.0`),
	fx("number/fraction", number(1.0/3.0), kFloat, `0.3333333333333333`),
	fx("number/smallest subnormal", number(math.SmallestNonzeroFloat64), kFloat, `5e-324`),
	fx("number/largest finite", number(math.MaxFloat64), kFloat, `1.7976931348623157e+308`),
	fx("number/NaN", number(math.NaN()), kFloat, `NaN`),
	fx("number/+Infinity", number(math.Inf(1)), kFloat, `Infinity`),
	fx("number/-Infinity", number(math.Inf(-1)), kFloat, `-Infinity`),

	fx("text/numeric", text("007"), kString, `"007"`),
	fx("text/empty", text(""), kString, `""`),
	fx("text/unicode", text("héllo 🌍"), kString, `"héllo 🌍"`),
	fx("text/escapes", text("a\"b\\c\n\t\x01"), kString, `"a\"b\\c\n\t\u0001"`),

	fx("json/object", jsonv(`{"a": 1, "b": "x"}`), kJSON, `{"a":1,"b":"x"}`),
	fx("json/array", jsonv(`[1, 2.5, "three", null]`), kJSON, `[1,2.5,"three",null]`),
	{name: "json/empty object", item: jsonv(`{}`), absent: true},
	fx("json/empty array", jsonv(`[]`), kJSON, `[]`),
	fx("json/scalar text", jsonv(`"scalar"`), kString, `"scalar"`),
	fx("json/whitespace", jsonv("  {  \"a\" :\n\t [ 1 , 2 ] }  "), kJSON, `{"a":[1,2]}`),
	fx("json/nested non-finite", jsonv(`{"nan": NaN, "pos": Infinity, "neg": -Infinity}`),
		kJSON, `{"nan":NaN,"neg":-Infinity,"pos":Infinity}`),
	fx("json/int wider than int64", jsonv(`{"big": 123456789012345678901234567890}`),
		kJSON, `{"big":1.2345678901234568e+29}`),
}
