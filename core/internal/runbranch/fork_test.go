package runbranch_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runbranch"
)

// Test that forked run id must be different from the current run id
func TestForkSameRunIDs(t *testing.T) {

	params, err := runbranch.NewForkBranch(
		"runid",
		"_step",
		0,
	).ApplyChanges(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "runid"},
	)

	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

// Test that forked metric name must be "_step", which is the only supported
// metric name currently
func TestForkUnsupportedMetricName(t *testing.T) {

	params, err := runbranch.NewForkBranch(
		"runid",
		"other",
		0,
	).ApplyChanges(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "other"},
	)

	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

// Test that GetUpdates correctly applies the changes to the run params
func TestForkGetUpdatesValid(t *testing.T) {

	params, err := runbranch.NewForkBranch(
		"runid",
		"_step",
		10,
	).ApplyChanges(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "other"},
	)

	assert.Nil(t, err, "GetUpdates should not return an error")
	assert.NotNil(t, params, "GetUpdates should return params")
	assert.True(t, params.Forked, "GetUpdates should set Forked to true")
	assert.Equal(t, int64(11), params.StartingStep, "GetUpdates should set StartingStep")
}
