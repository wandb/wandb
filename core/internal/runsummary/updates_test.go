package runsummary_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runsummary"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestUpdates_Apply_InsertsRemovesAndCollectsErrors(t *testing.T) {
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("x"), 1)
	rs.Set(pathtree.PathOf("y"), 2)

	err := runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "x", ValueJson: `3.5`},
			{Key: "z", ValueJson: `"this is z"`},
			{Key: "oops", ValueJson: `<not valid JSON>`},
		},
		Remove: []*spb.SummaryItem{
			{Key: "y"},
		},
	}).Apply(rs)

	assert.Equal(t,
		map[string]any{
			"x": float64(3.5),
			"z": "this is z",
		},
		rs.ToNestedMaps())
	assert.ErrorContains(t, err, "failed to update some keys")
	assert.ErrorContains(t, err, "oops")
}

func TestUpdates_Apply_NilMakesNoChanges(t *testing.T) {
	rs := runsummary.New()

	var nilUpdates *runsummary.Updates
	err := nilUpdates.Apply(rs)

	assert.NoError(t, err)
}

func TestUpdates_Merge(t *testing.T) {
	u1 := runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "update-then-remove", ValueJson: `"test"`},
		},
		Remove: []*spb.SummaryItem{
			{Key: "remove-then-update"},
		},
	})
	u2 := runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "remove-then-update", ValueJson: `7`},
		},
		Remove: []*spb.SummaryItem{
			{Key: "update-then-remove"},
		},
	})
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("not-changed-at-all"), "not changed")
	rs.Set(pathtree.PathOf("update-then-remove"), "initial")
	rs.Set(pathtree.PathOf("remove-then-update"), "initial")

	u1.Merge(u2)
	err := u1.Apply(rs)

	assert.NoError(t, err)
	assert.Equal(t,
		map[string]any{
			"not-changed-at-all": "not changed",
			"remove-then-update": int64(7),
		},
		rs.ToNestedMaps())
}

func TestUpdates_Merge_NilMakesNoChanges(t *testing.T) {
	u := runsummary.NoUpdates()

	u.Merge(nil)

	assert.True(t, u.IsEmpty())
}

func TestUpdates_FromProto(t *testing.T) {
	rs := runsummary.New()

	err := runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "invalid-but-removed", ValueJson: "<not valid JSON>"},
			{NestedKey: []string{"good", "key"}, ValueJson: "123"},
		},
		Remove: []*spb.SummaryItem{
			{Key: "invalid-but-removed"},
		},
	}).Apply(rs)

	assert.NoError(t, err)
	assert.Equal(t,
		map[string]any{
			"good": map[string]any{
				"key": int64(123),
			},
		},
		rs.ToNestedMaps())
}

func TestUpdates_IsEmpty(t *testing.T) {
	testCases := []struct {
		name    string
		updates *runsummary.Updates
		isEmpty bool
	}{
		{
			name:    "nil is empty",
			updates: nil,
			isEmpty: true,
		},
		{
			name:    "NoUpdates is empty",
			updates: runsummary.NoUpdates(),
			isEmpty: true,
		},
		{
			name:    "updates from empty proto is empty",
			updates: runsummary.FromProto(&spb.SummaryRecord{}),
			isEmpty: true,
		},
		{
			name: "non-empty updates is not empty",
			updates: runsummary.FromProto(&spb.SummaryRecord{
				Remove: []*spb.SummaryItem{{Key: "x"}},
			}),
			isEmpty: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.isEmpty, tc.updates.IsEmpty())
		})
	}
}
