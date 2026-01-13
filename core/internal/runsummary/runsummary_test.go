package runsummary_test

import (
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
)

func TestExplicitSummary(t *testing.T) {
	rs := runsummary.New()

	rs.Set(pathtree.PathOf("x"), int64(123))
	rs.Set(pathtree.PathOf("y"), float64(10.5))
	rs.Set(pathtree.PathOf("z"), "abc")

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"x": 123,
			"y": 10.5,
			"z": "abc"
		}`,
		string(encoded))
}

func TestSummaryTypes(t *testing.T) {
	rs := runsummary.New()
	rh1 := runhistory.New()
	rh2 := runhistory.New()
	rh3 := runhistory.New()
	rh1.SetInt(pathtree.PathOf("x"), 1)
	rh2.SetFloat(pathtree.PathOf("x"), 3.0)
	rh3.SetFloat(pathtree.PathOf("x"), 2.3)

	rs.ConfigureMetric(
		pathtree.PathOf("x"), false,
		runsummary.Min|runsummary.Max|runsummary.Mean|runsummary.Latest|runsummary.First,
	)
	_, _ = rs.UpdateSummaries(rh1)
	_, _ = rs.UpdateSummaries(rh2)
	_, _ = rs.UpdateSummaries(rh3)

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"x": {
				"min": 1,
				"max": 3.0,
				"mean": 2.1,
				"last": 2.3,
				"first": 1
			}
		}`,
		string(encoded))
}

func TestNestedKey(t *testing.T) {
	rs := runsummary.New()
	rh := runhistory.New()
	rh.SetFloat(
		pathtree.PathOf("x", "y", "z"),
		1.4,
	)

	_, _ = rs.UpdateSummaries(rh)
	rs.Set(pathtree.PathOf("a", "b", "c"), map[string]any{"value": int64(1)})

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{
			"x": {"y": {"z": 1.4}},
			"a": {"b": {"c": {"value": 1}}}
		}`,
		string(encoded))
}

func TestRemove(t *testing.T) {
	rs := runsummary.New()

	rs.Set(pathtree.PathOf("x", "y"), int64(1))
	rs.Set(pathtree.PathOf("z", "w"), int64(2))
	rs.Remove(pathtree.PathOf("x", "y"))

	encoded, err := rs.Serialize()
	require.NoError(t, err)
	assert.JSONEq(t,
		`{"z": {"w": 2}}`,
		string(encoded))
}

func TestNoSummary(t *testing.T) {
	rs := runsummary.New()

	rs.ConfigureMetric(pathtree.PathOf("x"), true /*noSummary*/, 0)
	rs.Set(pathtree.PathOf("x"), int64(1))

	assert.Empty(t, rs.ToNestedMaps())
	encoded, err := rs.Serialize()
	assert.NoError(t, err)
	assert.Equal(t, "{}", string(encoded))
}

func TestToRecords(t *testing.T) {
	rs := runsummary.New()

	rs.Set(pathtree.PathOf("x"), math.Inf(1))
	rs.Set(pathtree.PathOf("y", "z"), math.NaN())
	rs.ConfigureMetric(pathtree.PathOf("none"), true, 0)
	rs.Set(pathtree.PathOf("none"), int64(123))
	records, err := rs.ToRecords()

	assert.NoError(t, err)
	require.Len(t, records, 2)
	rec0 := records[0]
	rec1 := records[1]
	if len(rec0.NestedKey) > 0 {
		rec0, rec1 = rec1, rec0
	}
	assert.Equal(t, "x", rec0.Key)
	assert.Equal(t, "Infinity", rec0.ValueJson)
	assert.Equal(t, []string{"y", "z"}, rec1.NestedKey)
	assert.Equal(t, "NaN", rec1.ValueJson)
}

func TestSerialize(t *testing.T) {
	rs := runsummary.New()

	rs.Set(pathtree.PathOf("x"), float64(1.5))
	rs.Set(pathtree.PathOf("y", "z"), int64(-5))
	rs.Set(pathtree.PathOf("a", "b", "c"), "abc")
	rs.ConfigureMetric(pathtree.PathOf("none"), true, 0)
	rs.Set(pathtree.PathOf("none"), "none")
	encoded, err := rs.Serialize()

	assert.NoError(t, err)
	assert.JSONEq(t,
		`{
			"x": 1.5,
			"y": {"z": -5},
			"a": {"b": {"c": "abc"}}
		}`,
		string(encoded))
}
