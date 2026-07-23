// Package encodingbench contains an experimental filestream encoding harness.
// It is not a production wire protocol.
package encodingbench

import (
	"fmt"
	"math"
	"reflect"
	"slices"

	"github.com/wandb/simplejsonext"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ValueKind is the backend-aligned semantic type of a history value.
type ValueKind uint8

const (
	KindNull ValueKind = iota + 1
	KindBool
	KindNumber
	KindString
	KindJSON
)

// Value is a typed history value. JSON contains an encoded array or object.
type Value struct {
	Kind   ValueKind
	Bool   bool
	Number float64
	String string
	JSON   []byte
}

type Cell struct {
	Key       string
	NestedKey []string
	Value     Value
}

type Row struct {
	Cells []Cell
}

type Dataset struct {
	Name string
	Rows []Row
}

type ValueMode string

const (
	ValueJSONOnly ValueMode = "value_json_only"
	TypedOnly     ValueMode = "typed_only"
)

type EncodedEnvelope struct {
	Data      []byte
	BodyBytes int
}

// EnvelopeCodec encodes and decodes complete filestream request envelopes.
type EnvelopeCodec interface {
	Name() string
	Encode([]*spb.HistoryRecord) (EncodedEnvelope, error)
	Decode([]byte, ValueMode) ([]*spb.HistoryRecord, error)
}

func valueJSON(value Value) ([]byte, error) {
	switch value.Kind {
	case KindNull:
		return []byte("null"), nil
	case KindBool:
		return simplejsonext.Marshal(value.Bool)
	case KindNumber:
		return simplejsonext.Marshal(value.Number)
	case KindString:
		return simplejsonext.Marshal(value.String)
	case KindJSON:
		if _, err := complexJSON(value.JSON); err != nil {
			return nil, err
		}
		return value.JSON, nil
	default:
		return nil, fmt.Errorf("unknown value kind %d", value.Kind)
	}
}

func valueAny(value Value) (any, error) {
	switch value.Kind {
	case KindNull:
		return nil, nil
	case KindBool:
		return value.Bool, nil
	case KindNumber:
		return value.Number, nil
	case KindString:
		return value.String, nil
	case KindJSON:
		decoded, err := complexJSON(value.JSON)
		if err != nil {
			return nil, err
		}
		return decoded, nil
	default:
		return nil, fmt.Errorf("unknown value kind %d", value.Kind)
	}
}

func complexJSON(data []byte) (any, error) {
	decoded, err := simplejsonext.Unmarshal(data)
	if err != nil {
		return nil, fmt.Errorf("invalid JSON value: %w", err)
	}
	switch decoded.(type) {
	case []any, map[string]any:
		return decoded, nil
	default:
		return nil, fmt.Errorf("JSON fallback is %T, want array or object", decoded)
	}
}

func valueFromAny(value any) (Value, error) {
	switch value := value.(type) {
	case nil:
		return Value{Kind: KindNull}, nil
	case bool:
		return Value{Kind: KindBool, Bool: value}, nil
	case float64:
		return Value{Kind: KindNumber, Number: value}, nil
	case int64:
		return Value{Kind: KindNumber, Number: float64(value)}, nil
	case string:
		return Value{Kind: KindString, String: value}, nil
	case []any, map[string]any:
		encoded, err := simplejsonext.Marshal(value)
		if err != nil {
			return Value{}, fmt.Errorf("marshal complex value: %w", err)
		}
		return Value{Kind: KindJSON, JSON: encoded}, nil
	default:
		return Value{}, fmt.Errorf("unsupported decoded value type %T", value)
	}
}

func normalizedRows(rows []Row) ([]Row, error) {
	result := make([]Row, len(rows))
	for rowIndex, row := range rows {
		result[rowIndex].Cells = slices.Clone(row.Cells)
		for cellIndex := range result[rowIndex].Cells {
			cell := &result[rowIndex].Cells[cellIndex]
			cell.NestedKey = slices.Clone(cell.NestedKey)
			if cell.Value.Kind == KindJSON {
				if _, err := complexJSON(cell.Value.JSON); err != nil {
					return nil, err
				}
			}
		}
		slices.SortFunc(result[rowIndex].Cells, func(a, b Cell) int {
			aKey := cellIdentity(a)
			bKey := cellIdentity(b)
			if aKey < bKey {
				return -1
			}
			if aKey > bKey {
				return 1
			}
			return 0
		})
	}
	return result, nil
}

func cellIdentity(cell Cell) string {
	if len(cell.NestedKey) > 0 {
		return "nested:" + fmt.Sprint(cell.NestedKey)
	}
	return "key:" + cell.Key
}

func valuesEqual(a, b Value) bool {
	if a.Kind != b.Kind {
		return false
	}
	switch a.Kind {
	case KindNull:
		return true
	case KindBool:
		return a.Bool == b.Bool
	case KindNumber:
		return a.Number == b.Number || math.IsNaN(a.Number) && math.IsNaN(b.Number)
	case KindString:
		return a.String == b.String
	case KindJSON:
		aDecoded, aErr := simplejsonext.Unmarshal(a.JSON)
		bDecoded, bErr := simplejsonext.Unmarshal(b.JSON)
		return aErr == nil && bErr == nil && reflect.DeepEqual(aDecoded, bDecoded)
	default:
		return false
	}
}
