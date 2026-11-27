package runsummary_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runsummary"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestUpdates_Apply_InsertsAndRemoves(t *testing.T) {
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("x"), 1)
	rs.Set(pathtree.PathOf("y"), 2)

	runsummary.NoUpdates().
		Set(pathtree.PathOf("x"), 3.5).
		Set(pathtree.PathOf("z"), "this is z").
		Remove(pathtree.PathOf("y")).
		Apply(rs)

	assert.Equal(t,
		map[string]any{
			"x": float64(3.5),
			"z": "this is z",
		},
		rs.ToNestedMaps())
}

func TestUpdates_Apply_NilMakesNoChanges(t *testing.T) {
	rs := runsummary.New()

	var nilUpdates *runsummary.Updates

	assert.NotPanics(t, func() { nilUpdates.Apply(rs) })
}

func TestUpdates_Merge(t *testing.T) {
	u1 := runsummary.NoUpdates().
		Set(pathtree.PathOf("update-then-remove"), "test").
		Remove(pathtree.PathOf("remove-then-update"))
	u2 := runsummary.NoUpdates().
		Set(pathtree.PathOf("remove-then-update"), int64(7)).
		Remove(pathtree.PathOf("update-then-remove"))
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("not-changed-at-all"), "not changed")
	rs.Set(pathtree.PathOf("update-then-remove"), "initial")
	rs.Set(pathtree.PathOf("remove-then-update"), "initial")

	u1.Merge(u2)
	u1.Apply(rs)

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
	rs.Set(pathtree.PathOf("to-be-removed"), 99)

	updates, err := runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{
			{Key: "invalid", ValueJson: "Ã"},
			{NestedKey: []string{"good", "key"}, ValueJson: "123"},
		},
		Remove: []*spb.SummaryItem{
			{Key: "to-be-removed"},
		},
	})
	updates.Apply(rs)

	assert.ErrorContains(t, err, "Ã") // error only includes 1 character
	assert.Equal(t,
		map[string]any{
			"good": map[string]any{
				"key": int64(123),
			},
		},
		rs.ToNestedMaps())
}

func TestUpdates_Set(t *testing.T) {
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("x"), int64(1))
	rs.Set(pathtree.PathOf("y"), 1.23)

	runsummary.NoUpdates().
		Set(pathtree.PathOf("x"), int64(999)).
		Apply(rs)

	assert.Equal(t,
		map[string]any{
			"x": int64(999),
			"y": float64(1.23),
		},
		rs.ToNestedMaps())
}

func TestUpdates_Remove(t *testing.T) {
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("x"), int64(1))
	rs.Set(pathtree.PathOf("y"), 1.23)

	runsummary.NoUpdates().
		Remove(pathtree.PathOf("y")).
		Apply(rs)

	assert.Equal(t,
		map[string]any{
			"x": int64(1),
		},
		rs.ToNestedMaps())
}

func TestUpdates_Ignore(t *testing.T) {
	rs := runsummary.New()
	rs.Set(pathtree.PathOf("x"), int64(1))
	rs.Set(pathtree.PathOf("y"), 1.23)

	runsummary.NoUpdates().
		Set(pathtree.PathOf("x"), int64(999)).
		Ignore(pathtree.PathOf("x")).
		Apply(rs)

	runsummary.NoUpdates().
		Remove(pathtree.PathOf("y")).
		Ignore(pathtree.PathOf("y")).
		Apply(rs)

	assert.Equal(t,
		map[string]any{
			"x": int64(1),
			"y": float64(1.23),
		},
		rs.ToNestedMaps())
}

func TestUpdates_IgnoreStep_NilIsNoOp(t *testing.T) {
	var updates *runsummary.Updates

	assert.NotPanics(t, func() { updates.Ignore(pathtree.PathOf("x")) })
}

func TestUpdates_IsEmpty(t *testing.T) {
	updatesFromEmptyProto, err := runsummary.FromProto(&spb.SummaryRecord{})
	require.NoError(t, err)

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
			updates: updatesFromEmptyProto,
			isEmpty: true,
		},
		{
			name:    "non-empty updates is not empty",
			updates: runsummary.NoUpdates().Remove(pathtree.PathOf("x")),
			isEmpty: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			assert.Equal(t, tc.isEmpty, tc.updates.IsEmpty())
		})
	}
}
