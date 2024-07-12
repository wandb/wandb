package runconfig

import (
	"fmt"

	"github.com/wandb/segmentio-encoding/json"
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
	for treeKey, treeValue := range rc.pathTree.CloneTree() {
		value[treeKey] = map[string]any{"value": treeValue}
	}

	switch format {
	case FormatYaml:
		return yaml.Marshal(value)
	case FormatJson:
		return json.Marshal(value)
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
	for _, item := range configRecord.GetUpdate() {
		var value any
		if err := json.Unmarshal([]byte(item.GetValueJson()), &value); err != nil {
			onError(err)
			continue
		}

		rc.pathTree.Set(keyPath(item), value)
	}

	for _, item := range configRecord.GetRemove() {
		rc.pathTree.Remove(keyPath(item))
	}
}

// Inserts W&B-internal values into the run's configuration.
func (rc *RunConfig) AddTelemetryAndMetrics(
	telemetry *service.TelemetryRecord,
	metrics []map[int]interface{},
) {
	if telemetry.GetCliVersion() != "" {
		rc.pathTree.Set(
			pathtree.TreePath{"_wandb", "cli_version"},
			telemetry.CliVersion,
		)
	}
	if telemetry.GetPythonVersion() != "" {
		rc.pathTree.Set(
			pathtree.TreePath{"_wandb", "python_version"},
			telemetry.PythonVersion,
		)
	}

	rc.pathTree.Set(
		pathtree.TreePath{"_wandb", "t"},
		corelib.ProtoEncodeToDict(telemetry),
	)

	rc.pathTree.Set(
		pathtree.TreePath{"_wandb", "m"},
		metrics,
	)
}

// Incorporates the config from a run that's being resumed.
func (rc *RunConfig) MergeResumedConfig(oldConfig pathtree.TreeData) {
	// Add any top-level keys that aren't already set.
	rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{},
	)

	// When a user logs visualizations, we unfortunately store them in the
	// run's config. When resuming a run, we want to avoid erasing previously
	// logged visualizations, hence this special handling.
	rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "visualize"},
	)

	rc.pathTree.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "viz"},
	)
}

func (rc *RunConfig) CloneTree() pathtree.TreeData {
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
