package launch

import (
	"fmt"
	"strings"
)

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

func filterOutPaths(data interface{}, paths []string) error {
	// Filter out the specified paths from the data structure. The paths are
	// specified as a list of strings of the form key.key.index that specify
	// paths within a nested data structure. '.' is used as the separator unless
	// it is escaped with a backslash. The data structure is modified in place.
	if len(paths) == 0 {
		return nil
	}
	var err error
	for _, path := range paths {
		components := parseNestedPath(path)
		err = filterOut(data, components)
		if err != nil {
			return err
		}
	}
	return nil
}

func filterOut(data interface{}, components []string) error {
	// Filter out the specified components from the data structure. The components
	// are specified as a list of strings that specify paths within a nested data
	// structure.
	if len(components) == 0 {
		return nil
	}
	var err error
	switch data := data.(type) {
	case map[string]interface{}:
		if len(components) == 1 {
			delete(data, components[0])
		} else {
			if _, ok := data[components[0]]; !ok {
				return fmt.Errorf("missing key: %s", components[0])
			}
			err = filterOut(data[components[0]], components[1:])
			if err != nil {
				return err
			}
		}
	default:
		return nil
	}
	return nil
}

func filterInPaths(data interface{}, paths []string) (interface{}, error) {
	// Return a new interface that only includes the specified paths from the data.
	if len(paths) == 0 {
		return data, nil
	}
	var new_data interface{}
	var err error
	for _, path := range paths {
		components := parseNestedPath(path)
		new_data, err = filterIn(data, new_data, components)
		if err != nil {
			return nil, err
		}
	}
	return new_data, nil
}

func filterIn(data interface{}, new_data interface{}, components []string) (interface{}, error) {
	// Return a new interface that only includes the specified components from the data.
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
