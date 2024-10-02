package wbvalue

import (
	"encoding/json"

	"github.com/wandb/wandb/core/internal/pathtree"
)

// Chart is a chart displayed in the run's workspace page.
//
// For now, this is specifically a custom line chart.
//
// Chart metadata is stored in a run's config.
type Chart struct {
	// Title is the chart's title in the UI.
	Title string

	// TableKey is a key in the run history that points to a table.
	TableKey string

	// X and Y are columns in the underlying table to use for the X and Y axes.
	X, Y string
}

// ConfigKey is the key in the config where to store the chart metadata.
//
// The key parameter is a unique key for the chart. It's generally
// related to the key of the underlying table but is otherwise unimportant.
func (c Chart) ConfigKey(key string) pathtree.TreePath {
	return pathtree.PathOf("_wandb", "visualize", key)
}

// ConfigValueJSON is the JSON representation of the chart's metadata.
func (c Chart) ConfigValueJSON() (string, error) {
	result, err := json.Marshal(
		chartConfig{
			PanelType: "Vega2",
			PanelConfig: chartPanelConfig{
				PanelDefId:     "wandb/line/v0",
				FieldSettings:  map[string]string{"x": c.X, "y": c.Y},
				StringSettings: map[string]string{"title": c.Title},
				Transform:      map[string]string{"name": "tableWithLeafColNames"},
				UserQuery: chartUserQuery{
					QueryFields: []chartQueryField{{
						Name: "runSets",
						Args: []map[string]string{{
							"name":  "runSets",
							"value": "${runSets}",
						}},
						Fields: []chartQueryFieldField{
							{Name: "id"},
							{Name: "name"},
							{Name: "_defaultColorIndex"},
							{
								Name: "summaryTable",
								Args: []map[string]string{{
									"name":  "tableKey",
									"value": c.TableKey,
								}},
							},
						},
					}},
				},
			},
		},
	)

	return string(result), err
}

type chartConfig struct {
	PanelType   string           `json:"panel_type"`
	PanelConfig chartPanelConfig `json:"panel_config"`
}

type chartPanelConfig struct {
	PanelDefId     string            `json:"panelDefId"`
	FieldSettings  map[string]string `json:"fieldSettings"`
	StringSettings map[string]string `json:"stringSettings"`
	Transform      map[string]string `json:"transform"`
	UserQuery      chartUserQuery    `json:"userQuery"`
}

type chartUserQuery struct {
	QueryFields []chartQueryField `json:"queryFields"`
}

type chartQueryField struct {
	Name   string                 `json:"name"`
	Args   []map[string]string    `json:"args"`
	Fields []chartQueryFieldField `json:"fields"`
}

type chartQueryFieldField struct {
	Name string              `json:"name"`
	Args []map[string]string `json:"args,omitempty"`
}
