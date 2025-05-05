package runbranch_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runbranch"
)

// Test that forked run id must be different from the current run id
func TestForkSameRunIDs(t *testing.T) {
	err := runbranch.NewForkBranch(
		"runid",
		"_step",
		0,
	).UpdateForFork(&runbranch.RunParams{RunID: "runid"})

	assert.NotNil(t, err)
	assert.IsType(t, &runbranch.BranchError{}, err)
	assert.NotNil(t, err.(*runbranch.BranchError).Response)
}

// Test that forked metric name must be "_step", which is the only supported
// metric name currently
func TestForkUnsupportedMetricName(t *testing.T) {

	err := runbranch.NewForkBranch(
		"runid",
		"other",
		0,
	).UpdateForFork(&runbranch.RunParams{RunID: "other"})

	assert.NotNil(t, err)
	assert.IsType(t, &runbranch.BranchError{}, err)
	assert.NotNil(t, err.(*runbranch.BranchError).Response)
}

// Test that GetUpdates correctly applies the changes to the run params
func TestForkGetUpdatesValid(t *testing.T) {
	params := &runbranch.RunParams{RunID: "other"}
	err := runbranch.NewForkBranch(
		"runid",
		"_step",
		10,
	).UpdateForFork(params)

	assert.Nil(t, err)
	assert.True(t, params.Forked)
	assert.Equal(t, int64(11), params.StartingStep)
}
