package runsummary_test

import (
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/pkg/service"
)

func TestExplicitSummary(t *testing.T) {
	rs := runsummary.New()

	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "x",
		ValueJson: "123",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "y",
		ValueJson: "10.5",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "z",
		ValueJson: `"abc"`,
	})

	assert.Equal(t,
		map[string]any{
			"x": int64(123),
			"y": float64(10.5),
			"z": "abc",
		},
		rs.ToMap())
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
		runsummary.Min|runsummary.Max|runsummary.Mean|runsummary.Latest,
	)
	_, _ = rs.UpdateSummaries(rh1)
	_, _ = rs.UpdateSummaries(rh2)
	_, _ = rs.UpdateSummaries(rh3)

	assert.Equal(t,
		map[string]any{
			"x": map[string]any{
				"min":  float64(1),
				"max":  float64(3.0),
				"mean": float64(2.1),
				"last": float64(2.3),
			},
		},
		rs.ToMap())
}

func TestNestedKey(t *testing.T) {
	rs := runsummary.New()
	rh := runhistory.New()
	rh.SetFloat(
		pathtree.PathOf("x", "y", "z"),
		1.4,
	)

	_, _ = rs.UpdateSummaries(rh)
	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"a", "b", "c"},
		ValueJson: `{"value": 1}`,
	})

	assert.Equal(t,
		map[string]any{
			"x.y.z": float64(1.4),
			"a.b.c": map[string]any{
				"value": int64(1),
			},
		},
		rs.ToMap())
}

func TestRemove(t *testing.T) {
	rs := runsummary.New()

	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"x", "y"},
		ValueJson: "1",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"z", "w"},
		ValueJson: "2",
	})
	rs.Remove(pathtree.PathOf("x", "y"))

	assert.Equal(t,
		map[string]any{"z.w": int64(2)},
		rs.ToMap())
}

func TestNoSummary(t *testing.T) {
	rs := runsummary.New()

	rs.ConfigureMetric(pathtree.PathOf("x"), true /*noSummary*/, 0)
	_ = rs.SetFromRecord(&service.SummaryItem{Key: "x", ValueJson: "1"})

	assert.Empty(t, rs.ToMap())
	encoded, err := rs.Serialize()
	assert.NoError(t, err)
	assert.Equal(t, "{}", string(encoded))
}

func TestToRecords(t *testing.T) {
	rs := runsummary.New()

	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "x",
		ValueJson: "Infinity",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"y", "z"},
		ValueJson: "NaN",
	})
	rs.ConfigureMetric(pathtree.PathOf("none"), true, 0)
	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "none",
		ValueJson: "123",
	})
	records, err := rs.ToRecords()

	assert.NoError(t, err)
	require.Len(t, records, 2)
	keyValue := make(map[string]string)
	keyValue[strings.Join(records[0].NestedKey, ".")] = records[0].ValueJson
	keyValue[strings.Join(records[1].NestedKey, ".")] = records[1].ValueJson
	assert.Equal(t,
		map[string]string{
			"x":   "Infinity",
			"y.z": "NaN",
		},
		keyValue)
}

func TestSerialize(t *testing.T) {
	rs := runsummary.New()

	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "x",
		ValueJson: "1.5",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"y", "z"},
		ValueJson: "-5",
	})
	_ = rs.SetFromRecord(&service.SummaryItem{
		NestedKey: []string{"a", "b", "c"},
		ValueJson: `"abc"`,
	})
	rs.ConfigureMetric(pathtree.PathOf("none"), true, 0)
	_ = rs.SetFromRecord(&service.SummaryItem{
		Key:       "none",
		ValueJson: `"none"`,
	})
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
