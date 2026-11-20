package historycodec

import (
	"bytes"
	"fmt"
	"math"
	"slices"
	"strconv"
	"strings"
	"unicode/utf8"
)

// AppendJSON appends W&B extended JSON for a normalized value to dst.
// Containers recursively accept the same types as Kind. Floats retain
// a decimal point or exponent, including inside containers, and NaN and
// infinities are bare literals. Map keys are sorted by their raw bytes.
// On error, dst may contain a partially encoded value.
func AppendJSON(dst []byte, v any) ([]byte, error) {
	switch v := v.(type) {
	case nil:
		return append(dst, "null"...), nil
	case bool:
		return strconv.AppendBool(dst, v), nil
	case int64:
		return strconv.AppendInt(dst, v, 10), nil
	case float64:
		return appendFloat(dst, v), nil
	case string:
		return AppendKey(dst, v), nil
	case []any:
		return appendArray(dst, v)
	case map[string]any:
		return appendObject(dst, v)
	default:
		return dst, fmt.Errorf("historycodec: unsupported value type %T", v)
	}
}

func appendArray(dst []byte, values []any) ([]byte, error) {
	dst = append(dst, '[')
	for i, v := range values {
		if i > 0 {
			dst = append(dst, ',')
		}
		var err error
		dst, err = AppendJSON(dst, v)
		if err != nil {
			return dst, err
		}
	}
	return append(dst, ']'), nil
}

func appendObject(dst []byte, values map[string]any) ([]byte, error) {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	dst = append(dst, '{')
	for i, key := range keys {
		if i > 0 {
			dst = append(dst, ',')
		}
		dst = AppendKey(dst, key)
		dst = append(dst, ':')
		var err error
		dst, err = AppendJSON(dst, values[key])
		if err != nil {
			return dst, err
		}
	}
	return append(dst, '}'), nil
}

// AppendKey appends a quoted JSON string, repairing each invalid UTF-8
// byte with U+FFFD. Non-ASCII characters are not escaped.
func AppendKey(dst []byte, key string) []byte {
	key = NormalizeString(key)
	dst = append(dst, '"')
	for i := 0; i < len(key); i++ {
		dst = appendStringByte(dst, key[i])
	}
	return append(dst, '"')
}

func appendStringByte(dst []byte, b byte) []byte {
	switch b {
	case '"', '\\':
		return append(dst, '\\', b)
	case '\b':
		return append(dst, '\\', 'b')
	case '\f':
		return append(dst, '\\', 'f')
	case '\n':
		return append(dst, '\\', 'n')
	case '\r':
		return append(dst, '\\', 'r')
	case '\t':
		return append(dst, '\\', 't')
	default:
		if b < 0x20 {
			const hex = "0123456789abcdef"
			return append(dst, '\\', 'u', '0', '0', hex[b>>4], hex[b&15])
		}
		return append(dst, b)
	}
}

// NormalizeString replaces each invalid UTF-8 byte with U+FFFD.
// Valid strings are returned unchanged without allocation.
func NormalizeString(s string) string {
	if utf8.ValidString(s) {
		return s
	}
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		b.WriteRune(r)
	}
	return b.String()
}

func appendFloat(dst []byte, f float64) []byte {
	switch {
	case math.IsNaN(f):
		return append(dst, "NaN"...)
	case math.IsInf(f, 1):
		return append(dst, "Infinity"...)
	case math.IsInf(f, -1):
		return append(dst, "-Infinity"...)
	}
	start := len(dst)
	dst = strconv.AppendFloat(dst, f, 'g', -1, 64)
	if !bytes.ContainsAny(dst[start:], ".eE") {
		dst = append(dst, ".0"...)
	}
	return dst
}
