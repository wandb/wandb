package validator

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"reflect"
	"strconv"
	"strings"

	"github.com/vektah/gqlparser/v2/ast"
	"github.com/vektah/gqlparser/v2/gqlerror"
)

//nolint:staticcheck // We do not care about capitalized error strings
var ErrUnexpectedType = errors.New("Unexpected Type")

// VariableValues coerces and validates variable values.
func VariableValues(
	schema *ast.Schema,
	op *ast.OperationDefinition,
	variables map[string]any,
) (map[string]any, error) {
	coercedVars := map[string]any{}

	validator := varValidator{
		path:   ast.Path{ast.PathName("variable")},
		schema: schema,
	}

	for _, v := range op.VariableDefinitions {
		validator.path = append(validator.path, ast.PathName(v.Variable))

		if !v.Definition.IsInputType() {
			return nil, gqlerror.ErrorPathf(validator.path, "must an input type")
		}

		val, hasValue := variables[v.Variable]

		if !hasValue {
			if v.DefaultValue != nil {
				var err error
				val, err = v.DefaultValue.Value(nil)
				if err != nil {
					return nil, gqlerror.WrapPath(validator.path, err)
				}
				hasValue = true
			} else if v.Type.NonNull {
				return nil, gqlerror.ErrorPathf(validator.path, "must be defined")
			}
		}

		if hasValue {
			if val == nil {
				if v.Type.NonNull {
					return nil, gqlerror.ErrorPathf(validator.path, "cannot be null")
				}
				coercedVars[v.Variable] = nil
			} else {
				rv := reflect.ValueOf(val)

				jsonNumber, isJSONNumber := val.(json.Number)
				if isJSONNumber {
					switch v.Type.NamedType {
					case "Int":
						n, err := jsonNumber.Int64()
						if err != nil {
							return nil, gqlerror.ErrorPathf(
								validator.path,
								"cannot use value %d as %s",
								n,
								v.Type.NamedType,
							)
						}
						rv = reflect.ValueOf(n)
					case "Float":
						f, err := jsonNumber.Float64()
						if err != nil {
							return nil, gqlerror.ErrorPathf(
								validator.path,
								"cannot use value %f as %s",
								f,
								v.Type.NamedType,
							)
						}
						rv = reflect.ValueOf(f)
					}
				}
				if rv.Kind() == reflect.Pointer || rv.Kind() == reflect.Interface {
					rv = rv.Elem()
				}

				rval, err := validator.validateVarType(v.Type, rv)
				if err != nil {
					return nil, err
				}
				coercedVars[v.Variable] = rval.Interface()
			}
		}

		validator.path = validator.path[0 : len(validator.path)-1]
	}
	return coercedVars, nil
}

type varValidator struct {
	path   ast.Path
	schema *ast.Schema
}

