package historycodec

import (
	"fmt"
	"math"
	"strconv"
	"strings"

	"github.com/wandb/simplejsonext"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ToExtendedJSON renders the item's typed value as W&B extended JSON.
//
// Extended JSON extends standard JSON with the literals NaN, Infinity
// and -Infinity. Finite floats always keep a decimal point or an
// exponent, so the text parses back to a float rather than an integer.
// The json alternative is emitted verbatim: it must hold valid extended
// JSON text, and it is preserved byte for byte.
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
