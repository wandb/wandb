package implv4

import (
	"encoding/json"
)

func toJson(v interface{}) string {
	d, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return ""
	}
	return string(d)
}
