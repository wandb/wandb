package gqlmock

import json "github.com/wandb/simplejsonext"

// Converts a value to a map by marshalling to JSON and unmarshalling.
func jsonMarshallToMap(value any) (ret map[string]any) {
	bytes, err := json.Marshal(value)
	if err != nil {
		return nil
	}

	val, err := json.Unmarshal(bytes)
	ret = val.(map[string]any)
	if err != nil {
		return nil
	}

	return ret
}
