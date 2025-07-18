package api

import (
	"encoding/json"
	"strings"
)

// ErrorFromWBResponse extracts an error string from the response body if it is
// in one of the usual formats returned by the W&B backend.
//
// If multiple errors are found, they are joined with a semicolon.
func ErrorFromWBResponse(body []byte) string {
	var resp any

	err := json.Unmarshal(body, &resp)
	if err != nil {
		return ""
	}

	respMap, ok := resp.(map[string]any)
	if !ok {
		return ""
	}

	errorField, exists := respMap["error"]
	if exists {
		return errorFromStringOrMap(errorField)
	}

	errorsField := respMap["errors"]
	if errorsFieldList, ok := errorsField.([]any); ok {
		var messages []string

		for _, errorValue := range errorsFieldList {
			errorMessage := errorFromStringOrMap(errorValue)
			if len(errorMessage) > 0 {
				messages = append(messages, errorMessage)
			}
		}

		return strings.Join(messages, "; ")
	}

	return ""
}

// errorFromStringOrMap extracts an error message from an error value returned
// by the W&B backend.
//
// Backend errors are returned in one of two ways:
// - A string containing the error message
// - A JSON object with a "message" field that is a string
func errorFromStringOrMap(value any) string {
	switch x := value.(type) {
	case string:
		return x
	case map[string]any:
		message := x["message"]
		if messageStr, ok := message.(string); ok {
			return messageStr
		}
	}

	return ""
}
