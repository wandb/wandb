package runconfig

import (
	"fmt"
	"os"
	"path/filepath"

	"github.com/segmentio/encoding/json"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/pkg/service"
	"gopkg.in/yaml.v3"
)

// A RunConfig representation.
//
// This is a type alias for refactoring purposes; it should be new type
// otherwise.
type RunConfigDict = map[string]interface{}

// A key path determining a node in the run config tree.
type RunConfigPath []string

// The configuration of a run.
//
// This is usually used for hyperparameters and some run metadata like the
// start time and the ML framework used. In a somewhat hacky way, it is also
// used to store programmatic custom charts for the run and various other
// things.
//
// The server process builds this up incrementally throughout a run's lifetime.
type RunConfig struct {
	// The underlying configuration tree.
	//
	// Nodes are strings and leaves are types supported by JSON,
	// such as primitives and lists.
	tree RunConfigDict
}

type PathMap map[*RunConfigPath]interface{}

type ConfigFormat int

const (
	FormatYaml ConfigFormat = iota
	FormatJson
)

func New() *RunConfig {
	return &RunConfig{make(RunConfigDict)}
}

func NewFrom(tree RunConfigDict) *RunConfig {
	return &RunConfig{tree}
}

func NewFromConfigFile(path string) (*RunConfig, error) {
	ext := filepath.Ext(path)
	contents, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	switch ext {
	case ".json":
		var tree RunConfigDict
		if err := json.Unmarshal(contents, &tree); err != nil {
			return nil, err
		}
		return NewFrom(tree), nil
	case ".yaml", ".yml":
		var tree RunConfigDict
		if err := yaml.Unmarshal(contents, &tree); err != nil {
			return nil, err
		}
		return NewFrom(tree), nil
	default:
		return nil, fmt.Errorf("config: unknown file extension: %v", ext)
	}
}

// Returns the underlying config tree.
//
// Provided temporarily as part of a refactor. Avoid using this, especially
// mutating it.
func (runConfig *RunConfig) Tree() RunConfigDict {
	return runConfig.tree
}

