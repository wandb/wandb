package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/BurntSushi/toml"
	"github.com/segmentio/encoding/json"
	"gopkg.in/yaml.v3"
)

func loadConfigFile(configFile string) (interface{}, error) {
	// Load a yaml, json, or toml config file and return the parsed data structure.
	extension := strings.ToLower(filepath.Ext(configFile))
	var data interface{}
	data_bytes, err := os.ReadFile(configFile)
	if err != nil {
		return nil, err
	}
	switch extension {
	case ".yaml", ".yml":
		err = yaml.Unmarshal(data_bytes, &data)
	case ".json":
		err = json.Unmarshal(data_bytes, &data)
	case ".toml":
		err = toml.Unmarshal(data_bytes, &data)
	default:
		return nil, fmt.Errorf("unsupported file extension: %s", extension)
	}
	if err != nil {
		return nil, err
	}
	return data, nil
}

func filterDataStructure(ds map[string]interface{}, endpoints []string, filterIn bool) map[string]interface{} {
	if filterIn {
		// For filter in, start with an empty map and only add matching paths
		newDs := make(map[string]interface{})
		for _, endpoint := range endpoints {
			parts := strings.Split(endpoint, ".")
			addFilteredPath(newDs, ds, parts, 0, true)
		}
		return newDs
	} else {
		// For filter out, clone the ds and remove matching paths
		clonedDs := cloneMap(ds)
		for _, endpoint := range endpoints {
			parts := strings.Split(endpoint, ".")
			removeFilteredPath(clonedDs, parts, 0)
		}
		return clonedDs
	}
}

func cloneMap(original map[string]interface{}) map[string]interface{} {
	cloned := make(map[string]interface{})
	for key, value := range original {
		if subMap, ok := value.(map[string]interface{}); ok {
			cloned[key] = cloneMap(subMap)
		} else {
			cloned[key] = value
		}
	}
	return cloned
}

func removeFilteredPath(ds map[string]interface{}, parts []string, index int) {
	if index == len(parts)-1 {
		delete(ds, parts[index])
		return
	}
	if next, ok := ds[parts[index]].(map[string]interface{}); ok {
		removeFilteredPath(next, parts, index+1)
	}
}

func addFilteredPath(newDs, originalDs map[string]interface{}, parts []string, index int, add bool) {
	if add {
		if index < len(parts) {
			part := parts[index]
			if index == len(parts)-1 {
				// At endpoint, add the value
				newDs[part] = originalDs[part]
			} else {
				if _, ok := newDs[part]; !ok {
					newDs[part] = make(map[string]interface{})
				}
				if next, ok := originalDs[part].(map[string]interface{}); ok {
					addFilteredPath(newDs[part].(map[string]interface{}), next, parts, index+1, add)
				}
			}
		}
	}
}
