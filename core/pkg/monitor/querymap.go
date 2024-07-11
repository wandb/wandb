package monitor

// queryMapNumber reads a number-valued property from a JSON object.
//
// Returns 0 and false if the key is not found or isn't a number.
func queryMapNumber(jsonObj map[string]any, key string) (float64, bool) {
	value, exists := jsonObj[key]
	if !exists {
		return 0, false
	}

	// encoding/json returns all numbers as float64.
	switch x := value.(type) {
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