// Makes and returns a deep copy of the underlying tree.
func (runConfig *RunConfig) CloneTree() RunConfigDict {
	clone, err := deepCopy(runConfig.tree)
	if err != nil {
		panic(fmt.Errorf("config: failed to clone tree: %v", err))
	}
	return *clone
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (runConfig *RunConfig) ApplyChangeRecord(
	configRecord *service.ConfigRecord,
	onError func(error),
) {
	for _, configItem := range configRecord.Update {
		path := keyPath(configItem)

		var value interface{}
		if err := json.Unmarshal(
			[]byte(configItem.GetValueJson()),
			&value,
		); err != nil {
			onError(
				fmt.Errorf(
					"config: failed to unmarshall JSON for config key %v: %v",
					path,
					err,
				),
			)
			continue
		}

		if err := updateAtPath(runConfig.tree, path, value); err != nil {
			onError(err)
			continue
		}
	}

	for _, configItem := range configRecord.Remove {
		runConfig.removeAtPath(keyPath(configItem))
	}
}

// Inserts W&B-internal values into the run's configuration.
func (runConfig *RunConfig) AddTelemetryAndMetrics(
	telemetry *service.TelemetryRecord,
	metrics []map[int]interface{},
) {
	wandbInternal := runConfig.internalSubtree()

	if telemetry.GetCliVersion() != "" {
		wandbInternal["cli_version"] = telemetry.CliVersion
	}
	if telemetry.GetPythonVersion() != "" {
		wandbInternal["python_version"] = telemetry.PythonVersion
	}

	wandbInternal["t"] = corelib.ProtoEncodeToDict(telemetry)

	if metrics != nil {
		wandbInternal["m"] = metrics
	}
}

// Incorporates the config from a run that's being resumed.
func (runConfig *RunConfig) MergeResumedConfig(oldConfig RunConfigDict) error {
	// Add any top-level keys that aren't already set.
	if err := runConfig.addUnsetKeysFromSubtree(
		oldConfig,
		RunConfigPath{},
	); err != nil {
		return err
	}

	// When a user logs visualizations, we unfortunately store them in the
	// run's config. When resuming a run, we want to avoid erasing previously
	// logged visualizations, hence this special handling.
	if err := runConfig.addUnsetKeysFromSubtree(
		oldConfig,
		RunConfigPath{"_wandb", "visualize"},
	); err != nil {
		return err
	}

	if err := runConfig.addUnsetKeysFromSubtree(
		oldConfig,
		RunConfigPath{"_wandb", "viz"},
	); err != nil {
		return err
	}

	return nil
}

// Serializes the run configuration to send to the backend.
func (runConfig *RunConfig) Serialize(format ConfigFormat) ([]byte, error) {
	// A configuration dict in the format expected by the backend.
	valueConfig := make(map[string]map[string]interface{})
	for treeKey, treeValue := range runConfig.tree {
		valueConfig[treeKey] = map[string]interface{}{
			"value": treeValue,
		}
	}

	switch format {
	case FormatYaml:
		return yaml.Marshal(valueConfig)
	case FormatJson:
		return json.Marshal(valueConfig)
	}

	return nil, fmt.Errorf("config: unknown format: %v", format)
}

// Filters the configuration tree based on the given paths.
//
// If `exclude` is true, the paths are excluded from the tree. Otherwise, only
// the paths are included in the tree.
func (runConfig *RunConfig) FilterTree(
	paths []RunConfigPath,
	exclude bool,
) (RunConfigDict, error) {
	if exclude {
		pathMap := dictToPathMap(runConfig.tree)
		for _, path := range paths {
			prunePath(pathMap, path)
		}
		return pathMapToDict(pathMap), nil
	} else {
		pathMap := make(PathMap)
		for _, path := range paths {
			value := getSubtreeOrLeaf(runConfig.tree, path)
			if value != nil {
				pathMap[&path] = value
			}
		}
		return pathMapToDict(pathMap), nil
	}
}

// Converts of paths to values to a nested dict.
func pathMapToDict(pathMap PathMap) RunConfigDict {
	dict := make(RunConfigDict)
	for path, value := range pathMap {
		err := updateAtPath(dict, *path, deepCopyValue(value))
		// This can only happen if update one path and then another, invalid path
		// that goes through a leaf prefixed by the first path. This should
		// never happen.
		if err != nil {
			panic(err)
		}
	}
	return dict
}

// Makes a deep copy of the given value.
//
// The value can be a map, list, or a primitive.
func deepCopyValue(value interface{}) interface{} {
	var valueCopy interface{}
	switch value := value.(type) {
	case RunConfigDict:
		valueCopy := make(RunConfigDict)
		for k, v := range value {
			valueCopy[k] = deepCopyValue(v)
		}
	case []interface{}:
		copy := make([]interface{}, len(value))
		for i, v := range value {
			copy[i] = deepCopyValue(v)
		}
	default:
		return value
	}
	return valueCopy
}

// Converts a nested dict to a flat map of paths to values.
func dictToPathMap(dict RunConfigDict) PathMap {
	pathMap := make(PathMap)
	flattenMap(dict, RunConfigPath{}, pathMap)
	return pathMap
}

// Recursively constructs a flattened map of paths to values from a nested dict.
func flattenMap(input RunConfigDict, path RunConfigPath, output PathMap) {
	for k, v := range input {
		path := append(path, k)
		switch v := v.(type) {
		case RunConfigDict:
			flattenMap(v, path, output)
		default:
			output[&path] = v
		}
	}
}

// Prunes all paths starting with a given prefix from a PathMap.
func prunePath(input PathMap, prefix RunConfigPath) {
	for k := range input {
		if len(*k) < len(prefix) {
			continue
		}
		for i := 0; i < len(prefix); i++ {
			if (*k)[i] == prefix[i] {
				if i == len(prefix)-1 {
					delete(input, k)
				}
			} else {
				break
			}
		}
	}
}

// Uses the given subtree for keys that aren't already set.
func (runConfig *RunConfig) addUnsetKeysFromSubtree(
	tree RunConfigDict,
	path RunConfigPath,
) error {
	oldSubtree := getSubtree(tree, path)
	if oldSubtree == nil {
		return nil
	}

	newSubtree, err := getOrMakeSubtree(runConfig.tree, path)
	if err != nil {
		return err
	}

	for key, value := range oldSubtree {
		if _, exists := newSubtree[key]; !exists {
			newSubtree[key] = value
		}
	}

	return nil
}

// Returns the "_wandb" subtree of the config.
func (runConfig *RunConfig) internalSubtree() RunConfigDict {
	node, found := runConfig.tree["_wandb"]

	if !found {
		wandbInternal := make(RunConfigDict)
		runConfig.tree["_wandb"] = wandbInternal
		return wandbInternal
	}

	// Panic if the type is wrong, which should never happen.
	return node.(RunConfigDict)
}

// Sets the value at the path in the config tree.
func updateAtPath(
	tree RunConfigDict,
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

// Removes the value at the path in the config tree.
func (runConfig *RunConfig) removeAtPath(path RunConfigPath) {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree := getSubtree(runConfig.tree, pathPrefix)
	if subtree != nil {
		delete(subtree, key)
	}
}

// Returns the key path referenced by the config item.
func keyPath(configItem *service.ConfigItem) RunConfigPath {
	if len(configItem.GetNestedKey()) > 0 {
		return RunConfigPath(configItem.NestedKey)
	} else {
		return RunConfigPath{configItem.Key}
	}
}

// Returns the subtree at the path, or nil if it does not exist.
func getSubtree(
	tree RunConfigDict,
	path RunConfigPath,
) RunConfigDict {
	for _, key := range path {
		node, ok := tree[key]
		if !ok {
			return nil
		}

		subtree, ok := node.(RunConfigDict)
		if !ok {
			return nil
		}

		tree = subtree
	}

	return tree
}

// Returns the subtree or leaf at the path, or nil if it does not exist.
func getSubtreeOrLeaf(
	tree RunConfigDict,
	path RunConfigPath,
) interface{} {
	for _, key := range path {
		node, ok := tree[key]
		if !ok {
			return nil
		}

		subtree, ok := node.(RunConfigDict)
		if !ok {
			return node
		}

		tree = subtree
	}

	return tree
}

// Returns the subtree at the path, creating it if necessary.
//
// Returns an error if there exists a non-map value at the path.
func getOrMakeSubtree(
	tree RunConfigDict,
	path RunConfigPath,
) (RunConfigDict, error) {
	for _, key := range path {
		node, exists := tree[key]
		if !exists {
			node = make(RunConfigDict)
			tree[key] = node
		}

		subtree, ok := node.(RunConfigDict)
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

// Returns a deep copy of the given tree.
func deepCopy(tree RunConfigDict) (*RunConfigDict, error) {
	clone := make(RunConfigDict)
	for key, value := range tree {
		switch value := value.(type) {
		case RunConfigDict:
			innerClone, err := deepCopy(value)
			if err != nil {
				return nil, err
			}
			clone[key] = *innerClone
		case []interface{}:
			innerClone, err := deepCopyList(value)
			if err != nil {
				return nil, err
			}
			clone[key] = innerClone
		default:
			clone[key] = value
		}
	}
	return &clone, nil
}

// Returns a deep copy of the given list.
func deepCopyList(list []interface{}) ([]interface{}, error) {
	clone := make([]interface{}, len(list))
	for i, value := range list {
		switch value := value.(type) {
		case RunConfigDict:
			innerClone, err := deepCopy(value)
			if err != nil {
				return nil, err
			}
			clone[i] = *innerClone
		case []interface{}:
			innerClone, err := deepCopyList(value)
			if err != nil {
				return nil, err
			}
			clone[i] = innerClone
		default:
			clone[i] = value
		}
	}
	return clone, nil
}
