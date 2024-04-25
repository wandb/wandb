package runconfig_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestConfigUpdate(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigTree{
		"b": runconfig.RunConfigTree{
			"c": 321.0,
			"d": 123.0,
		},
	})

	runConfig.ApplyChangeRecord(
		&service.ConfigRecord{
			Update: []*service.ConfigItem{
				{
					Key:       "a",
					ValueJson: "1",
				},
				{
					NestedKey: []string{"b", "c"},
					ValueJson: "\"text\"",
				},
			},
		}, ignoreError,
	)

	assert.Equal(t,
		runconfig.RunConfigTree{
			"a": 1.0,
			"b": runconfig.RunConfigTree{
				"c": "text",
				"d": 123.0,
			},
		},
		runConfig.Tree(),
	)
}

func TestConfigRemove(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigTree{
		"a": 9,
		"b": runconfig.RunConfigTree{
			"c": 321.0,
			"d": 123.0,
		},
	})

	runConfig.ApplyChangeRecord(
		&service.ConfigRecord{
			Remove: []*service.ConfigItem{
				{Key: "a"},
				{NestedKey: []string{"b", "c"}},
			},
		}, ignoreError,
	)

	assert.Equal(t,
		runconfig.RunConfigTree{"b": runconfig.RunConfigTree{"d": 123.0}},
		runConfig.Tree(),
	)
}

func TestConfigSerialize(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigTree{
		"number": 9,
		"nested": runconfig.RunConfigTree{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})

	yaml, _ := runConfig.Serialize(pathtree.FormatYaml)

	assert.Equal(t,
		""+
			"nested:\n"+
			"    value:\n"+
			"        list:\n"+
			"            - a\n"+
			"            - b\n"+
			"            - c\n"+
			"        text: xyz\n"+
			"number:\n"+
			"    value: 9\n",
		string(yaml),
	)
}

func TestAddTelemetryAndMetrics(t *testing.T) {
	runConfig := runconfig.New()
	telemetry := &service.TelemetryRecord{}

	runConfig.AddTelemetryAndMetrics(
		telemetry,
		[]map[int]interface{}{},
	)

	assert.Equal(t,
		runconfig.RunConfigTree{
			"_wandb": runconfig.RunConfigTree{
				"t": corelib.ProtoEncodeToDict(telemetry),
				"m": []map[int]interface{}{},
			},
		},
		runConfig.Tree(),
	)
}

func ignoreError(_err error) {}

func TestCloneTree(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigTree{
		"number": 9,
		"nested": runconfig.RunConfigTree{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	cloned, _ := runConfig.CloneTree()
	assert.Equal(t,
		runconfig.RunConfigTree{
			"number": 9,
			"nested": runconfig.RunConfigTree{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		cloned,
	)
	assert.NotEqual(t, runConfig, cloned)
	// Delete elements from the cloned tree and check that the original is unchanged.
	delete(cloned, "number")
	delete(cloned["nested"].(runconfig.RunConfigTree), "list")
	assert.Equal(t,
		runconfig.RunConfigTree{
			"number": 9,
			"nested": runconfig.RunConfigTree{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		runConfig.Tree(),
	)
}
