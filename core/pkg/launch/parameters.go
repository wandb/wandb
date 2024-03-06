package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

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
	default:
		return nil, fmt.Errorf("unsupported file extension: %s", extension)
	}
	if err != nil {
		return nil, err
	}
	return data, nil
}

func parseNestedPath(path string) []string {
	// Split a path in a nested data structure into its components. The path is
	// a string of the form key.key.index that specifies a path within a nested
	// data structure. '.' is used as the separator unless it is escaped with a
	// backslash.
	var separators []int
	for i, c := range path {
		if c == '.' {
			if i == 0 || path[i-1] != '\\' {
				separators = append(separators, i)
			}
		}
	}
	components := make([]string, len(separators)+1)
	start := 0
	for i, sep := range separators {
		components[i] = path[start:sep]
		start = sep + 1
	}
	components[len(separators)] = path[start:]
	for i, comp := range components {
		components[i] = strings.ReplaceAll(comp, "\\.", ".")
	}
	return components
}

func filterInPaths(data interface{}, endpoints []string) (interface{}, error) {
	// Return a new interface that only includes the specified endpoints from the data.
	// The endpoints are specified as a list of strings of the form key.key.index
	// that specify paths within a nested data structure. '.' is used as the separator
	// unless it is escaped with a backslash.
	if len(endpoints) == 0 {
		return data, nil
	}
	var err error
	var new_data interface{}
	switch data.(type) {
	case map[string]interface{}:
		new_data = make(map[string]interface{})
	}
	if new_data == nil {
		return nil, fmt.Errorf("unsupported data type: %T", data)
	}
	for _, endpoint := range endpoints {
		components := parseNestedPath(endpoint)
		new_data, err = filterIn(data, new_data, components)
		if err != nil {
			return nil, err
		}
	}
	return new_data, nil
}

func filterIn(data interface{}, new_data interface{}, components []string) (interface{}, error) {
	// Return a new interface that only includes the specified components from the data.
	// The components are specified as a list of strings that specify paths within
	// a nested data structure.
	if len(components) == 0 {
		return data, nil
	}
	var err error
	switch data := data.(type) {
	case map[string]interface{}:
		var new_data_map map[string]interface{}
		if new_data == nil {
			new_data_map = make(map[string]interface{})
		} else {
			new_data_map = new_data.(map[string]interface{})
		}
		if len(components) == 1 {
			new_data_map[components[0]] = data[components[0]]
		} else {
			if _, ok := data[components[0]]; !ok {
				return data, fmt.Errorf("missing key: %s", components[0])
			}
			new_data_map[components[0]], err = filterIn(data[components[0]], new_data_map[components[0]], components[1:])
			if err != nil {
				return data, err
			}
		}
		return new_data_map, nil
	default:
		return data, nil
	}
}

func filterOutPaths(data interface{}, endpoints []string) (interface{}, error) {
	// Filter out the specified endpoints from the data structure.
	// The endpoints are specified as a list of strings of the form key.key.index
	// that specify paths within a nested data structure. '.' is used as the separator
	// unless it is escaped with a backslash.
	// The data structure is modified in place.
	if len(endpoints) == 0 {
		return data, nil
	}
	var filtered_data = data
	var err error
	for _, endpoint := range endpoints {
		components := parseNestedPath(endpoint)
		filtered_data, err = filterOut(data, components)
		if err != nil {
			return nil, err
		}
	}
	return filtered_data, nil
}

func filterOut(data interface{}, components []string) (interface{}, error) {
	// Filter out the specified components from the data structure.
	// The components are specified as a list of strings that specify paths within
	// a nested data structure.
	if len(components) == 0 {
		return data, nil
	}
	var filtered_data interface{}
	var err error
	switch data := data.(type) {
	case map[string]interface{}:
		if len(components) == 1 {
			delete(data, components[0])
		} else {
			if _, ok := data[components[0]]; !ok {
				return data, fmt.Errorf("missing key: %s", components[0])
			}
			filtered_data, err = filterOut(data[components[0]], components[1:])
			if err != nil {
				return data, err
			}
			data[components[0]] = filtered_data
		}
	default:
		return data, nil
	}
	return data, nil
}
