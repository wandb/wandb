package cliutil

import (
	"strconv"
	"strings"
)

// ConvertConfigArrayToNestedMap converts a flat key-value map with dot notation
// paths into a nested map[string]interface{} structure. It handles conversion
// of string values to numbers and booleans where appropriate.
func ConvertConfigArrayToNestedMap(configArray map[string]string) map[string]interface{} {
	config := make(map[string]interface{})
	for path, value := range configArray {
		segments := strings.Split(path, ".")
		current := config
		for i, segment := range segments {
			if i == len(segments)-1 {
				if num, err := strconv.ParseFloat(value, 64); err == nil {
					current[segment] = num
				} else if value == "true" {
					current[segment] = true
				} else if value == "false" {
					current[segment] = false
				} else {
					current[segment] = value
				}
			} else {
				// Create nested map if it doesn't exist
				if _, exists := current[segment]; !exists {
					current[segment] = make(map[string]interface{})
				}
				// Move to next level
				current = current[segment].(map[string]interface{})
			}
		}
	}
	return config
}

func StringPtr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}

func MetadataPtr(m map[string]string) *map[string]string {
	if len(m) == 0 {
		return nil
	}
	return &m
}

func ConfigPtr(c map[string]interface{}) *map[string]interface{} {
	if len(c) == 0 {
		return nil
	}
	return &c
}
