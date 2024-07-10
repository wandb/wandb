package monitor

// queryMapNumber reads a number-valued property from a JSON object.
//
// Returns 0 and false if the key is not found or isn't a number.
func queryMapNumber(jsonObj map[string]any, key string) (float64, bool) {
	value, exists := jsonObj[key]
	if !exists {
		return 0, false
	}

	// simplejsonext returns all numbers as int64 or float64.
	switch x := value.(type) {
	case int64:
		return float64(x), true
	case float64:
		return x, true
	default:
		return 0, false
	}
}

// queryMapString reads a string-valued property from a JSON object.
//
// Returns 0 and false if the key is not found or has the wrong type.
func queryMapString(jsonObj map[string]any, key string) (string, bool) {
	value, exists := jsonObj[key]
	if !exists {
		return "", false
	}

	str, ok := value.(string)
	return str, ok
}
