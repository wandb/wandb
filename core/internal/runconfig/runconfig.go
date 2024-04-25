package runconfig

import (
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/pkg/service"
)

// A RunConfig representation.
//
// This is a type alias for refactoring purposes; it should be new type
// otherwise.
type RunConfigDict = pathtree.TreeData

// The configuration of a run.
//
// This is usually used for hyperparameters and some run metadata like the
// start time and the ML framework used. In a somewhat hacky way, it is also
// used to store programmatic custom charts for the run and various other
// things.
//
// The server process builds this up incrementally throughout a run's lifetime.
type RunConfig struct {
	*pathtree.PathTree
}

func New() *RunConfig {
	return &RunConfig{PathTree: pathtree.New()}
}

func NewFrom(tree RunConfigDict) *RunConfig {
	return &RunConfig{PathTree: pathtree.NewFrom(tree)}
}

func (runConfig *RunConfig) Serialize(format pathtree.Format) ([]byte, error) {
	return runConfig.PathTree.Serialize(format, func(value any) any {
		return map[string]any{"value": value}
	})
}

// Updates and/or removes values from the configuration tree.
//
// Does a best-effort job to apply all changes. Errors are passed to `onError`
// and skipped.
func (runConfig *RunConfig) ApplyChangeRecord(
	configRecord *service.ConfigRecord,
	onError func(error),
) {
	updates := make([]*pathtree.PathItem, len(configRecord.GetUpdate()))
	for i, item := range configRecord.GetUpdate() {
		updates[i] = pathtree.FromItem(item)
	}
	runConfig.ApplyUpdate(updates, onError)

	removes := make([]*pathtree.PathItem, len(configRecord.GetRemove()))
	for i, item := range configRecord.GetRemove() {
		removes[i] = pathtree.FromItem(item)
	}
	runConfig.ApplyRemove(removes, onError)
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
	if err := runConfig.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{},
	); err != nil {
		return err
	}

	// When a user logs visualizations, we unfortunately store them in the
	// run's config. When resuming a run, we want to avoid erasing previously
	// logged visualizations, hence this special handling.
	if err := runConfig.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "visualize"},
	); err != nil {
		return err
	}

	if err := runConfig.AddUnsetKeysFromSubtree(
		oldConfig,
		pathtree.TreePath{"_wandb", "viz"},
	); err != nil {
		return err
	}

	return nil
}

// Returns the "_wandb" subtree of the config.
func (runConfig *RunConfig) internalSubtree() RunConfigDict {
	node, found := runConfig.Tree()["_wandb"]

	if !found {
		wandbInternal := make(RunConfigDict)
		runConfig.Tree()["_wandb"] = wandbInternal
		return wandbInternal
	}

	// Panic if the type is wrong, which should never happen.
	return node.(RunConfigDict)
}
