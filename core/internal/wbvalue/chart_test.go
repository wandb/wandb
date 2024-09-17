package wbvalue_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/wbvalue"
)

func TestChartKey(t *testing.T) {
	key := wbvalue.Chart{}.ConfigKey("stuff")

	assert.Equal(t, pathtree.PathOf("_wandb", "visualize", "stuff"), key)
}

func TestChartValue(t *testing.T) {
	valueJSON, err := wbvalue.Chart{
		Title:    `test title with JSON injection: "`,
		TableKey: "test_table_key",
		X:        "test_x", Y: "test_y",
	}.ConfigValueJSON()

	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"panel_type": "Vega2",
			"panel_config": {
				"panelDefId": "wandb/line/v0",
				"fieldSettings": {"x": "test_x", "y": "test_y"},
				"stringSettings": {"title": "test title with JSON injection: \""},
				"transform": {"name": "tableWithLeafColNames"},
				"userQuery": {
					"queryFields": [{
						"name": "runSets",
						"args": [{"name": "runSets", "value": "${runSets}"}],
						"fields": [
							{"name": "id"},
							{"name": "name"},
							{"name": "_defaultColorIndex"},
							{
								"name": "summaryTable",
								"args": [{
									"name": "tableKey",
									"value": "test_table_key"
								}]
							}
						]
					}]
				}
			}
		}`,
		valueJSON)
}
