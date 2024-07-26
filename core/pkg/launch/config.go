package launch

import (
	"fmt"
	"os"
	"path/filepath"
	"slices"

	"github.com/wandb/simplejsonext"
	"gopkg.in/yaml.v3"
)

// ConfigDict is the Type representing a configuration tree.
type ConfigDict = map[string]interface{}

// ConfigPath is a key path determining a node in the run config tree.
type ConfigPath []string

// Config is a wrapper around a configuration tree that provides helpful methods.
//
// In launch, we use this to filter various configuration trees based on
// include and exclude paths. This allows users to specify which parts of the
// configuration tree they want to include in job inputs.
type Config struct {
	// The underlying configuration tree.
	tree ConfigDict
}

// PathMap is a flat representation of the configuration tree, where each path is
// a list of keys and the value is the value at that path in the tree.
//
// Note that this is a map of pointers to paths, not paths themselves. If you
// want to check if a path is in the map, you need to use the address of the
// path or iterate over the map and compare the paths.
type PathMap map[*ConfigPath]interface{}

// func NewConfig() *Config {
// 	return &Config{make(ConfigDict)}
// }

func NewConfigFrom(tree ConfigDict) *Config {
	return &Config{tree}
}

// Filters the configuration tree based on the given paths.
//
// include and exclude are lists of paths within the configuration tree. The
// resulting tree will contain only the paths that are included and not
// excluded. If include is empty, all paths are included. If exclude is empty,
// no paths are excluded.
func (runConfig *Config) filterTree(
	include []ConfigPath,
	exclude []ConfigPath,
) ConfigDict {
	pathMap := dictToPathMap(runConfig.tree)
	for _, path := range exclude {
		prunePath(pathMap, path)
	}
	if len(include) > 0 {
		for k := range pathMap {
			keep := false
			for _, path := range include {
				if pathHasPrefix(*k, path) {
					keep = true
					break
				}
			}
			if !keep {
				delete(pathMap, k)
			}
		}
	}
	return pathMapToDict(pathMap)
}

// Deserializes a run config file into a Config object.
//
// The file format is inferred from the file extension.
func deserializeConfig(path string) (*Config, error) {
	ext := filepath.Ext(path)
	contents, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	switch ext {
	case ".json":
		tree, err := simplejsonext.UnmarshalObject(contents)
		if err != nil {
			return nil, err
		}
		return NewConfigFrom(tree), nil
	case ".yaml", ".yml":
		var tree ConfigDict
		if err := yaml.Unmarshal(contents, &tree); err != nil {
			return nil, err
		}
		return NewConfigFrom(tree), nil
	default:
		return nil, fmt.Errorf("config: unknown file extension: %v", ext)
	}
}

// Checks if a given ConfigPath has a given prefix.
func pathHasPrefix(path ConfigPath, prefix ConfigPath) bool {
	if len(path) < len(prefix) {
		return false
	}
	for i, prefixPart := range prefix {
		if path[i] != prefixPart {
			return false
		}
	}
	return true
}

// Converts of paths to values to a nested dict.
func pathMapToDict(pathMap PathMap) ConfigDict {
	dict := make(ConfigDict)
	for path, value := range pathMap {
		err := updateAtPath(dict, *path, value)
		// This error only happens if we try to add a path that goes through
		// a leaf of the existing tree, which should never happen since this is
		// only ever called with paths that end in leaves of the tree.
		if err != nil {
			panic(err)
		}
	}
	return dict
}

// Converts a nested dict to a flat map of paths to values.
func dictToPathMap(dict ConfigDict) PathMap {
	pathMap := make(PathMap)
	flattenMap(dict, ConfigPath{}, pathMap)
	return pathMap
}

// Recursively constructs a flattened map of paths to values from a nested dict.
func flattenMap(input ConfigDict, path ConfigPath, output PathMap) {
	for k, v := range input {
		new_path := slices.Clone(path)
		new_path = append(new_path, k)
		switch v := v.(type) {
		case ConfigDict:
			flattenMap(v, new_path, output)
		default:
			output[&new_path] = v
		}
	}
}

// Prunes all paths starting with a given prefix from a PathMap.
func prunePath(input PathMap, prefix ConfigPath) {
	for k := range input {
		if pathHasPrefix(*k, prefix) {
			delete(input, k)
		}
	}
}

// Sets the value at the path in the config tree.
func updateAtPath(
	tree ConfigDict,
	path []string,
	value interface{},
) error {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree, err := getOrMakeSubtree(tree, pathPrefix)

	if err != nil {
		return err
	}

	subtree[key] = value
	return nil
}

// Returns the subtree at the path, creating it if necessary.
//
// Returns an error if there exists a non-map value at the path.
func getOrMakeSubtree(
	tree ConfigDict,
	path ConfigPath,
) (ConfigDict, error) {
	for _, key := range path {
		node, exists := tree[key]
		if !exists {
			node = make(ConfigDict)
			tree[key] = node
		}

		subtree, ok := node.(ConfigDict)
		if !ok {
			return nil, fmt.Errorf(
				"config: value at path %v is type %T, not a map",
				path,
				node,
			)
		}

		tree = subtree
	}

	return tree, nil
}
