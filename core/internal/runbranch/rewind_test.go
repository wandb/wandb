package runbranch_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runbranch"
)

func TestDifferentRunIDs(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	rb := runbranch.NewRewindBranch(ctx, mockGQL, "rewind", "_step", 0)
	params, err := rb.GetUpdates(&runbranch.RunParams{
		RunID: "other",
	}, runbranch.RunPath{RunID: "other"})
	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestUnsupportedMetricName(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	rb := runbranch.NewRewindBranch(ctx, mockGQL, "runid", "other", 0)
	params, err := rb.GetUpdates(&runbranch.RunParams{
		RunID: "runid",
	}, runbranch.RunPath{RunID: "runid"})
	assert.Nil(t, params, "GetUpdates should return nil params")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestGetUpdatesNoResponse(t *testing.T) {
	ctx := context.TODO()
	mockGQL := gqlmock.NewMockClient()
	nilResponse, _ := json.Marshal(nil)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(nilResponse),
	)
	rb := runbranch.NewRewindBranch(ctx, mockGQL, "runid", "_step", 0)
	params, err := rb.GetUpdates(&runbranch.RunParams{
		RunID: "runid",
	}, runbranch.RunPath{RunID: "runid"})
	assert.Nil(t, params, "GetUpdates should return nil params")
	fmt.Println(err)
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}
