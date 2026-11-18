package runsummary_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/runsummary"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// set returns updates that set key to the JSON value.
func set(key, valueJSON string) *runsummary.Updates {
	return runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: key, ValueJson: valueJSON}},
	})
}

// serialize calls Serialize and returns its JSON as a string.
func serialize(
	t *testing.T,
	s *runsummary.SummaryAndDelta,
	preferDelta bool,
) (string, bool) {
	t.Helper()
	json, isDelta, err := s.Serialize(preferDelta)
	require.NoError(t, err)
	return string(json), isDelta
}

func TestSummaryAndDelta_SerializesDeltaOnlyWhenTrackedAndPreferred(t *testing.T) {
	s := runsummary.NewSummaryAndDelta()
	require.NoError(t, s.Apply(set("a", "1")))

	// Changes aren't tracked until ResetDelta(true).
	json, isDelta := serialize(t, s, true)
	assert.JSONEq(t, `{"a":1}`, json)
	assert.False(t, isDelta)

	s.ResetDelta(true)
	require.NoError(t, s.Apply(set("b", "2")))

	json, isDelta = serialize(t, s, false)
	assert.JSONEq(t, `{"a":1,"b":2}`, json)
	assert.False(t, isDelta)
	json, isDelta = serialize(t, s, true)
	assert.JSONEq(t, `{"b":2}`, json)
	assert.True(t, isDelta)
}

func TestSummaryAndDelta_RemovalSerializesFull(t *testing.T) {
	s := runsummary.NewSummaryAndDelta()
	require.NoError(t, s.Apply(set("a", "1")))
	s.ResetDelta(true)

	require.NoError(t, s.Apply(runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: "b", ValueJson: "2"}},
		Remove: []*spb.SummaryItem{{Key: "a"}},
	})))

	json, isDelta := serialize(t, s, true)
	assert.JSONEq(t, `{"b":2}`, json)
	assert.False(t, isDelta)
}

func TestSummaryAndDelta_EmptyDeltaIsNil(t *testing.T) {
	s := runsummary.NewSummaryAndDelta()
	s.ResetDelta(true)
	require.NoError(t, s.Apply(runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{Key: "acc", ValueJson: "0.5", FromHistory: true}},
	})))

	json, isDelta, err := s.Serialize(true)

	require.NoError(t, err)
	assert.Nil(t, json)
	assert.False(t, isDelta)
	assert.False(t, s.DeltaSinceFull())
}

func TestSummaryAndDelta_DeltaSinceFull(t *testing.T) {
	s := runsummary.NewSummaryAndDelta()
	s.ResetDelta(true)
	require.NoError(t, s.Apply(set("a", "1")))

	serialize(t, s, true)
	assert.True(t, s.DeltaSinceFull())

	serialize(t, s, false)
	assert.False(t, s.DeltaSinceFull())
}

func TestSummaryAndDelta_NilIsNoOp(t *testing.T) {
	var s *runsummary.SummaryAndDelta

	s.ResetDelta(true)

	assert.False(t, s.DeltaSinceFull())
}
