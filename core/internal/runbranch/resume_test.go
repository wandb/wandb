package runbranch_test

import (
	"context"
	"encoding/json"
	"fmt"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runbranch"
)

type ResumeResponse struct {
	Model Model `json:"model"`
}
type Model struct {
	Bucket Bucket `json:"bucket"`
}
type Bucket struct {
	Name             string   `json:"name"`
	HistoryLineCount int      `json:"historyLineCount"`
	EventsLineCount  int      `json:"eventsLineCount"`
	LogLineCount     int      `json:"logLineCount"`
	HistoryTail      *string  `json:"historyTail"`
	SummaryMetrics   *string  `json:"summaryMetrics"`
	Config           *string  `json:"config"`
	EventsTail       string   `json:"eventsTail"`
	Tags             []string `json:"tags"`
	WandbConfig      string   `json:"wandbConfig"`
}

func TestNeverResumeEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		`{}`,
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"never")
	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, params, "GetUpdates should return nil when response is empty")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestAllowResumeEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		`{}`,
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"allow")
	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, params, "GetUpdates should return nil when response is empty")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		`{}`,
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")
	updates, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, updates, "GetUpdates should return nil when response is invalid")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestNeverResumeNoneEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()
	history := "[]"
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"never")
	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, params, "GetUpdates should return nil when response is empty")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
}

func TestAllowResumeNoneEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := "[]"
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"allow")
	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeNoneEmptyResponse(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	hisotry := "[]"
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &hisotry,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")
	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")
	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeValidHistory(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := `["{\"_step\":1,\"_runtime\":50}"]`
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:             "FakeName",
				HistoryLineCount: 1,
				HistoryTail:      &history,
				SummaryMetrics:   &summary,
				Config:           &config,
				EventsTail:       "[]",
				WandbConfig:      `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")
	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(2), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(50), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeZeroHisotry(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := "[]"
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")
	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(0), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(0), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeHistoryTailStepZero(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := `["{\"_step\":1}"]`
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(1), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(0), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeValidSummary(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := `["{\"_step\":1, \"_runtime\":10}"]`
	config := "{}"
	summary := `{"loss": 0.5, "_runtime": 20, "wandb": {"runtime": 30}}`
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:             "FakeName",
				HistoryLineCount: 1,
				HistoryTail:      &history,
				SummaryMetrics:   &summary,
				Config:           &config,
				EventsTail:       "[]",
				WandbConfig:      `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(2), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(30), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")

	// check the value of the summary are correct
	assert.Len(t, params.Summary, 3, "GetUpdates should return correct summary")
	assert.Equal(t, 0.5, params.Summary["loss"], "GetUpdates should return correct summary")
	assert.Equal(t, int64(20), params.Summary["_runtime"], "GetUpdates should return correct summary")
	assert.Equal(t, int64(30), params.Summary["wandb"].(map[string]any)["runtime"], "GetUpdates should return correct summary")
	fmt.Println(params.Summary)

	assert.Nil(t, err, "GetUpdates should not return an error")
}

func TestMustResumeValidConfig(t *testing.T) {

	mockGQL := gqlmock.NewMockClient()

	history := "[]"
	config := `{"lr": {"value": 0.001}}`
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, err, "GetUpdates should not return an error")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(0), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(0), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
	assert.Len(t, params.Config, 1, "GetUpdates should return correct config")
	assert.Equal(t, 0.001, params.Config["lr"], "GetUpdates should return correct config")
}

func TestMustResumeValidTags(t *testing.T) {
	mockGQL := gqlmock.NewMockClient()

	history := "[]"
	config := "{}"
	summary := "{}"
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     "[]",
				Tags:           []string{"tag1", "tag2"},
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, err, "GetUpdates should not return an error")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(0), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(0), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
	assert.Len(t, params.Tags, 2, "GetUpdates should return correct tags")
	assert.Contains(t, params.Tags, "tag1", "GetUpdates should return correct tags")
	assert.Contains(t, params.Tags, "tag2", "GetUpdates should return correct tags")
}

