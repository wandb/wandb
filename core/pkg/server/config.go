package server

import (
	"fmt"

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

type ConfigFormat int

const (
	FORMAT_YAML ConfigFormat = iota
	FORMAT_JSON
)

func NewRunConfig() *RunConfig {
	return &RunConfig{make(RunConfigDict)}
}

func NewRunConfigFrom(tree RunConfigDict) *RunConfig {
	return &RunConfig{tree}
}

// Returns the underlying config tree.
//
// Provided temporarily as part of a refactor. Avoid using this, especially
// mutating it.
func (runConfig *RunConfig) Tree() RunConfigDict {
	return runConfig.tree
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
					"failed to unmarshall JSON for config key %v: %w",
					path,
					err,
				),
			)
			continue
		}

		if err := runConfig.updateAtPath(path, value); err != nil {
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
	case FORMAT_YAML:
		return yaml.Marshal(valueConfig)
	case FORMAT_JSON:
		return json.Marshal(valueConfig)
	}

	return nil, fmt.Errorf("unknown format: %v", format)
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
func (runConfig *RunConfig) updateAtPath(
	path []string,
	value interface{},
) error {
	pathPrefix := path[:len(path)-1]
	key := path[len(path)-1]

	subtree, err := getOrMakeSubtree(runConfig.tree, pathPrefix)

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
				"config value at path %v is type %T, not a map",
				path,
				node,
			)
		}

		tree = subtree
	}

	return tree, nil
}
