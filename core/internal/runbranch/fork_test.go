package runbranch_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runbranch"
)

func TestForkSameRunIDs(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	fb := runbranch.NewForkBranch(ctx, mockGQL, "runid", "_step", 0)
	params, err := fb.GetUpdates(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "runid"})
	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestForkUnsupportedMetricName(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	fb := runbranch.NewForkBranch(ctx, mockGQL, "runid", "other", 0)
	params, err := fb.GetUpdates(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "other"})
	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestForkGetUpdatesValid(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	fb := runbranch.NewForkBranch(ctx, mockGQL, "runid", "_step", 10)
	params, err := fb.GetUpdates(
		&runbranch.RunParams{},
		runbranch.RunPath{RunID: "other"},
	)

	assert.Nil(t, err, "GetUpdates should not return an error")
	assert.NotNil(t, params, "GetUpdates should return params")
	assert.True(t, params.Forked, "GetUpdates should set Forked to true")
	assert.Equal(t, int64(11), params.StartingStep, "GetUpdates should set StartingStep")
}