func TestMustResumeValidEvents(t *testing.T) {

	mockGQL := gqlmock.NewMockClient()

	history := `["{\"_runtime\":10}"]`
	config := "{}"
	summary := `{ "_runtime": 20, "wandb": {"runtime": 30}}`
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:           "FakeName",
				HistoryTail:    &history,
				SummaryMetrics: &summary,
				Config:         &config,
				EventsTail:     `["{\"_runtime\":40}", "{\"_runtime\":50}"]`,
				Tags:           []string{"tag1", "tag2"},
				WandbConfig:    `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.Nil(t, err, "GetUpdates should not return an error")
	assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
	assert.Equal(t, int64(0), params.StartingStep, "GetUpdates should return correct starting step")
	assert.Equal(t, int32(50), params.Runtime, "GetUpdates should return correct runtime")
	assert.True(t, params.Resumed, "GetUpdates should return correct resumed state")
}

func TestMustResumeNullValue(t *testing.T) {

	config := "{}"
	summary := "{}"
	history := "[]"
	testCase := []struct {
		name     string
		response ResumeResponse
	}{
		{
			name: "NullHistory",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:           "FakeName",
						SummaryMetrics: &summary,
						Config:         &config,
						EventsTail:     "[]",
						WandbConfig:    `{"t": 1}`,
					},
				},
			},
		},
		{
			name: "NullSummary",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:        "FakeName",
						HistoryTail: &history,
						Config:      &config,
						EventsTail:  "[]",
					},
				},
			},
		},
		{
			name: "NullConfig",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:           "FakeName",
						HistoryTail:    &history,
						SummaryMetrics: &summary,
						EventsTail:     "[]",
					},
				},
			},
		},
	}
	for _, tc := range testCase {
		t.Run(tc.name, func(t *testing.T) {

			mockGQL := gqlmock.NewMockClient()

			jsonData, err := json.MarshalIndent(tc.response, "", "    ")
			assert.Nil(t, err, "Failed to marshal json data")

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunResumeStatus"),
				string(jsonData),
			)
			resumeState := runbranch.NewResumeBranch(
				context.Background(),
				mockGQL,
				"must")

			params, err := resumeState.GetUpdates("", "", "")
			assert.NotNil(t, err, "GetUpdates should return an error")
			assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
			assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
			assert.Nil(t, params, "GetUpdates should return nil when response is empty")
		})
	}
}

func TestAllowResumeNullValue(t *testing.T) {
	config := "{}"
	summary := "{}"
	history := "[]"
	testCase := []struct {
		name     string
		response ResumeResponse
	}{
		{
			name: "NullHistory",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:           "FakeName",
						SummaryMetrics: &summary,
						Config:         &config,
						EventsTail:     "[]",
						WandbConfig:    `{"t": 1}`,
					},
				},
			},
		},
		{
			name: "NullSummary",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:        "FakeName",
						HistoryTail: &history,
						Config:      &config,
						EventsTail:  "[]",
						WandbConfig: `{"t": 1}`,
					},
				},
			},
		},
		{
			name: "NullConfig",
			response: ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:           "FakeName",
						HistoryTail:    &history,
						SummaryMetrics: &summary,
						EventsTail:     "[]",
						WandbConfig:    `{"t": 1}`,
					},
				},
			},
		},
	}
	for _, tc := range testCase {
		t.Run(tc.name, func(t *testing.T) {

			mockGQL := gqlmock.NewMockClient()

			jsonData, err := json.MarshalIndent(tc.response, "", "    ")
			assert.Nil(t, err, "Failed to marshal json data")

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunResumeStatus"),
				string(jsonData),
			)
			resumeState := runbranch.NewResumeBranch(
				context.Background(),
				mockGQL,
				"allow")

			params, err := resumeState.GetUpdates("", "", "")
			assert.NotNil(t, err, "GetUpdates should return an error")
			if _, ok := err.(*runbranch.BranchError); ok {
				t.Errorf("expected a BranchError but got %T", err)
			}

			assert.Nil(t, params, "GetUpdates should return nil when response is empty")
		})
	}
}

func TestMustResumeInvalidHistory(t *testing.T) {

	testCases := []struct {
		name  string
		value string
	}{
		{
			name:  "InvalidContent",
			value: `["invalid_history"]`,
		},
		{
			name:  "InvalidShape",
			value: `{"_step":0}`,
		},
	}
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			mockGQL := gqlmock.NewMockClient()

			config := "{}"
			summary := "{}"
			rr := ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:             "FakeName",
						HistoryLineCount: 0,
						EventsLineCount:  0,
						LogLineCount:     0,
						HistoryTail:      &tc.value,
						SummaryMetrics:   &summary,
						Config:           &config,
						EventsTail:       `[]`,
						WandbConfig:      `{"t": 1}`,
					},
				},
			}

			jsonData, err := json.MarshalIndent(rr, "", "    ")
			assert.Nil(t, err, "Failed to marshal json data")

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunResumeStatus"),
				string(jsonData),
			)
			resumeState := runbranch.NewResumeBranch(
				context.Background(),
				mockGQL,
				"must")

			params, err := resumeState.GetUpdates("", "", "")
			assert.NotNil(t, err, "GetUpdates should return an error")
			assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
			assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
			assert.Nil(t, params, "GetUpdates should return nil when response is empty")
		})
	}
}

func TestMustResumeInvalidSummary(t *testing.T) {

	mockGQL := gqlmock.NewMockClient()

	history := `[]`
	config := "{}"
	summary := `[]`
	rr := ResumeResponse{
		Model: Model{
			Bucket: Bucket{
				Name:             "FakeName",
				HistoryLineCount: 0,
				EventsLineCount:  0,
				LogLineCount:     0,
				HistoryTail:      &history,
				SummaryMetrics:   &summary,
				Config:           &config,
				EventsTail:       `[]`,
				WandbConfig:      `{"t": 1}`,
			},
		},
	}

	jsonData, err := json.MarshalIndent(rr, "", "    ")
	assert.Nil(t, err, "Failed to marshal json data")

	mockGQL.StubMatchOnce(
		gqlmock.WithOpName("RunResumeStatus"),
		string(jsonData),
	)
	resumeState := runbranch.NewResumeBranch(
		context.Background(),
		mockGQL,
		"must")

	params, err := resumeState.GetUpdates("", "", "")
	assert.NotNil(t, err, "GetUpdates should return an error")
	assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
	assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
	assert.Nil(t, params, "GetUpdates should return nil when response is empty")
}

func TestMustResumeInvalidConfig(t *testing.T) {

	testCases := []struct {
		name  string
		value string
	}{
		{
			name:  "ConfigList",
			value: `[]`,
		},
		{
			name:  "ConfigNotNested",
			value: `{"_step":0}`,
		},
		{
			name:  "ConfigNestedNotValue",
			value: `{"_step": {"runtime": 30}`,
		},
	}
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			history := `[]`
			summary := `{}`
			mockGQL := gqlmock.NewMockClient()

			rr := ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:             "FakeName",
						HistoryLineCount: 0,
						EventsLineCount:  0,
						LogLineCount:     0,
						HistoryTail:      &history,
						SummaryMetrics:   &summary,
						Config:           &tc.value,
						EventsTail:       `[]`,
						WandbConfig:      `{"t": 1}`,
					},
				},
			}

			jsonData, err := json.MarshalIndent(rr, "", "    ")
			assert.Nil(t, err, "Failed to marshal json data")

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunResumeStatus"),
				string(jsonData),
			)
			resumeState := runbranch.NewResumeBranch(
				context.Background(),
				mockGQL,
				"must")

			params, err := resumeState.GetUpdates("", "", "")
			assert.NotNil(t, err, "GetUpdates should return an error")
			assert.IsType(t, &runbranch.BranchError{}, err, "GetUpdates should return a BranchError")
			assert.NotNil(t, err.(*runbranch.BranchError).Response, "BranchError should have a response")
			assert.Nil(t, params, "GetUpdates should return nil when response is empty")
		})
	}
}

func TestNotNeverResumeFileStreamOffset(t *testing.T) {

	history := `[]`
	summary := `{}`
	config := `{}`

	testCases := []struct {
		name  string
		value string
	}{
		{
			name:  "Allow",
			value: "allow",
		},
		{
			name:  "Must",
			value: "must",
		},
	}
	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			mockGQL := gqlmock.NewMockClient()

			rr := ResumeResponse{
				Model: Model{
					Bucket: Bucket{
						Name:             "FakeName",
						HistoryLineCount: 10,
						EventsLineCount:  13,
						LogLineCount:     15,
						HistoryTail:      &history,
						SummaryMetrics:   &summary,
						Config:           &config,
						EventsTail:       `[]`,
						WandbConfig:      `{"t": 1}`,
					},
				},
			}

			jsonData, err := json.MarshalIndent(rr, "", "    ")
			assert.Nil(t, err, "Failed to marshal json data")

			mockGQL.StubMatchOnce(
				gqlmock.WithOpName("RunResumeStatus"),
				string(jsonData),
			)
			resumeState := runbranch.NewResumeBranch(
				context.Background(),
				mockGQL,
				tc.value)
			params, err := resumeState.GetUpdates("", "", "")
			assert.Nil(t, err, "GetUpdates should not return an error")
			assert.NotNil(t, params, "GetUpdates should return nil when response is empty")
			assert.Len(t, params.FileStreamOffset, 3, "GetUpdates should return correct file stream offset")
			assert.Equal(t, 10, params.FileStreamOffset[filestream.HistoryChunk], "GetUpdates should return correct file stream offset")
			assert.Equal(t, 13, params.FileStreamOffset[filestream.EventsChunk], "GetUpdates should return correct file stream offset")
			assert.Equal(t, 15, params.FileStreamOffset[filestream.OutputChunk], "GetUpdates should return correct file stream offset")
		})
	}
}
