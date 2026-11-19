package evaltables

import (
	"encoding/json"
	"errors"
	"fmt"
	"strconv"

	ces "github.com/wandb/cwevals-go"

	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// rowColumn is a column of an EvalTable row's input, output, or scores.
type rowColumn struct {
	name string

	// key is the column's name as a JSON object key followed by a colon,
	// such as `"expected":` for a column named expected.
	key []byte

	// valueType is the column's CES value type.
	valueType string

	// mediaType is the column's W&B media type, or empty if it isn't a
	// media column.
	mediaType string
}

// rowEncoder writes the CES row JSON of an EvalTable's typed rows.
type rowEncoder struct {
	media *mediaConverter

	inputs  []rowColumn
	outputs []rowColumn
	scores  []rowColumn
}

// The table's columns must have passed validateColumns.
func newRowEncoder(
	data *spb.EvalTableData,
	runPath runbranch.RunPath,
) (*rowEncoder, error) {
	e := &rowEncoder{media: &mediaConverter{runPath: runPath}}

	for _, field := range data.GetDatasetFields() {
		column, err := newRowColumn(
			field.GetName(), field.GetValueType(), field.GetWandbMediaType())
		if err != nil {
			return nil, err
		}

		switch source := ces.EvalTableColumnNewParamsDatasetFieldsSource(field.GetSource()); source {
		case ces.EvalTableColumnNewParamsDatasetFieldsSourceInput:
			e.inputs = append(e.inputs, column)
		case ces.EvalTableColumnNewParamsDatasetFieldsSourceOutput:
			e.outputs = append(e.outputs, column)
		default:
			return nil, fmt.Errorf(
				"field %q has unsupported source %q", field.GetName(), source)
		}
	}

	for _, scorer := range data.GetScorers() {
		column, err := newRowColumn(scorer.GetName(), scorer.GetValueType(), "")
		if err != nil {
			return nil, err
		}
		e.scores = append(e.scores, column)
	}

	return e, nil
}

func newRowColumn(name, valueType, mediaType string) (rowColumn, error) {
	key, err := appendJSON(nil, name)
	if err != nil {
		return rowColumn{}, fmt.Errorf("column %q: %v", name, err)
	}

	return rowColumn{
		name:      name,
		key:       append(key, ':'),
		valueType: valueType,
		mediaType: mediaType,
	}, nil
}

func (e *rowEncoder) encodeRows(rows []*spb.EvalTableRow) ([][]byte, error) {
	encoded := make([][]byte, len(rows))
	for i, row := range rows {
		rowJSON, err := e.encodeRow(row)
		if err != nil {
			return nil, fmt.Errorf("%v (row %d)", err, i)
		}
		encoded[i] = rowJSON
	}
	return encoded, nil
}

// encodeRow returns a row's CES row JSON, of the form
// {"input": {...} | null, "output": {...} | null, "scores": {...}}
// with "example_key" if the row has one.
func (e *rowEncoder) encodeRow(row *spb.EvalTableRow) ([]byte, error) {
	var err error
	buf := []byte(`{"input":`)
	if buf, err = e.appendPart(buf, "input", e.inputs, row.GetInput()); err != nil {
		return nil, err
	}

	buf = append(buf, `,"output":`...)
	if buf, err = e.appendPart(buf, "output", e.outputs, row.GetOutput()); err != nil {
		return nil, err
	}

	buf = append(buf, `,"scores":`...)
	if buf, err = e.appendValues(buf, "score", e.scores, row.GetScores()); err != nil {
		return nil, err
	}

	if exampleKey := row.GetExampleKey(); exampleKey != "" {
		buf = append(buf, `,"example_key":`...)
		if buf, err = appendJSON(buf, exampleKey); err != nil {
			return nil, fmt.Errorf("example key: %v", err)
		}
	}
	buf = append(buf, '}')

	if len(rowBatchPrefix)+len(buf)+len(rowBatchSuffix) >= maxRequestBodyBytes {
		return nil, fmt.Errorf(
			"row is %d bytes, must be under %d",
			len(buf), maxRequestBodyBytes-len(rowBatchPrefix)-len(rowBatchSuffix))
	}

	return buf, nil
}

// appendPart appends a row's input or output object, or null if unset.
//
// part names the values in errors.
func (e *rowEncoder) appendPart(
	buf []byte,
	part string,
	columns []rowColumn,
	values *spb.EvalTableRowValues,
) ([]byte, error) {
	if values == nil {
		return append(buf, "null"...), nil
	}
	return e.appendValues(buf, part, columns, values.GetValues())
}

// appendValues appends a JSON object mapping each column's name to the
// value at the same position in values, such as {"expected":"cat","weight":0.5}.
//
// part names the values in errors.
func (e *rowEncoder) appendValues(
	buf []byte,
	part string,
	columns []rowColumn,
	values []*spb.EvalTableValue,
) ([]byte, error) {
	if len(values) != len(columns) {
		return nil, fmt.Errorf(
			"row has %d %s values, expected %d",
			len(values), part, len(columns))
	}

	buf = append(buf, '{')
	for i, value := range values {
		if i > 0 {
			buf = append(buf, ',')
		}
		buf = append(buf, columns[i].key...)

		var err error
		buf, err = e.appendValue(buf, columns[i], value)
		if err != nil {
			return nil, fmt.Errorf("field %q: %v", columns[i].name, err)
		}
	}
	return append(buf, '}'), nil
}

// appendValue appends a value as JSON, checking that it fits its column.
func (e *rowEncoder) appendValue(
	buf []byte,
	column rowColumn,
	value *spb.EvalTableValue,
) ([]byte, error) {
	if !column.fits(value) {
		return nil, fmt.Errorf("%s in %s", valueKind(value), columnKind(column))
	}

	switch value := value.GetValue().(type) {
	case *spb.EvalTableValue_BoolValue:
		return strconv.AppendBool(buf, value.BoolValue), nil
	case *spb.EvalTableValue_IntValue:
		return strconv.AppendInt(buf, value.IntValue, 10), nil
	case *spb.EvalTableValue_NumberValue:
		return appendJSON(buf, value.NumberValue)
	case *spb.EvalTableValue_StringValue:
		return appendJSON(buf, value.StringValue)
	case *spb.EvalTableValue_JsonValue:
		if !json.Valid([]byte(value.JsonValue)) {
			return nil, errors.New("invalid JSON")
		}
		return append(buf, value.JsonValue...), nil
	case *spb.EvalTableValue_WandbMediaJson:
		converted, err := e.media.convertMedia(
			json.RawMessage(value.WandbMediaJson),
			column.mediaType,
		)
		if err != nil {
			return nil, err
		}
		return append(buf, converted...), nil
	default:
		return append(buf, "null"...), nil
	}
}

// fits reports whether a value can be in the column.
//
// Null fits any column, and integers fit "number" columns too.
func (c rowColumn) fits(value *spb.EvalTableValue) bool {
	if c.mediaType != "" {
		switch value.GetValue().(type) {
		case nil, *spb.EvalTableValue_WandbMediaJson:
			return true
		default:
			return false
		}
	}

	switch value.GetValue().(type) {
	case nil:
		return true
	case *spb.EvalTableValue_BoolValue:
		return c.valueType == "boolean"
	case *spb.EvalTableValue_IntValue:
		return c.valueType == "integer" || c.valueType == "number"
	case *spb.EvalTableValue_NumberValue:
		return c.valueType == "number"
	case *spb.EvalTableValue_StringValue:
		return c.valueType == "string"
	case *spb.EvalTableValue_JsonValue:
		return c.valueType == "json"
	default:
		return false
	}
}

func valueKind(value *spb.EvalTableValue) string {
	switch value.GetValue().(type) {
	case *spb.EvalTableValue_BoolValue:
		return "boolean value"
	case *spb.EvalTableValue_IntValue:
		return "integer value"
	case *spb.EvalTableValue_NumberValue:
		return "number value"
	case *spb.EvalTableValue_StringValue:
		return "string value"
	case *spb.EvalTableValue_JsonValue:
		return "JSON value"
	case *spb.EvalTableValue_WandbMediaJson:
		return "W&B media value"
	default:
		return "value"
	}
}

func columnKind(column rowColumn) string {
	if column.mediaType != "" {
		return column.mediaType + " column"
	}
	return fmt.Sprintf("%q column", column.valueType)
}

func appendJSON(buf []byte, v any) ([]byte, error) {
	encoded, err := json.Marshal(v)
	if err != nil {
		return nil, err
	}
	return append(buf, encoded...), nil
}
