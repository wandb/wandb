package gqlmock

import "encoding/json"

// Converts a value to a map by marshalling to JSON and unmarshalling.
func jsonMarshallToMap(value any) (ret map[string]any) {
	bytes, err := json.Marshal(value)
	if err != nil {
		return nil
	}

	err = json.Unmarshal(bytes, &ret)
	if err != nil {
		return nil
	}

	return ret
}
