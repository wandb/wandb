package server_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/server"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestConfigUpdate(t *testing.T) {
	runConfig := server.NewRunConfigFrom(server.RunConfigDict{
		"b": server.RunConfigDict{
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
		server.RunConfigDict{
			"a": 1.0,
			"b": server.RunConfigDict{
				"c": "text",
				"d": 123.0,
			},
		},
		runConfig.Tree(),
	)
}

func TestConfigRemove(t *testing.T) {
	runConfig := server.NewRunConfigFrom(server.RunConfigDict{
		"a": 9,
		"b": server.RunConfigDict{
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
		server.RunConfigDict{"b": server.RunConfigDict{"d": 123.0}},
		runConfig.Tree(),
	)
}

func TestConfigSerialize(t *testing.T) {
	runConfig := server.NewRunConfigFrom(server.RunConfigDict{
		"number": 9,
		"nested": server.RunConfigDict{
			"list": []string{"a", "b", "c"},
			"text": "xyz",
		},
	})

	yaml, _ := runConfig.Serialize(server.FORMAT_YAML)

	assert.Equal(t,
		string(yaml),
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
	)
}

func ignoreError(_err error) {}
