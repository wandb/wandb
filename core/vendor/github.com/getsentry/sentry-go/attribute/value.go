// Adapted from https://github.com/open-telemetry/opentelemetry-go/blob/cc43e01c27892252aac9a8f20da28cdde957a289/attribute/value.go
//
// Copyright The OpenTelemetry Authors
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package attribute

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strconv"
)

// Type describes the type of the data Value holds.
type Type int // redefines builtin Type.

// Value represents the value part in key-value pairs.
type Value struct {
	vtype    Type
	numeric  uint64
	stringly string
	slice    any
}

const (
	// INVALID is used for a Value with no value set.
	INVALID Type = iota
	// BOOL is a boolean Type Value.
	BOOL
	// INT64 is a 64-bit signed integral Type Value.
	INT64
	// FLOAT64 is a 64-bit floating point Type Value.
	FLOAT64
	// STRING is a string Type Value.
	STRING
	// BOOLSLICE is a slice of booleans Type Value.
	BOOLSLICE
	// INT64SLICE is a slice of 64-bit signed integral numbers Type Value.
	INT64SLICE
	// FLOAT64SLICE is a slice of 64-bit floating point numbers Type Value.
	FLOAT64SLICE
	// STRINGSLICE is a slice of strings Type Value.
	STRINGSLICE
	// UINT64 is a 64-bit unsigned integral Type Value.
	//
	// This type is intentionally not exposed through the Builder API.
	UINT64
)

// BoolValue creates a BOOL Value.
func BoolValue(v bool) Value {
	return Value{
		vtype:   BOOL,
		numeric: boolToRaw(v),
	}
}

// BoolSliceValue creates a BOOLSLICE Value.
func BoolSliceValue(v []bool) Value {
	cp := reflect.New(reflect.ArrayOf(len(v), reflect.TypeFor[bool]())).Elem()
	reflect.Copy(cp, reflect.ValueOf(v))
	return Value{vtype: BOOLSLICE, slice: cp.Interface()}
}

// IntValue creates an INT64 Value.
func IntValue(v int) Value {
	return Int64Value(int64(v))
}

// IntSliceValue creates an INTSLICE Value.
func IntSliceValue(v []int) Value {
	cp := reflect.New(reflect.ArrayOf(len(v), reflect.TypeFor[int64]()))
	for i, val := range v {
		cp.Elem().Index(i).SetInt(int64(val))
	}
	return Value{
		vtype: INT64SLICE,
		slice: cp.Elem().Interface(),
	}
}

// Int64Value creates an INT64 Value.
func Int64Value(v int64) Value {
	return Value{
		vtype:   INT64,
		numeric: int64ToRaw(v),
	}
}

// Int64SliceValue creates an INT64SLICE Value.
func Int64SliceValue(v []int64) Value {
	cp := reflect.New(reflect.ArrayOf(len(v), reflect.TypeFor[int64]())).Elem()
	reflect.Copy(cp, reflect.ValueOf(v))
	return Value{vtype: INT64SLICE, slice: cp.Interface()}
}

// Float64Value creates a FLOAT64 Value.
func Float64Value(v float64) Value {
	return Value{
		vtype:   FLOAT64,
		numeric: float64ToRaw(v),
	}
}

// Float64SliceValue creates a FLOAT64SLICE Value.
func Float64SliceValue(v []float64) Value {
	cp := reflect.New(reflect.ArrayOf(len(v), reflect.TypeFor[float64]())).Elem()
	reflect.Copy(cp, reflect.ValueOf(v))
	return Value{vtype: FLOAT64SLICE, slice: cp.Interface()}
}

// StringValue creates a STRING Value.
func StringValue(v string) Value {
	return Value{
		vtype:    STRING,
		stringly: v,
	}
}

// StringSliceValue creates a STRINGSLICE Value.
func StringSliceValue(v []string) Value {
	cp := reflect.New(reflect.ArrayOf(len(v), reflect.TypeFor[string]())).Elem()
	reflect.Copy(cp, reflect.ValueOf(v))
	return Value{vtype: STRINGSLICE, slice: cp.Interface()}
}

// Uint64Value creates a UINT64 Value.
//
// This constructor is intentionally not exposed through the Builder API.
func Uint64Value(v uint64) Value {
	return Value{
		vtype:   UINT64,
		numeric: v,
	}
}

// Type returns a type of the Value.
func (v Value) Type() Type {
	return v.vtype
}

// AsBool returns the bool value. Make sure that the Value's type is
// BOOL.
func (v Value) AsBool() bool {
	return rawToBool(v.numeric)
}

