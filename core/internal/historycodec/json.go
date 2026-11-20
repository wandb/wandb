package historycodec

import (
	"fmt"
	"math"
	"strconv"
	"strings"
	"unicode/utf8"

	"github.com/wandb/simplejsonext"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ToExtendedJSON renders the item's normalized value as W&B extended JSON.
//
// Extended JSON extends standard JSON with the literals NaN, Infinity
// and -Infinity. Finite floats always keep a decimal point or an
// exponent, so the text parses back to a float rather than an integer.
// JSON containers are preserved byte for byte without validation. JSON
// scalars render as their matching typed alternatives. Strings replace
// each invalid UTF-8 byte with U+FFFD.
//
// The same inputs rejected by WireKind are errors here.
func ToExtendedJSON(item *spb.HistoryItem) ([]byte, error) {
	v, err := decode(item)
	if err != nil {
		return nil, err
	}

	switch v.kind {
	case filestreamv1.MetricsBatch_KIND_NULL:
		return []byte("null"), nil
	case filestreamv1.MetricsBatch_KIND_BOOL:
		return strconv.AppendBool(nil, v.b), nil
	case filestreamv1.MetricsBatch_KIND_INT:
		return strconv.AppendInt(nil, v.i, 10), nil
	case filestreamv1.MetricsBatch_KIND_FLOAT:
		return marshalFloat(v.f), nil
	case filestreamv1.MetricsBatch_KIND_STRING:
		return simplejsonext.Marshal(v.s)
	case filestreamv1.MetricsBatch_KIND_JSON:
		return []byte(v.s), nil
	default:
		return nil, fmt.Errorf(
			"historycodec: no JSON conversion for %v", v.kind)
	}
}

func decodeJSON(s string) (value, error) {
	trimmed := strings.Trim(s, " \t\r\n")
	if trimmed != "" && (trimmed[0] == '{' || trimmed[0] == '[') {
		return value{kind: filestreamv1.MetricsBatch_KIND_JSON, s: s}, nil
	}
	parsed, err := simplejsonext.UnmarshalString(trimmed)
	if err != nil {
		return value{}, fmt.Errorf("historycodec: invalid JSON scalar")
	}
	return scalarValue(parsed)
}

func scalarValue(parsed any) (value, error) {
	switch v := parsed.(type) {
	case nil:
		return value{kind: filestreamv1.MetricsBatch_KIND_NULL}, nil
	case bool:
		return value{kind: filestreamv1.MetricsBatch_KIND_BOOL, b: v}, nil
	case int64:
		return value{kind: filestreamv1.MetricsBatch_KIND_INT, i: v}, nil
	case float64:
		return value{kind: filestreamv1.MetricsBatch_KIND_FLOAT, f: v}, nil
	case string:
		return value{kind: filestreamv1.MetricsBatch_KIND_STRING, s: normalizeString(v)}, nil
	default:
		return value{}, fmt.Errorf("historycodec: invalid JSON scalar")
	}
}

func normalizeString(s string) string {
	if utf8.ValidString(s) {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		b.WriteRune(r)
	}
	return b.String()
}

// marshalFloat renders f as extended JSON. 'g' with precision -1 is the
// shortest text that round-trips to the same float64 bits. It drops the
// decimal point on integral values, so ".0" is appended when the result
// has neither a decimal point nor an exponent.
func marshalFloat(f float64) []byte {
	switch {
	case math.IsNaN(f):
		return []byte("NaN")
	case math.IsInf(f, 1):
		return []byte("Infinity")
	case math.IsInf(f, -1):
		return []byte("-Infinity")
	}

	s := strconv.FormatFloat(f, 'g', -1, 64)
	if !strings.ContainsAny(s, ".eE") {
		s += ".0"
	}
	return []byte(s)
}
