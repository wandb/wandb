package historycodec

import (
	"fmt"
	"maps"
	"slices"
	"strings"
	"unicode/utf8"
)

// Normalize repairs strings and map keys throughout the closed value set
// accepted by Kind, rejecting unsupported types at any depth.
// It never mutates the input. Unchanged values are returned without
// allocation; only containers on a changed path are copied.
// If repaired keys collide, the lexically last original key wins.
func Normalize(v any) (any, error) {
	result, _, err := normalize(v)
	return result, err
}

func normalize(v any) (any, bool, error) {
	switch value := v.(type) {
	case nil, bool, int64, float64:
		return v, false, nil
	case string:
		if utf8.ValidString(value) {
			return v, false, nil
		}
		return NormalizeString(value), true, nil
	case []any:
		return normalizeSlice(v, value)
	case map[string]any:
		return normalizeMap(v, value)
	default:
		return nil, false, fmt.Errorf("historycodec: unsupported value type %T", v)
	}
}

func normalizeSlice(original any, values []any) (any, bool, error) {
	var result []any
	for i, v := range values {
		normalized, changed, err := normalize(v)
		if err != nil {
			return nil, false, err
		}
		if changed {
			if result == nil {
				result = slices.Clone(values)
			}
			result[i] = normalized
		}
	}
	if result == nil {
		return original, false, nil
	}
	return result, true, nil
}

func normalizeMap(original any, values map[string]any) (any, bool, error) {
	var result map[string]any
	keysChanged := false
	for key, v := range values {
		normalized, changed, err := normalize(v)
		if err != nil {
			return nil, false, err
		}
		if changed {
			if result == nil {
				result = maps.Clone(values)
			}
			result[key] = normalized
		}
		keysChanged = keysChanged || !utf8.ValidString(key)
	}
	if keysChanged {
		if result == nil {
			result = values
		}
		return normalizeKeys(result), true, nil
	}
	if result == nil {
		return original, false, nil
	}
	return result, true, nil
}

func normalizeKeys(values map[string]any) map[string]any {
	keys := make([]string, 0, len(values))
	for key := range values {
		keys = append(keys, key)
	}
	slices.Sort(keys)
	result := make(map[string]any, len(values))
	for _, key := range keys {
		result[NormalizeString(key)] = values[key]
	}
	return result
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
