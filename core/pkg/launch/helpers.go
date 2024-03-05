package launch

import (
	"fmt"
	"strconv"
	"strings"
)

func splitEndpoint(endpoint string) []string {
	// Split an endpoint into its components. The endpoint is a string of the form
	// key.key.index that specifies a path within a nested data structure. '.' is
	// used as the separator unless it is escaped with a backslash.
	var separators []int
	for i, c := range endpoint {
		if c == '.' {
			if i == 0 || endpoint[i-1] != '\\' {
				separators = append(separators, i)
			}
		}
	}
	components := make([]string, len(separators)+1)
	start := 0
	for i, sep := range separators {
		components[i] = endpoint[start:sep]
		start = sep + 1
	}
	components[len(separators)] = endpoint[start:]
	for i, comp := range components {
		components[i] = strings.ReplaceAll(comp, "\\.", ".")
	}
	return components
}

func filterInEndpoints(data interface{}, endpoints []string) (interface{}, error) {
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
	case []interface{}:
		new_data = make([]interface{}, 0)
	}
	if new_data == nil {
		return nil, fmt.Errorf("unsupported data type: %T", data)
	}
	for _, endpoint := range endpoints {
		components := splitEndpoint(endpoint)
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
	case []interface{}:
		var new_data_list []interface{}
		if new_data == nil {
			new_data_list = make([]interface{}, 0)
		} else {
			new_data_list = new_data.([]interface{})
		}
		index, err := parseIndex(components[0], len(data))
		if err != nil {
			return data, err
		}
		if len(components) == 1 {
			new_data_list = append(new_data_list, data[index])
		} else {
			new_data_list = append(new_data_list, nil)
			result, err := filterIn(data[index], new_data_list[index], components[1:])
			if err != nil {
				return data, err
			}
			new_data_list[index] = result
		}
		return new_data_list, nil
	default:
		return data, nil
	}
}

func filterOutEndpoints(data interface{}, endpoints []string) (interface{}, error) {
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
		components := splitEndpoint(endpoint)
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
	case []interface{}:
		index, err := parseIndex(components[0], len(data))
		if err != nil {
			return data, err
		}
		if len(components) == 1 {
			return append(data[:index], data[index+1:]...), nil
		} else {
			filtered_data, err = filterOut(data[index], components[1:])
			if err != nil {
				return data, err
			}
			data[index] = filtered_data
			return data, nil
		}
	default:
		return data, nil
	}
	return data, nil
}

func parseIndex(s string, max int) (int, error) {
	// Parse an index string and return the corresponding integer.
	// The index string can be a positive integer or the string "end" to indicate
	// the last index. Negative integers are not allowed.
	if s == "end" {
		return max - 1, nil
	}
	index, err := strconv.Atoi(s)
	if err != nil {
		return 0, err
	}
	if index < 0 {
		return 0, fmt.Errorf("negative index: %d", index)
	}
	if index >= max {
		return 0, fmt.Errorf("index out of range: %d", index)
	}
	return index, nil
}
