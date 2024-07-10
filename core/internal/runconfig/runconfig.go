package runconfig

import (
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
	"gopkg.in/yaml.v3"
)

type Format int

const (
	FormatYaml Format = iota
	FormatJson
)

// The configuration of a run.
//
// This is usually used for hyperparameters and some run metadata like the
// start time and the ML framework used. In a somewhat hacky way, it is also
// used to store programmatic custom charts for the run and various other
// things.
//
// The server process builds this up incrementally throughout a run's lifetime.
type RunConfig struct {
	pathTree *pathtree.PathTree
}

func New() *RunConfig {
	return &RunConfig{
		pathTree: pathtree.New(),
	}
}

func NewFrom(tree pathtree.TreeData) *RunConfig {
	return &RunConfig{
		pathTree: pathtree.NewFrom(tree),
	}
}

func (rc *RunConfig) Serialize(format Format) ([]byte, error) {

	value := make(map[string]any)
	for treeKey, treeValue := range rc.pathTree.Tree() {
		value[treeKey] = map[string]any{"value": treeValue}
	}

	switch format {
	case FormatYaml:
		// TODO: Does `yaml` support NaN and +-Infinity?
		return yaml.Marshal(value)
	case FormatJson:
		return simplejsonext.Marshal(value)
	default:
		return nil, fmt.Errorf("unsupported format: %v", format)
	}
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (rc *RunConfig) ApplyChangeRecord(
	configRecord *service.ConfigRecord,
	onError func(error),
) {
	updates := make([]*pathtree.PathItem, 0, len(configRecord.GetUpdate()))
	for _, item := range configRecord.GetUpdate() {
		value, err := simplejsonext.UnmarshalString(item.GetValueJson())
		if err != nil {
			onError(err)
			continue
		}

		updates = append(updates, &pathtree.PathItem{
			Path:  keyPath(item),
			Value: value,
		})
	}
	rc.pathTree.ApplyUpdate(updates, onError)
	removes := make([]*pathtree.PathItem, 0, len(configRecord.GetRemove()))
	for _, item := range configRecord.GetRemove() {
		removes = append(removes, &pathtree.PathItem{
			Path: keyPath(item),
		})
	}
	rc.pathTree.ApplyRemove(removes)
}

// Inserts W&B-internal values into the run's configuration.
func (rc *RunConfig) AddTelemetryAndMetrics(
	telemetry *service.TelemetryRecord,
	metrics []map[int]interface{},
) {
	wandbInternal := rc.internalSubtree()

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
func (rc *RunConfig) MergeResumedConfig(oldConfig pathtree.TreeData) error {
	// Add any top-level keys that aren't already set.
	if err := rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{},
	); err != nil {
		return err
	}

	// When a user logs visualizations, we unfortunately store them in the
	// run's config. When resuming a run, we want to avoid erasing previously
	// logged visualizations, hence this special handling.
	if err := rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "visualize"},
	); err != nil {
		return err
	}

	if err := rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "viz"},
	); err != nil {
		return err
	}

	return nil
}

// Returns the "_wandb" subtree of the config.
func (rc *RunConfig) internalSubtree() pathtree.TreeData {
	node, found := rc.pathTree.Tree()["_wandb"]

	if !found {
		wandbInternal := make(pathtree.TreeData)
		rc.pathTree.Tree()["_wandb"] = wandbInternal
		return wandbInternal
	}

	// Panic if the type is wrong, which should never happen.
	return node.(pathtree.TreeData)
}

func (rc *RunConfig) Tree() pathtree.TreeData {
	return rc.pathTree.Tree()
}

func (rc *RunConfig) CloneTree() (pathtree.TreeData, error) {
	return rc.pathTree.CloneTree()
}

// keyPath returns the key path for the given config item.
// If the item has a nested key, it returns the nested key.
// Otherwise, it returns a slice with the key.
func keyPath(item *service.ConfigItem) []string {
	if len(item.GetNestedKey()) > 0 {
		return item.GetNestedKey()
	}
	return []string{item.GetKey()}
}
