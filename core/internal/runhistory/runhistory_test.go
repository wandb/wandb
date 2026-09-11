package runhistory_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/simplejsonext"

	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSetFromRecord_NestedKey(t *testing.T) {
	rh := runhistory.New()

	err := rh.SetFromRecord(&spb.HistoryItem{
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

	err := rh.SetFromRecord(&spb.HistoryItem{
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

	err := rh.SetFromRecord(&spb.HistoryItem{
		Key:       "a",
		ValueJson: "invalid",
	})

	assert.ErrorContains(t, err, "failed to unmarshal")
}

func TestNaN(t *testing.T) {
	rh := runhistory.New()

	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "+inf", ValueJson: "Infinity"})
	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "-inf", ValueJson: "-Infinity"})
	_ = rh.SetFromRecord(&spb.HistoryItem{Key: "nan", ValueJson: "NaN"})

	encoded, err := rh.ToExtendedJSON()
	require.NoError(t, err)
	asMap, err := simplejsonext.UnmarshalObject(encoded)
	require.NoError(t, err)
	assert.Equal(t, asMap["+inf"], math.Inf(1))
	assert.Equal(t, asMap["-inf"], math.Inf(-1))
	assert.True(t, math.IsNaN(asMap["nan"].(float64))) // NaN != NaN
}