func (v *varValidator) validateVarType(
	typ *ast.Type,
	val reflect.Value,
) (reflect.Value, *gqlerror.Error) {
	currentPath := v.path
	resetPath := func() {
		v.path = currentPath
	}
	defer resetPath()

	if !val.IsValid() {
		if typ.NonNull {
			return val, gqlerror.ErrorPathf(v.path, "cannot be null")
		}
		return val, nil
	}

	if typ.Elem != nil {
		if val.Kind() != reflect.Slice {
			// GraphQL spec says that non-null values should be coerced to an array when possible.
			// Hence if the value is not a slice, we create a slice and add val to it.
			slc := reflect.MakeSlice(reflect.SliceOf(val.Type()), 0, 0)
			slc = reflect.Append(slc, val)
			val = slc
		}
		for i := 0; i < val.Len(); i++ {
			resetPath()
			v.path = append(v.path, ast.PathIndex(i))
			field := val.Index(i)
			if field.Kind() == reflect.Pointer || field.Kind() == reflect.Interface {
				if typ.Elem.NonNull && field.IsNil() {
					return val, gqlerror.ErrorPathf(v.path, "cannot be null")
				}
				field = field.Elem()
			}
			cval, err := v.validateVarType(typ.Elem, field)
			if err != nil {
				return val, err
			}
			// Like the input object case below, this writes the coerced value
			// into the caller's slice.
			if canStore(val.Type().Elem(), cval) {
				val.Index(i).Set(cval)
			}
		}
		return val, nil
	}
	def := v.schema.Types[typ.NamedType]
	if def == nil {
		panic(fmt.Errorf("missing def for %s", typ.NamedType))
	}

	switch def.Kind {
	case ast.Enum:
		kind := val.Type().Kind()
		if kind != reflect.Int && kind != reflect.Int32 && kind != reflect.Int64 &&
			kind != reflect.String {
			return val, gqlerror.ErrorPathf(v.path, "enums must be ints or strings")
		}
		isValidEnum := false
		for _, enumVal := range def.EnumValues {
			if strings.EqualFold(val.String(), enumVal.Name) {
				isValidEnum = true
			}
		}
		if !isValidEnum {
			return val, gqlerror.ErrorPathf(v.path, "%s is not a valid %s", val.String(), def.Name)
		}
		return val, nil
	case ast.Scalar:
		kind := val.Type().Kind()
		switch typ.NamedType {
		case "Int":
			switch kind {
			case reflect.Int, reflect.Int32, reflect.Int64:
				return val, nil
			case reflect.Float32, reflect.Float64:
				// A JSON integer decoded into an `any` is a float64. Reject a
				// fractional one, as VariableValues does for a json.Number.
				if isWholeNumber(val.Float()) {
					return val, nil
				}
			case reflect.String:
				if IsValidIntString(val, kind) {
					return val, nil
				}
			}
		case "Float":
			if kind == reflect.Float32 || kind == reflect.Float64 || kind == reflect.Int ||
				kind == reflect.Int32 ||
				kind == reflect.Int64 ||
				IsValidFloatString(val, kind) {
				return val, nil
			}
		case "String":
			if kind == reflect.String {
				return val, nil
			}

		case "Boolean":
			if kind == reflect.Bool {
				return val, nil
			}

		case "ID":
			switch kind {
			case reflect.Int, reflect.Int32, reflect.Int64, reflect.String:
				return val, nil
			case reflect.Float32, reflect.Float64:
				return v.coerceFloatID(val)
			}
		default:
			// assume custom scalars are ok
			return val, nil
		}
		return val, gqlerror.ErrorPathf(v.path, "cannot use %s as %s", kind.String(), typ.NamedType)
	case ast.InputObject:
		if val.Kind() != reflect.Map {
			return val, gqlerror.ErrorPathf(v.path, "must be a %s, not a %s", def.Name, val.Kind())
		}

		// check for unknown fields
		for _, name := range val.MapKeys() {
			val.MapIndex(name)
			fieldDef := def.Fields.ForName(name.String())
			resetPath()
			v.path = append(v.path, ast.PathName(name.String()))

			switch {
			case name.String() == "__typename":
				continue
			case fieldDef == nil:
				return val, gqlerror.ErrorPathf(v.path, "unknown field")
			}
		}

		for _, fieldDef := range def.Fields {
			resetPath()
			v.path = append(v.path, ast.PathName(fieldDef.Name))

			field := val.MapIndex(reflect.ValueOf(fieldDef.Name))
			if !field.IsValid() {
				if fieldDef.Type.NonNull {
					if fieldDef.DefaultValue != nil {
						var err error
						_, err = fieldDef.DefaultValue.Value(nil)
						if err == nil {
							continue
						}
					}
					return val, gqlerror.ErrorPathf(v.path, "must be defined")
				}
				continue
			}

			if field.Kind() == reflect.Pointer || field.Kind() == reflect.Interface {
				if fieldDef.Type.NonNull && field.IsNil() {
					return val, gqlerror.ErrorPathf(v.path, "cannot be null")
				}
				// allow null object field and skip it
				if !fieldDef.Type.NonNull && field.IsNil() {
					continue
				}
				field = field.Elem()
			}
			cval, err := v.validateVarType(fieldDef.Type, field)
			if err != nil {
				return val, err
			}
			if canStore(val.Type().Elem(), cval) {
				val.SetMapIndex(reflect.ValueOf(fieldDef.Name), cval)
			}
		}
	default:
		panic(fmt.Errorf("unsupported type %s", def.Kind))
	}
	return val, nil
}

func IsValidIntString(val reflect.Value, kind reflect.Kind) bool {
	if kind != reflect.String {
		return false
	}
	_, e := strconv.ParseInt(fmt.Sprintf("%v", val.Interface()), 10, 64)

	return e == nil
}

func IsValidFloatString(val reflect.Value, kind reflect.Kind) bool {
	if kind != reflect.String {
		return false
	}
	_, e := strconv.ParseFloat(fmt.Sprintf("%v", val.Interface()), 64)
	return e == nil
}

// canStore reports whether the coerced value cval can be written back into a
// container element of type elem. A typed container such as []float64 cannot
// hold an ID coerced to int64, and a []*string element cannot hold the string
// it was dereferenced to, so those keep their original element.
func canStore(elem reflect.Type, cval reflect.Value) bool {
	return cval.IsValid() && cval.Type().AssignableTo(elem)
}

// maxSafeFloatInt is 2^53-1, the largest integer n for which float64(n) cannot
// be the rounded result of a different integer (JavaScript's
// Number.MAX_SAFE_INTEGER). float64(2^53) is ambiguous: 2^53+1 rounds to it.
const maxSafeFloatInt = 1<<53 - 1

// isWholeNumber reports whether f is finite and has no fractional part.
func isWholeNumber(f float64) bool {
	return !math.IsInf(f, 0) && f == math.Trunc(f)
}

// coerceFloatID coerces a float ID variable to an int64.
//
// Decoding JSON into an `any` without json.Decoder.UseNumber turns an integer
// ID such as {"id": 4} into float64(4). The spec accepts an integer for ID, so
// it is accepted here, but returned as int64: consumers format a float64 ID
// with a fractional part (gqlgen's UnmarshalID yields "4.000000").
//
// Requires: val is a Float32 or Float64 value.
// Ensures:  returns int64(val) when val is a whole number no larger in
// magnitude than maxSafeFloatInt; otherwise returns an error at v.path.
func (v *varValidator) coerceFloatID(val reflect.Value) (reflect.Value, *gqlerror.Error) {
	f := val.Float()
	if !isWholeNumber(f) {
		return val, gqlerror.ErrorPathf(v.path, "cannot use %s as ID", val.Kind())
	}
	if math.Abs(f) > maxSafeFloatInt {
		return val, gqlerror.ErrorPathf(
			v.path,
			"cannot use %g as ID: integers beyond 2^53-1 may have been rounded; "+
				"decode variables with json.Decoder.UseNumber",
			f,
		)
	}
	return reflect.ValueOf(int64(f)), nil
}
