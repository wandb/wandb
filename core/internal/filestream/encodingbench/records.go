package encodingbench

import (
	"fmt"
	"slices"

	"github.com/wandb/simplejsonext"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type recordFixture struct {
	Mode    ValueMode
	Records []*spb.HistoryRecord
}

func recordFixtures(rows []Row) ([]recordFixture, error) {
	fixtures := make([]recordFixture, 0, 2)
	for _, mode := range []ValueMode{JSONValue, TypedValue} {
		records, err := recordsFromRows(rows, mode)
		if err != nil {
			return nil, err
		}
		fixtures = append(fixtures, recordFixture{Mode: mode, Records: records})
	}
	return fixtures, nil
}

func recordsFromRows(rows []Row, mode ValueMode) ([]*spb.HistoryRecord, error) {
	records := make([]*spb.HistoryRecord, len(rows))
	for rowIndex, row := range rows {
		record := &spb.HistoryRecord{Item: make([]*spb.HistoryItem, len(row.Cells))}
		for cellIndex, cell := range row.Cells {
			item, err := itemFromValue(cell.Key, cell.NestedKey, cell.Value, mode)
			if err != nil {
				return nil, fmt.Errorf("row %d cell %d: %w", rowIndex, cellIndex, err)
			}
			record.Item[cellIndex] = item
		}
		records[rowIndex] = record
	}
	return records, nil
}

func rowsFromRecords(records []*spb.HistoryRecord) ([]Row, error) {
	rows := make([]Row, len(records))
	for rowIndex, record := range records {
		if record == nil {
			return nil, fmt.Errorf("row %d: nil history record", rowIndex)
		}
		rows[rowIndex].Cells = make([]Cell, len(record.Item))
		for cellIndex, item := range record.Item {
			if item == nil {
				return nil, fmt.Errorf("row %d cell %d: nil history item", rowIndex, cellIndex)
			}
			value, err := valueFromItem(item)
			if err != nil {
				return nil, fmt.Errorf("row %d cell %d: %w", rowIndex, cellIndex, err)
			}
			rows[rowIndex].Cells[cellIndex] = Cell{
				Key:       item.Key,
				NestedKey: slices.Clone(item.NestedKey),
				Value:     value,
			}
		}
	}
	return rows, nil
}

func itemFromValue(key string, nestedKey []string, value Value, mode ValueMode) (*spb.HistoryItem, error) {
	item := &spb.HistoryItem{Key: key, NestedKey: slices.Clone(nestedKey)}
	switch mode {
	case JSONValue:
		encoded, err := valueJSON(value)
		if err != nil {
			return nil, err
		}
		item.ValueJson = string(encoded)
	case TypedValue:
		typed, err := typedValue(value)
		if err != nil {
			return nil, err
		}
		item.Value = typed
	default:
		return nil, fmt.Errorf("unknown value mode %q", mode)
	}
	return item, nil
}

func typedValue(value Value) (*spb.HistoryValue, error) {
	typed := &spb.HistoryValue{}
	switch value.Kind {
	case KindNull:
		typed.Kind = spb.HistoryValue_KIND_NULL
	case KindBool:
		typed.Kind = spb.HistoryValue_KIND_BOOL
		typed.BoolValue = value.Bool
	case KindNumber:
		typed.Kind = spb.HistoryValue_KIND_NUMBER
		typed.NumberValue = value.Number
	case KindString:
		typed.Kind = spb.HistoryValue_KIND_STRING
		typed.StringValue = value.String
	case KindJSON:
		if _, err := complexJSON(value.JSON); err != nil {
			return nil, err
		}
		typed.Kind = spb.HistoryValue_KIND_JSON
		typed.JsonValue = slices.Clone(value.JSON)
	default:
		return nil, fmt.Errorf("unknown value kind %d", value.Kind)
	}
	return typed, nil
}

func valueFromItem(item *spb.HistoryItem) (Value, error) {
	if item.Value != nil {
		value, err := valueFromTyped(item.Value)
		if err == nil {
			return value, nil
		}
		if item.ValueJson == "" {
			return Value{}, err
		}
	}
	decoded, err := simplejsonext.UnmarshalString(item.ValueJson)
	if err != nil {
		return Value{}, fmt.Errorf("decode value_json: %w", err)
	}
	return valueFromAny(decoded)
}

func valueFromTyped(value *spb.HistoryValue) (Value, error) {
	switch value.Kind {
	case spb.HistoryValue_KIND_NULL:
		return Value{Kind: KindNull}, nil
	case spb.HistoryValue_KIND_BOOL:
		return Value{Kind: KindBool, Bool: value.BoolValue}, nil
	case spb.HistoryValue_KIND_NUMBER:
		return Value{Kind: KindNumber, Number: value.NumberValue}, nil
	case spb.HistoryValue_KIND_STRING:
		return Value{Kind: KindString, String: value.StringValue}, nil
	case spb.HistoryValue_KIND_JSON:
		if _, err := complexJSON(value.JsonValue); err != nil {
			return Value{}, fmt.Errorf("invalid typed JSON value: %w", err)
		}
		return Value{Kind: KindJSON, JSON: slices.Clone(value.JsonValue)}, nil
	default:
		return Value{}, fmt.Errorf("unknown typed value kind %d", value.Kind)
	}
}