// AsBoolSlice returns the []bool value. Make sure that the Value's type is
// BOOLSLICE.
func (v Value) AsBoolSlice() []bool {
	if v.vtype != BOOLSLICE {
		return nil
	}
	return asSlice[bool](v.slice)
}

// AsInt64 returns the int64 value. Make sure that the Value's type is
// INT64.
func (v Value) AsInt64() int64 {
	return rawToInt64(v.numeric)
}

// AsInt64Slice returns the []int64 value. Make sure that the Value's type is
// INT64SLICE.
func (v Value) AsInt64Slice() []int64 {
	if v.vtype != INT64SLICE {
		return nil
	}
	return asSlice[int64](v.slice)
}

// AsFloat64 returns the float64 value. Make sure that the Value's
// type is FLOAT64.
func (v Value) AsFloat64() float64 {
	return rawToFloat64(v.numeric)
}

// AsFloat64Slice returns the []float64 value. Make sure that the Value's type is
// FLOAT64SLICE.
func (v Value) AsFloat64Slice() []float64 {
	if v.vtype != FLOAT64SLICE {
		return nil
	}
	return asSlice[float64](v.slice)
}

// AsString returns the string value. Make sure that the Value's type
// is STRING.
func (v Value) AsString() string {
	return v.stringly
}

// AsStringSlice returns the []string value. Make sure that the Value's type is
// STRINGSLICE.
func (v Value) AsStringSlice() []string {
	if v.vtype != STRINGSLICE {
		return nil
	}
	return asSlice[string](v.slice)
}

// AsUint64 returns the uint64 value. Make sure that the Value's type is
// UINT64.
func (v Value) AsUint64() uint64 {
	return v.numeric
}

type unknownValueType struct{}

// AsInterface returns Value's data as interface{}.
func (v Value) AsInterface() interface{} {
	switch v.Type() {
	case BOOL:
		return v.AsBool()
	case BOOLSLICE:
		return v.AsBoolSlice()
	case INT64:
		return v.AsInt64()
	case INT64SLICE:
		return v.AsInt64Slice()
	case FLOAT64:
		return v.AsFloat64()
	case FLOAT64SLICE:
		return v.AsFloat64Slice()
	case STRING:
		return v.stringly
	case STRINGSLICE:
		return v.AsStringSlice()
	case UINT64:
		return v.numeric
	}
	return unknownValueType{}
}

// String returns a string representation of Value's data.
func (v Value) String() string {
	switch v.Type() {
	case BOOLSLICE:
		return fmt.Sprint(v.AsBoolSlice())
	case BOOL:
		return strconv.FormatBool(v.AsBool())
	case INT64SLICE:
		return fmt.Sprint(v.AsInt64Slice())
	case INT64:
		return strconv.FormatInt(v.AsInt64(), 10)
	case FLOAT64SLICE:
		return fmt.Sprint(v.AsFloat64Slice())
	case FLOAT64:
		return fmt.Sprint(v.AsFloat64())
	case STRINGSLICE:
		return fmt.Sprint(v.AsStringSlice())
	case STRING:
		return v.stringly
	case UINT64:
		return strconv.FormatUint(v.numeric, 10)
	default:
		return "unknown"
	}
}

// MarshalJSON returns the JSON encoding of the Value.
func (v Value) MarshalJSON() ([]byte, error) {
	var jsonVal struct {
		Value any    `json:"value"`
		Type  string `json:"type"`
	}
	jsonVal.Type = mapTypesToStr[v.Type()]
	jsonVal.Value = v.AsInterface()
	return json.Marshal(jsonVal)
}

func (t Type) String() string {
	switch t {
	case BOOL:
		return "bool"
	case BOOLSLICE:
		return "boolslice"
	case INT64:
		return "int64"
	case INT64SLICE:
		return "int64slice"
	case FLOAT64:
		return "float64"
	case FLOAT64SLICE:
		return "float64slice"
	case STRING:
		return "string"
	case STRINGSLICE:
		return "stringslice"
	case UINT64:
		return "uint64"
	}
	return "invalid"
}

// mapTypesToStr is a map from attribute.Type to the primitive types the server understands.
// https://develop.sentry.dev/sdk/foundations/data-model/attributes/#primitive-types
var mapTypesToStr = map[Type]string{
	INVALID:      "",
	BOOL:         "boolean",
	INT64:        "integer",
	FLOAT64:      "double",
	STRING:       "string",
	BOOLSLICE:    "array",
	INT64SLICE:   "array",
	FLOAT64SLICE: "array",
	STRINGSLICE:  "array",
	UINT64:       "integer", // wire format: same "integer" type
}
