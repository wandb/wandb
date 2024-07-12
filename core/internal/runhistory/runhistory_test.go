package runhistory_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
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
	x, exists := rh.GetNumber("a.b")
	assert.True(t, exists)
	assert.EqualValues(t, 1, x)
}

func TestSetRecord_NestedValue(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&service.HistoryItem{
		Key:       "a",
		ValueJson: `{"b": 1, "c": {"d": 2.5, "e": "e"}}`,
	})

	require.NoError(t, err)
	ab, _ := rh.GetNumber("a.b")
	acd, _ := rh.GetNumber("a.c.d")
	ace, _ := rh.GetString("a.c.e")
	assert.EqualValues(t, 1, ab)
	assert.EqualValues(t, 2.5, acd)
	assert.Equal(t, "e", ace)
}

func TestNaN(t *testing.T) {
	rh := runhistory.New()

	rh.SetFloat("+inf", math.Inf(1))
	rh.SetFloat("-inf", math.Inf(-1))
	rh.SetFloat("nan", math.NaN())

	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	assert.Equal(t,
		`{"+inf":Infinity,"-inf":-Infinity,"nan":NaN}`,
		string(encoded))
}
