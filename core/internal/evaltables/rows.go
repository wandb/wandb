package evaltables

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"strconv"
	"unicode/utf8"

	"github.com/wandb/wandb/core/internal/runbranch"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// rowColumn is a column of an EvalTable row's input, output, or scores.
type rowColumn struct {
	name string

	// key is the column's JSON object key, with its colon.
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

// newRowEncoder returns an encoder for the request's rows.
//
// The request's columns must have passed validateColumns.
func newRowEncoder(
	request *spb.UploadEvalTableRequest,
	runPath runbranch.RunPath,
) *rowEncoder {
	e := &rowEncoder{media: &mediaConverter{runPath: runPath}}

	for _, field := range request.GetDatasetFields() {
		column := newRowColumn(
			field.GetName(), field.GetValueType(), field.GetWandbMediaType())

		// validateColumns checked that the source is "input" or "output".
		if field.GetSource() == "input" {
			e.inputs = append(e.inputs, column)
		} else {
			e.outputs = append(e.outputs, column)
		}
	}

	for _, scorer := range request.GetScorers() {
		e.scores = append(e.scores,
			newRowColumn(scorer.GetName(), scorer.GetValueType(), ""))
	}

	return e
}

func newRowColumn(name, valueType, mediaType string) rowColumn {
	return rowColumn{
		name:      name,
		key:       append(appendJSONString(nil, name), ':'),
		valueType: valueType,
		mediaType: mediaType,
	}
}

// encodeRows returns the CES row JSON of the request's rows.
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
		buf = appendJSONString(buf, exampleKey)
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

// appendValues appends an object of the columns' values.
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
		return appendJSONFloat(buf, value.NumberValue)
	case *spb.EvalTableValue_StringValue:
		return appendJSONString(buf, value.StringValue), nil
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

// valueKind describes a value's type for errors.
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

// columnKind describes a column's type for errors.
func columnKind(column rowColumn) string {
	if column.mediaType != "" {
		return column.mediaType + " column"
	}
	return fmt.Sprintf("%q column", column.valueType)
}

// appendJSONFloat appends f as encoding/json would encode it.
func appendJSONFloat(buf []byte, f float64) ([]byte, error) {
	if math.IsNaN(f) || math.IsInf(f, 0) {
		return nil, fmt.Errorf("unsupported number %v", f)
	}

	format := byte('f')
	if abs := math.Abs(f); abs != 0 && (abs < 1e-6 || abs >= 1e21) {
		format = 'e'
	}
	buf = strconv.AppendFloat(buf, f, format, -1, 64)

	if format == 'e' {
		// Shorten e-09 to e-9, like encoding/json.
		n := len(buf)
		if n >= 4 && buf[n-4] == 'e' && buf[n-3] == '-' && buf[n-2] == '0' {
			buf[n-2] = buf[n-1]
			buf = buf[:n-1]
		}
	}
	return buf, nil
}

// appendJSONString appends s as a JSON string, escaped as encoding/json
// escapes it without HTML escaping.
func appendJSONString(buf []byte, s string) []byte {
	const hex = "0123456789abcdef"

	buf = append(buf, '"')
	start := 0
	for i := 0; i < len(s); {
		if b := s[i]; b < utf8.RuneSelf {
			if b >= 0x20 && b != '"' && b != '\\' {
				i++
				continue
			}

			buf = append(buf, s[start:i]...)
			switch b {
			case '"', '\\':
				buf = append(buf, '\\', b)
			case '\b':
				buf = append(buf, '\\', 'b')
			case '\f':
				buf = append(buf, '\\', 'f')
			case '\n':
				buf = append(buf, '\\', 'n')
			case '\r':
				buf = append(buf, '\\', 'r')
			case '\t':
				buf = append(buf, '\\', 't')
			default:
				buf = append(buf, '\\', 'u', '0', '0', hex[b>>4], hex[b&0xf])
			}
			i++
			start = i
			continue
		}

		r, size := utf8.DecodeRuneInString(s[i:])
		switch {
		case r == utf8.RuneError && size == 1:
			buf = append(buf, s[start:i]...)
			buf = append(buf, `�`...)
		case r == ' ' || r == ' ':
			// Valid JSON, but not valid JavaScript.
			buf = append(buf, s[start:i]...)
			buf = append(buf, '\\', 'u', '2', '0', '2', hex[r&0xf])
		default:
			i += size
			continue
		}
		i += size
		start = i
	}
	buf = append(buf, s[start:]...)
	return append(buf, '"')
}
