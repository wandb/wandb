// Package historycodec converts the typed history log schema
// (spb.HistoryItem) to the filestream wire schema
// (filestreamv1.MetricsBatch).
//
// HistoryItem.value is a protobuf oneof with six alternatives.
// JSON containers retain their raw text; JSON scalars are normalized to
// scalar wire kinds, and strings replace invalid UTF-8 bytes with U+FFFD.
// These helpers are the conversion contract for the batch builder; they
// do not change the JSONL upload path.
package historycodec

import (
	"fmt"

	"google.golang.org/protobuf/types/known/structpb"

	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// WireKind returns the MetricsBatch kind after normalizing JSON scalars.
//
// It returns an error when the item is nil, its value oneof is unset or
// holds a nil wrapper, the none payload is not NULL_VALUE, the
// alternative has no mapping, or a JSON scalar cannot be parsed.
// An unset oneof is not a null value: the caller is responsible for any
// value_json fallback.
func WireKind(item *spb.HistoryItem) (filestreamv1.MetricsBatch_Kind, error) {
	v, err := decode(item)
	if err != nil {
		return filestreamv1.MetricsBatch_KIND_UNSPECIFIED, err
	}
	return v.kind, nil
}

// value is a validated typed value: its wire kind and payload.
type value struct {
	kind filestreamv1.MetricsBatch_Kind
	b    bool
	i    int64
	f    float64
	s    string // Text payload, or raw JSON text for KIND_JSON.
}

// decode validates the item's value oneof and returns its payload.
func decode(item *spb.HistoryItem) (value, error) {
	if item == nil {
		return value{}, fmt.Errorf("historycodec: nil history item")
	}
	if err := errNilWrapper(item.Value); err != nil {
		return value{}, err
	}

	switch v := item.Value.(type) {
	case *spb.HistoryItem_None:
		if v.None != structpb.NullValue_NULL_VALUE {
			return value{}, fmt.Errorf(
				"historycodec: none payload %d is not NULL_VALUE",
				int32(v.None))
		}
		return value{kind: filestreamv1.MetricsBatch_KIND_NULL}, nil

	case *spb.HistoryItem_Boolean:
		return value{
			kind: filestreamv1.MetricsBatch_KIND_BOOL,
			b:    v.Boolean,
		}, nil

	case *spb.HistoryItem_Integer:
		return value{
			kind: filestreamv1.MetricsBatch_KIND_INT,
			i:    v.Integer,
		}, nil

	case *spb.HistoryItem_Number:
		return value{
			kind: filestreamv1.MetricsBatch_KIND_FLOAT,
			f:    v.Number,
		}, nil

	case *spb.HistoryItem_Text:
		return value{
			kind: filestreamv1.MetricsBatch_KIND_STRING,
			s:    normalizeString(v.Text),
		}, nil

	case *spb.HistoryItem_Json:
		return decodeJSON(v.Json)

	case nil:
		return value{}, fmt.Errorf("historycodec: value oneof is not set")

	default:
		return value{}, fmt.Errorf(
			"historycodec: unsupported value alternative %T", item.Value)
	}
}

// errNilWrapper returns an error when v is a oneof wrapper holding a nil
// pointer. A new wrapper type that lacks a case here still fails in
// decode's default case before its fields are dereferenced.
func errNilWrapper(v any) error {
	switch v := v.(type) {
	case *spb.HistoryItem_None:
		if v == nil {
			return fmt.Errorf("historycodec: nil none value wrapper")
		}
	case *spb.HistoryItem_Boolean:
		if v == nil {
			return fmt.Errorf("historycodec: nil boolean value wrapper")
		}
	case *spb.HistoryItem_Integer:
		if v == nil {
			return fmt.Errorf("historycodec: nil integer value wrapper")
		}
	case *spb.HistoryItem_Number:
		if v == nil {
			return fmt.Errorf("historycodec: nil number value wrapper")
		}
	case *spb.HistoryItem_Text:
		if v == nil {
			return fmt.Errorf("historycodec: nil text value wrapper")
		}
	case *spb.HistoryItem_Json:
		if v == nil {
			return fmt.Errorf("historycodec: nil json value wrapper")
		}
	}
	return nil
}
