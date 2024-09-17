package runconfig_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/corelib"
	"github.com/wandb/wandb/core/internal/runconfig"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestConfigUpdate(t *testing.T) {
	runConfig := runconfig.NewFrom(map[string]any{
		"b": map[string]any{
			"c": 321.0,
			"d": 123.0,
		},
	})

	runConfig.ApplyChangeRecord(
		&spb.ConfigRecord{
			Update: []*spb.ConfigItem{
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
		map[string]any{
			"a": int64(1),
			"b": map[string]any{
				"c": "text",
				"d": 123.0,
			},
		},
		runConfig.CloneTree(),
	)
}

func TestConfigRemove(t *testing.T) {
	runConfig := runconfig.NewFrom(map[string]any{
		"a": 9,
		"b": map[string]any{
			"c": 321.0,
			"d": 123.0,
		},
	})

	runConfig.ApplyChangeRecord(
		&spb.ConfigRecord{
			Remove: []*spb.ConfigItem{
				{Key: "a"},
				{NestedKey: []string{"b", "c"}},
			},
		}, ignoreError,
	)

	assert.Equal(t,
		map[string]any{"b": map[string]any{"d": 123.0}},
		runConfig.CloneTree(),
	)
}

func TestConfigSerialize(t *testing.T) {
	runConfig := runconfig.NewFrom(map[string]any{
		"number": 9,
		"nested": map[string]any{
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
	telemetry := &spb.TelemetryRecord{}

	runConfig.AddTelemetryAndMetrics(
		telemetry,
		[]map[string]any{},
	)

	assert.Equal(t,
		map[string]any{
			"_wandb": map[string]any{
				"t": corelib.ProtoEncodeToDict(telemetry),
				"m": []map[string]any{},
			},
		},
		runConfig.CloneTree(),
	)
}

func ignoreError(_err error) {}

func TestCloneTree(t *testing.T) {
	runConfig := runconfig.NewFrom(map[string]any{
		"number": 9,
		"nested": map[string]any{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})
	cloned := runConfig.CloneTree()
	assert.Equal(t,
		map[string]any{
			"number": 9,
			"nested": map[string]any{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		cloned,
	)
	assert.NotEqual(t, runConfig, cloned)
	// Delete elements from the cloned tree and check that the original is unchanged.
	delete(cloned, "number")
	delete(cloned["nested"].(map[string]any), "list")
	assert.Equal(t,
		map[string]any{
			"number": 9,
			"nested": map[string]any{
				"list": []string{"a", "b", "c"},
				"text": "xyz",
			},
		},
		runConfig.CloneTree(),
	)
}
