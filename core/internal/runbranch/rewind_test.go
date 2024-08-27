package runbranch_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/pkg/utils"
)

type RewindResponse struct {
	RewindRun RewindRun `json:"rewindRun"`
}
type RewindRun struct {
	RewoundRun RewoundRun `json:"rewoundRun"`
}
type RewoundRun struct {
	ID               string  `json:"id"`
	Name             string  `json:"name"`
	DisplayName      *string `json:"displayName"`
	SweepName        *string `json:"sweepName"`
	HistoryLineCount *int    `json:"historyLineCount"`
	Config           *string `json:"config"`
}

// Test that rewind run id must be different from the current run id
func TestRewindDifferentRunIDs(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "rewind", "_step", 0,
	).ApplyChanges(
		&runbranch.RunParams{RunID: "other"},
		runbranch.RunPath{RunID: "other"},
	)

	assert.Nil(t, params, "ApplyChanges should return nil params")
	assert.NotNil(t, err, "ApplyChanges should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "ApplyChanges should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

// Test that rewind metric name must be "_step", which is the only supported
// metric name currently
func TestRewindUnsupportedMetricName(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "other", 0,
	).ApplyChanges(
		&runbranch.RunParams{RunID: "runid"},
		runbranch.RunPath{RunID: "runid"},
	)

	assert.Nil(t, params, "ApplyChanges should return nil params")
	assert.NotNil(t, err, "ApplyChanges should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "ApplyChanges should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when the response is nil
func TestApplyChangesNoResponse(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	nilResponse, _ := json.Marshal(nil)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(nilResponse),
	)

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).ApplyChanges(&runbranch.RunParams{
		RunID: "runid",
	}, runbranch.RunPath{RunID: "runid"},
	)

	assert.Nil(t, params, "ApplyChanges should return nil params")
	assert.NotNil(t, err, "ApplyChanges should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "ApplyChanges should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when a valid response
func TestRewindApplyChangesWithResponse(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:               "storageid",
					Name:             "runid",
					DisplayName:      utils.NilIfZero("rewound"),
					SweepName:        utils.NilIfZero("sweep"),
					HistoryLineCount: utils.NilIfZero(10),
					Config:           utils.NilIfZero(`{"lr": {"value": 0.001}}`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 10,
	).ApplyChanges(&runbranch.RunParams{
		RunID: "runid",
	}, runbranch.RunPath{RunID: "runid"},
	)

	assert.Nil(t, err, "ApplyChanges should not return an error")
	assert.NotNil(t, params, "ApplyChanges should return params")
	assert.Equal(t, "runid", params.RunID, "RunID should be set")
	assert.Equal(t, int64(11), params.StartingStep, "DisplayName should be set")
	assert.Equal(t, 10, params.FileStreamOffset[filestream.HistoryChunk], "FileStreamOffset should be set")
	assert.True(t, params.Forked, "Intialized should be set")
	assert.Equal(t, "rewound", params.DisplayName, "DisplayName should be set")
	assert.Equal(t, "sweep", params.SweepID, "SweepID should be set")
	assert.Equal(t, "storageid", params.StorageID, "StorageID should be set")

	paramsConfig, err := json.Marshal(params.Config)
	assert.Nil(t, err, "json.Marshal should not return an error")
	assert.JSONEq(t, `{"lr" :0.001}`, string(paramsConfig), "Config should be set")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when a valid response with no config
func TestRewindApplyChangesConfigNil(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:   "",
					Name: "",
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).ApplyChanges(
		&runbranch.RunParams{
			RunID: "runid",
		}, runbranch.RunPath{RunID: "runid"},
	)

	assert.Nil(t, err, "ApplyChanges should not return an error")
	assert.NotNil(t, params, "ApplyChanges should return params")
	assert.Equal(t, "runid", params.RunID, "RunID should be set")
	assert.True(t, params.Forked, "Forked should be set")
	assert.Nil(t, params.Config, "Config should be nil")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when a valid response with invalid config
func TestRewindApplyChangesInvalidConfig(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: utils.NilIfZero("invalid"),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).ApplyChanges(
		&runbranch.RunParams{
			RunID: "runid",
		}, runbranch.RunPath{RunID: "runid"},
	)

	assert.NotNil(t, err, "ApplyChanges should not return an error")
	assert.NotNil(t, params, "ApplyChanges should return params")
	assert.Equal(t, "runid", params.RunID, "RunID should be set")
	assert.True(t, params.Forked, "Forked should be set")
	assert.Nil(t, params.Config, "Config should be nil")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when a valid response with invalid type config
func TestRewindApplyChangesInvalidTypeConfig(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: utils.NilIfZero(`"invalid"`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).ApplyChanges(
		&runbranch.RunParams{RunID: "runid"}, runbranch.RunPath{
			RunID: "runid",
		},
	)

	assert.NotNil(t, err, "ApplyChanges should not return an error")
	assert.NotNil(t, params, "ApplyChanges should return params")
	assert.Equal(t, "runid", params.RunID, "RunID should be set")
	assert.True(t, params.Forked, "Forked should be set")
	assert.Nil(t, params.Config, "Config should be nil")
}

// Test that ApplyChanges correctly applies the changes to the run params
// when a valid response with no value config
func TestRewindApplyChangesConfigNoValue(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()

	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: utils.NilIfZero(`{"lr": 0.0001}`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)
	params, err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).ApplyChanges(
		&runbranch.RunParams{RunID: "runid"}, runbranch.RunPath{
			RunID: "runid",
		},
	)

	assert.NotNil(t, err, "ApplyChanges should not return an error")
	assert.NotNil(t, params, "ApplyChanges should return params")
	assert.Equal(t, "runid", params.RunID, "RunID should be set")
	assert.True(t, params.Forked, "Forked should be set")
	assert.Nil(t, params.Config, "Config should be nil")
}
