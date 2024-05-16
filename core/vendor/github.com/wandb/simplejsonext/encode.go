package simplejsonext

import (
	"bytes"
	"strings"
)

// Marshal writes the JSON representation of v to a byte slice returned in b.
func Marshal(v interface{}) (b []byte, err error) {
	var buf bytes.Buffer
	err = NewEmitter(&buf).Emit(v)
	if err != nil {
		return
	}
	return buf.Bytes(), nil
}

func MarshalToString(v interface{}) (s string, err error) {
	var sb strings.Builder
	err = NewEmitter(&sb).Emit(v)
	if err != nil {
		return
	}
	return sb.String(), nil
}
