package simplejsonext

import (
	"bytes"
	"strings"
)

// Marshal writes the JSON representation of the given value to a byte slice.
//
// The given value is expected to contain only supported types, which include:
// nil, bool, integers, floats, string, []byte (as a base64 encoded string),
// time.Time (written as an RFC3339 string), error (written as a string), and
// pointers/slices/string-keyed maps of supported types. If a type in v is not
// supported, an error will be returned.
func Marshal(v interface{}) (b []byte, err error) {
	var buf bytes.Buffer
	err = NewEmitter(&buf).Emit(v)
	if err != nil {
		return
	}
	return buf.Bytes(), nil
}

// MarshalToString writes the JSON representation of the given value to a
// string.
//
// The given value is expected to contain only supported types, which include:
// nil, bool, integers, floats, string, []byte (as a base64 encoded string),
// time.Time (written as an RFC3339 string), error (written as a string), and
// pointers/slices/string-keyed maps of supported types. If a type in v is not
// supported, an error will be returned.
func MarshalToString(v interface{}) (s string, err error) {
	var sb strings.Builder
	err = NewEmitter(&sb).Emit(v)
	if err != nil {
		return
	}
	return sb.String(), nil
}
