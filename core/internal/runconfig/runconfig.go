package runconfig

import (
	"fmt"

	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/pathtree"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
	pathTree *pathtree.PathTree[any]
}

func New() *RunConfig {
	return &RunConfig{
		pathTree: pathtree.New[any](),
	}
}

func NewFrom(tree map[string]any) *RunConfig {
	rc := New()

	for key, value := range tree {
		switch x := value.(type) {
		case map[string]any:
			pathtree.SetSubtree(rc.pathTree, pathtree.PathOf(key), x)
		default:
			rc.pathTree.Set(pathtree.PathOf(key), x)
		}
	}

	return rc
}

func (rc *RunConfig) Serialize(format Format) ([]byte, error) {

	value := make(map[string]any)
	for treeKey, treeValue := range rc.pathTree.CloneTree() {
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
	configRecord *spb.ConfigRecord,
	onError func(error),
) {
	for _, item := range configRecord.GetUpdate() {
		value, err := simplejsonext.UnmarshalString(item.GetValueJson())
		if err != nil {
			onError(err)
			continue
		}

		switch x := value.(type) {
		case map[string]any:
			pathtree.SetSubtree(rc.pathTree, keyPath(item), x)
		default:
			rc.pathTree.Set(keyPath(item), x)
		}
	}

	for _, item := range configRecord.GetRemove() {
		rc.pathTree.Remove(keyPath(item))
	}
}

// Inserts W&B-internal values into the run's configuration.
func (rc *RunConfig) AddTelemetryAndMetrics(
	telemetry *spb.TelemetryRecord,
	metrics []map[string]interface{},
) {
	if telemetry.GetCliVersion() != "" {
		rc.pathTree.Set(
			pathtree.PathOf("_wandb", "cli_version"),
			telemetry.CliVersion,
		)
	}
	if telemetry.GetPythonVersion() != "" {
		rc.pathTree.Set(
			pathtree.PathOf("_wandb", "python_version"),
			telemetry.PythonVersion,
		)
	}

	rc.pathTree.Set(
		pathtree.PathOf("_wandb", "t"),
		corelib.ProtoEncodeToDict(telemetry),
	)

	rc.pathTree.Set(
		pathtree.PathOf("_wandb", "m"),
		metrics,
	)
}

// Incorporates the config from a run that's being resumed.
func (rc *RunConfig) MergeResumedConfig(oldConfig map[string]any) {
	// Add any top-level keys that aren't already set.
	rc.addUnsetKeysFromSubtree(oldConfig, nil)

	// When a user logs visualizations, we unfortunately store them in the
	// run's config. When resuming a run, we want to avoid erasing previously
	// logged visualizations, hence this special handling.
	rc.addUnsetKeysFromSubtree(
		oldConfig,
		[]string{"_wandb", "visualize"},
	)

	rc.addUnsetKeysFromSubtree(
		oldConfig,
		[]string{"_wandb", "viz"},
	)
}

func (rc *RunConfig) addUnsetKeysFromSubtree(
	oldConfig map[string]any,
	prefix []string,
) {
	for _, part := range prefix {
		x, ok := oldConfig[part]

		if !ok {
			return
		}

		switch subtree := x.(type) {
		case map[string]any:
			oldConfig = subtree
		default:
			return
		}
	}

	for key, value := range oldConfig {
		if rc.pathTree.HasNode(pathtree.PathOf(key)) {
			continue
		}

		path := pathtree.PathWithPrefix(prefix, key)
		switch x := value.(type) {
		case map[string]any:
			pathtree.SetSubtree(rc.pathTree, path, x)
		default:
			rc.pathTree.Set(path, x)
		}
	}
}

func (rc *RunConfig) CloneTree() map[string]any {
	return rc.pathTree.CloneTree()
}

// keyPath returns the key path for the given config item.
// If the item has a nested key, it returns the nested key.
// Otherwise, it returns a slice with the key.
func keyPath(item *spb.ConfigItem) pathtree.TreePath {
	if len(item.GetNestedKey()) > 0 {
		key := item.GetNestedKey()
		return pathtree.PathOf(key[0], key[1:]...)
	}

	return pathtree.PathOf(item.GetKey())
}
