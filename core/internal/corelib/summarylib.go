package corelib

import (
	"fmt"

	// TODO: use simplejsonext for now until we replace the usage of json with
	// protocol buffer and proto json marshaler
	json "github.com/wandb/simplejsonext"
)

// Generic item which works with summary and history
type genericItem interface {
	GetKey() string
	GetNestedKey() []string
	GetValueJson() string
}

func JsonifyItems[V genericItem](items []V) (string, error) {
	jsonMap := make(map[string]interface{})

	for _, item := range items {
		value, err := json.Unmarshal([]byte(item.GetValueJson()))
		if err != nil {
			e := fmt.Errorf("json unmarshal error: %v, items: %v", err, item)
			return "", e
		}
		key := append([]string{item.GetKey()}, item.GetNestedKey()...)
		insertNested(jsonMap, key, value)
	}

	jsonBytes, err := json.Marshal(jsonMap)
	if err != nil {
		return "", err
	}
	return string(jsonBytes), nil
}

// insertNested inserts a value into a map based on a slice of keys representing the path
func insertNested(m map[string]interface{}, keys []string, value interface{}) {
	for i, key := range keys {
		if i == len(keys)-1 {
			m[key] = value
		} else {
			if _, ok := m[key]; !ok {
				m[key] = make(map[string]interface{})
			}
			m = m[key].(map[string]interface{})
		}
	}
}
