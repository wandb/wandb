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
	runConfig := runconfig.NewFrom(pathtree.TreeData{
		"b": pathtree.TreeData{
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
		pathtree.TreeData{
			"a": 1.0,
			"b": pathtree.TreeData{
				"c": "text",
				"d": 123.0,
			},
		},
		runConfig.Tree(),
	)
}

func TestConfigRemove(t *testing.T) {
	runConfig := runconfig.NewFrom(pathtree.TreeData{
		"a": 9,
		"b": pathtree.TreeData{
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
		pathtree.TreeData{"b": pathtree.TreeData{"d": 123.0}},
		runConfig.Tree(),
	)
}

func TestConfigSerialize(t *testing.T) {
	runConfig := runconfig.NewFrom(pathtree.TreeData{
		"number": 9,
		"nested": pathtree.TreeData{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})

	yaml, _ := runConfig.Serialize(runconfig.FormatYaml)

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
		pathtree.TreeData{
			"_wandb": pathtree.TreeData{
				"t": corelib.ProtoEncodeToDict(telemetry),
				"m": []map[int]interface{}{},
			},
		},
		runConfig.Tree(),
	)
}

func ignoreError(_err error) {}

func TestCloneTree(t *testing.T) {
	runConfig := runconfig.NewFrom(pathtree.TreeData{
		"number": 9,
		"nested": pathtree.TreeData{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	cloned, _ := runConfig.CloneTree()
	assert.Equal(t,
		pathtree.TreeData{
			"number": 9,
			"nested": pathtree.TreeData{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		cloned,
	)
	assert.NotEqual(t, runConfig, cloned)
	// Delete elements from the cloned tree and check that the original is unchanged.
	delete(cloned, "number")
	delete(cloned["nested"].(pathtree.TreeData), "list")
	assert.Equal(t,
		pathtree.TreeData{
			"number": 9,
			"nested": pathtree.TreeData{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		runConfig.Tree(),
	)
}
