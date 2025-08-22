package runbranch_test

import (
	"context"
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/runbranch"
	"github.com/wandb/wandb/core/internal/runconfig"
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

	err := runbranch.NewRewindBranch(
		ctx, mockGQL, "rewind", "_step", 0,
	).UpdateForRewind(
		&runbranch.RunParams{RunID: "other"},
		runconfig.New(),
	)

	assert.NotNil(t, err)
	assert.IsType(t, &runbranch.BranchError{}, err)
	assert.NotNil(t, err.(*runbranch.BranchError).Response)
}

// Test that rewind metric name must be "_step", which is the only supported
// metric name currently
func TestRewindUnsupportedMetricName(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()

	err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "other", 0,
	).UpdateForRewind(
		&runbranch.RunParams{RunID: "runid"},
		runconfig.New(),
	)

	assert.NotNil(t, err)
	assert.IsType(t, &runbranch.BranchError{}, err)
	assert.NotNil(t, err.(*runbranch.BranchError).Response)
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when the response is nil
func TestUpdateForRewindNoResponse(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	nilResponse, _ := json.Marshal(nil)
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(nilResponse),
	)

	err := runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).UpdateForRewind(
		&runbranch.RunParams{RunID: "runid"},
		runconfig.New(),
	)

	assert.NotNil(t, err)
	assert.IsType(t, &runbranch.BranchError{}, err)
	assert.NotNil(t, err.(*runbranch.BranchError).Response)
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when a valid response
func TestUpdateForRewindWithResponse(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:               "storageid",
					Name:             "runid",
					DisplayName:      nullify.NilIfZero("rewound"),
					SweepName:        nullify.NilIfZero("sweep"),
					HistoryLineCount: nullify.NilIfZero(10),
					Config:           nullify.NilIfZero(`{"lr": {"value": 0.001}}`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	config := runconfig.New()
	params := &runbranch.RunParams{RunID: "runid"}
	err = runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 10,
	).UpdateForRewind(params, config)

	assert.Nil(t, err)
	assert.Equal(t, int64(11), params.StartingStep)
	assert.Equal(t, 10, params.FileStreamOffset[filestream.HistoryChunk])
	assert.True(t, params.Forked)
	assert.Equal(t, "rewound", params.DisplayName)
	assert.Equal(t, "sweep", params.SweepID)
	assert.Equal(t, "storageid", params.StorageID)

	configJSON, err := config.Serialize(runconfig.FormatJson)
	assert.Nil(t, err)
	assert.JSONEq(t, `{"lr": {"value": 0.001}}`, string(configJSON))
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when a valid response with no config
func TestUpdateForRewindConfigNil(t *testing.T) {

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

	config := runconfig.New()
	params := &runbranch.RunParams{RunID: "runid"}
	err = runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).UpdateForRewind(params, config)

	assert.Nil(t, err)
	assert.True(t, params.Forked)
	assert.Empty(t, config.CloneTree())
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when a valid response with invalid config
func TestUpdateForRewindInvalidConfig(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: nullify.NilIfZero("invalid"),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	config := runconfig.New()
	params := &runbranch.RunParams{RunID: "runid"}
	err = runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).UpdateForRewind(params, config)

	assert.NotNil(t, err)
	assert.True(t, params.Forked)
	assert.Empty(t, config.CloneTree())
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when a valid response with invalid type config
func TestUpdateForRewindInvalidTypeConfig(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()
	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: nullify.NilIfZero(`"invalid"`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	config := runconfig.New()
	params := &runbranch.RunParams{RunID: "runid"}
	err = runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).UpdateForRewind(params, config)

	assert.NotNil(t, err)
	assert.True(t, params.Forked)
	assert.Empty(t, config.CloneTree())
}

// Test that UpdateForRewind correctly applies the changes to the run params
// when a valid response with no value config
func TestUpdateForRewindConfigNoValue(t *testing.T) {

	ctx := context.Background()
	mockGQL := gqlmock.NewMockClient()

	response, err := json.Marshal(
		RewindResponse{
			RewindRun: RewindRun{
				RewoundRun: RewoundRun{
					ID:     "",
					Name:   "",
					Config: nullify.NilIfZero(`{"lr": 0.0001}`),
				},
			},
		},
	)
	assert.Nil(t, err, "json.Marshal should not return an error")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RewindRun"),
		string(response),
	)

	config := runconfig.New()
	params := &runbranch.RunParams{RunID: "runid"}
	err = runbranch.NewRewindBranch(
		ctx, mockGQL, "runid", "_step", 0,
	).UpdateForRewind(params, config)

	assert.NotNil(t, err)
	assert.True(t, params.Forked)
	assert.Empty(t, config.CloneTree())
}
