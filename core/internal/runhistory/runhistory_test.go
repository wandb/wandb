package runhistory_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/segmentio-encoding/json"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestSetFromRecord_NestedKey(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&service.HistoryItem{
		NestedKey: []string{"a", "b"},
		ValueJson: "1",
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t, `{"a": {"b": 1}}`, string(encoded))
}

func TestSetRecord_NestedValue(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&service.HistoryItem{
		Key:       "a",
		ValueJson: `{"b": 1, "c": {"d": 2.5, "e": "e", "f": false}}`,
	})

	require.NoError(t, err)
	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{"a": {"b": 1, "c": {"d": 2.5, "e": "e", "f": false}}}`,
		string(encoded))
}

func TestSetRecord_UnmarshalError(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&service.HistoryItem{
		Key:       "a",
		ValueJson: "invalid",
	})

	assert.ErrorContains(t, err, "failed to unmarshal")
}

func TestNaN(t *testing.T) {
	rh := runhistory.New()

	rh.SetFloat(pathtree.TreePath{"+inf"}, math.Inf(1))
	rh.SetFloat(pathtree.TreePath{"-inf"}, math.Inf(-1))
	rh.SetFloat(pathtree.TreePath{"nan"}, math.NaN())

	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	var asMap map[string]any
	err = json.Unmarshal(encoded, &asMap)
	require.NoError(t, err)
	assert.Equal(t, asMap["+inf"], math.Inf(1))
	assert.Equal(t, asMap["-inf"], math.Inf(-1))
	assert.True(t, math.IsNaN(asMap["nan"].(float64))) // NaN != NaN
}

func TestSetBool(t *testing.T) {
	rh := runhistory.New()

	rh.SetBool(pathtree.TreePath{"bool"}, true)

	encoded, _ := rh.ToExtendedJSON()
	assert.Equal(t, `{"bool":true}`, string(encoded))
}

func TestSetInt(t *testing.T) {
	rh := runhistory.New()

	rh.SetInt(pathtree.TreePath{"int"}, 123)

	encoded, _ := rh.ToExtendedJSON()
	assert.Equal(t, `{"int":123}`, string(encoded))
}

func TestSetFloat(t *testing.T) {
	rh := runhistory.New()

	rh.SetFloat(pathtree.TreePath{"float"}, 1.23)

	encoded, _ := rh.ToExtendedJSON()
	assert.Equal(t, `{"float":1.23}`, string(encoded))
}

func TestSetString(t *testing.T) {
	rh := runhistory.New()

	rh.SetString(pathtree.TreePath{"string"}, "abc")

	encoded, _ := rh.ToExtendedJSON()
	assert.Equal(t, `{"string":"abc"}`, string(encoded))
}
