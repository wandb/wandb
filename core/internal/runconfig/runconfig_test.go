package runconfig_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestConfigUpdate(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigDict{
		"b": runconfig.RunConfigDict{
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
		runconfig.RunConfigDict{
			"a": 1.0,
			"b": runconfig.RunConfigDict{
				"c": "text",
				"d": 123.0,
			},
		},
		runConfig.Tree(),
	)
}

func TestConfigRemove(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigDict{
		"a": 9,
		"b": runconfig.RunConfigDict{
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
		runconfig.RunConfigDict{"b": runconfig.RunConfigDict{"d": 123.0}},
		runConfig.Tree(),
	)
}

func TestConfigSerialize(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigDict{
		"number": 9,
		"nested": runconfig.RunConfigDict{
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
		runconfig.RunConfigDict{
			"_wandb": runconfig.RunConfigDict{
				"t": corelib.ProtoEncodeToDict(telemetry),
				"m": []map[int]interface{}{},
			},
		},
		runConfig.Tree(),
	)
}

func ignoreError(_err error) {}

func TestFilterTree(t *testing.T) {
	runConfig := runconfig.NewFrom(runconfig.RunConfigDict{
		"number": 9,
		"nested": runconfig.RunConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	paths := []runconfig.RunConfigPath{
		{"number"},
		{"nested", "list"},
	}

	t.Run("Include Tree", func(t *testing.T) {
		include_tree, err := runConfig.FilterTree(paths, false)
		if err != nil {
			t.Error(err)
		}
		assert.Equal(t,
			runconfig.RunConfigDict{
				"number": 9,
				"nested": runconfig.RunConfigDict{
					"list": []string{"a", "b", "c"},
				},
			},
			include_tree,
		)
	})

	t.Run("Exclude Tree", func(t *testing.T) {
		exclude_tree, err := runConfig.FilterTree(paths, true)
		if err != nil {
			t.Error(err)
		}
		assert.Equal(t,
			runconfig.RunConfigDict{
				"nested": runconfig.RunConfigDict{
					"text": "xyz",
				},
			},
			exclude_tree,
		)
	})

	t.Run("Missing path", func(t *testing.T) {
		config, err := runConfig.FilterTree([]runconfig.RunConfigPath{{"missing"}}, false)
		assert.Nil(t, err)
		assert.Equal(t, config, runconfig.RunConfigDict{"missing": nil})
	})

	// This weird case is the only error that FilterTree needs to check. It can only
	// happen if we have an include path that goes through a leaf. And the leaf must be
	// included in a previous path.
	t.Run("Invalid path through leaf", func(t *testing.T) {
		config, err := runConfig.FilterTree([]runconfig.RunConfigPath{{"nested", "text"}, {"nested", "text", "thing"}}, false)
		assert.Nil(t, config)
		assert.NotNil(t, err)
	})
}
