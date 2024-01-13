package sender_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server/stream/sender"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

func TestGetFileStreamOffset_NilReceiver(t *testing.T) {
	var resumeState *sender.ResumeState
	assert.Nil(t, resumeState.GetFileStreamOffset(), "GetFileStreamOffset should return nil when receiver is nil")
}

func TestGetFileStreamOffset_Empty(t *testing.T) {
	logger := observability.NewNoOpLogger()
	resumeState := sender.NewResumeState(logger, "")
	assert.Empty(t, resumeState.GetFileStreamOffset(), "GetFileStreamOffset should return an empty map when no offsets are set")
}

func TestGetFileStreamOffset_WithOffsets(t *testing.T) {
	logger := observability.NewNoOpLogger()
	resumeState := sender.NewResumeState(logger, "")
	resumeState.AddOffset(1, 100)
	offsets := resumeState.GetFileStreamOffset()
	assert.Equal(t, 100, offsets[1], "GetFileStreamOffset should return correct offset for a given key")
}

func TestAddOffset_InitializeMap(t *testing.T) {
	logger := observability.NewNoOpLogger()
	resumeState := sender.NewResumeState(logger, "")
	resumeState.AddOffset(1, 100)
	assert.Equal(t, 100, resumeState.FileStreamOffset[1], "AddOffset should initialize map and add offset correctly")
}

func TestAddOffset_UpdateExistingMap(t *testing.T) {
	logger := observability.NewNoOpLogger()
	resumeState := sender.NewResumeState(logger, "")
	resumeState.AddOffset(1, 100) // First add
	resumeState.AddOffset(1, 200) // Update
	assert.Equal(t, 200, resumeState.FileStreamOffset[1], "AddOffset should update existing offset correctly")
}

func createBucketRawData(historyLineCount, eventsLineCount, logLineCount int, history, config, summaryMetrics *string, tags []string) *gql.RunResumeStatusModelProjectBucketRun {
	summaryMetricsData := appender(summaryMetrics, "null")
	historyData := appender(history, "null")
	configData := appender(config, "null")

	return &gql.RunResumeStatusModelProjectBucketRun{
		HistoryLineCount: &historyLineCount,
		EventsLineCount:  &eventsLineCount,
		LogLineCount:     &logLineCount,
		HistoryTail:      historyData,
		Config:           configData,
		SummaryMetrics:   summaryMetricsData,
		Tags:             tags,
	}
}

func appender(target *string, defaultVal string) *string {
	if target == nil {
		return &defaultVal
	}
	return target
}

func TestUpdate(t *testing.T) {
	logger := observability.NewNoOpLogger()

	validHistory := `["{\"_step\":1,\"_runtime\":50}"]`
	validHistoryStep0 := `["{\"_step\":0}"]`
	validSummary := `{"loss": 0.5}`
	validConfig := `{"lr": {"value": 0.001}}`
	invalidHistoryOrConfig := `{"_step":0}`
	invalidHistory := `["invalid_history"]`
	invalidConfig := `{"_step": {"other": 2}}`

	testCases := []struct {
		name                   string
		resumeMode             string
		bucket                 *gql.RunResumeStatusModelProjectBucketRun
		run                    *pb.RunRecord
		expectResumed          bool
		expectStartingStep     int64
		expectRuntime          int32
		expectSummaryUpdate    bool
		expectConfigUpdate     bool
		expectTagsUpdate       bool
		expectError            bool
		expectedErrorSubstring string
	}{
		{
			name:                   "nonexistent_run_must_resume",
			resumeMode:             "must",
			bucket:                 nil,
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "The value 'must' is not a valid option for resuming a run (test/abc123) that does not exist.",
		},
		{
			name:                   "existing_run_never_resume",
			resumeMode:             "never",
			bucket:                 createBucketRawData(0, 0, 0, nil, nil, nil, nil),
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "The value 'never' is not a valid option for resuming a run (test/abc123) that already exists.",
		},
		{
			name:               "valid_resume_history",
			resumeMode:         "must",
			bucket:             createBucketRawData(1, 0, 0, &validHistory, nil, nil, nil),
			run:                &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:      true,
			expectStartingStep: 2,
			expectRuntime:      50,
			expectError:        false,
		},
		{
			name:               "valid_resume_history_step_0",
			resumeMode:         "must",
			bucket:             createBucketRawData(0, 0, 0, nil, nil, nil, nil),
			run:                &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:      true,
			expectStartingStep: 0,
			expectError:        false,
		},
		{
			name:               "valid_resume_history_step_0_line_count_1",
			resumeMode:         "must",
			bucket:             createBucketRawData(1, 0, 0, &validHistoryStep0, nil, nil, nil),
			run:                &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:      true,
			expectStartingStep: 1,
			expectError:        false,
		},
		{
			name:                "valid_resume_summary",
			resumeMode:          "must",
			bucket:              createBucketRawData(0, 0, 0, nil, nil, &validSummary, nil),
			run:                 &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:       true,
			expectSummaryUpdate: true,
			expectError:         false,
		},
		{
			name:               "valid_resume_config",
			resumeMode:         "must",
			bucket:             createBucketRawData(0, 0, 0, nil, &validConfig, nil, nil),
			run:                &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:      true,
			expectConfigUpdate: true,
			expectError:        false,
		},
		{
			name:             "valid_resume_tags",
			resumeMode:       "must",
			bucket:           createBucketRawData(0, 0, 0, nil, nil, nil, []string{"tag1", "tag2"}),
			run:              &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:    true,
			expectTagsUpdate: true,
			expectError:      false,
		},
		{
			name:                   "invalid_resume_history_tail",
			resumeMode:             "must",
			bucket:                 createBucketRawData(0, 0, 0, &invalidHistoryOrConfig, nil, nil, nil),
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "failed to unmarshal history tail",
		},
		{
			name:                   "invalid_resume_history_tail_map",
			resumeMode:             "must",
			bucket:                 createBucketRawData(0, 0, 0, &invalidHistory, nil, nil, nil),
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "failed to unmarshal history tail map",
		},
		{
			name:                   "invalid_resume_summary",
			resumeMode:             "must",
			bucket:                 createBucketRawData(0, 0, 0, nil, nil, &invalidHistory, nil),
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "failed to unmarshal summary metrics",
		},
		{
			name:                   "invalid_resume_config",
			resumeMode:             "must",
			bucket:                 createBucketRawData(0, 0, 0, nil, &invalidHistory, nil, nil),
			run:                    &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed:          false,
			expectError:            true,
			expectedErrorSubstring: "failed to unmarshal config",
		},
		{
			name:          "invalid_resume_config_value",
			resumeMode:    "must",
			bucket:        createBucketRawData(0, 0, 0, nil, &invalidHistoryOrConfig, nil, nil),
			run:           &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed: true,
			expectError:   false,
		},
		{
			name:          "invalid_resume_config_no_value",
			resumeMode:    "must",
			bucket:        createBucketRawData(0, 0, 0, nil, &invalidConfig, nil, nil),
			run:           &pb.RunRecord{Project: "test", RunId: "abc123"},
			expectResumed: true,
			expectError:   false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			rs := sender.NewResumeState(logger, tc.resumeMode)
			fakeResp := &gql.RunResumeStatusResponse{
				Model: &gql.RunResumeStatusModelProject{
					Bucket: tc.bucket,
				},
			}

			configCopy := make(map[string]interface{})
			_, err := rs.Update(fakeResp, tc.run, configCopy)

			if tc.expectError {
				require.Error(t, err, "Expected error in Update")
				require.Contains(t, err.Error(), tc.expectedErrorSubstring)
			} else {
				require.NoError(t, err, "Unexpected error in Update")
				assert.Equal(t, tc.expectResumed, tc.run.Resumed, "Unexpected resumed state")

				if tc.expectStartingStep > 0 {
					assert.Equal(t, tc.expectStartingStep, tc.run.StartingStep, "Unexpected starting step")
				}

				if tc.expectRuntime > 0 {
					assert.Equal(t, tc.expectRuntime, tc.run.Runtime, "Unexpected runtime")
				}

				if tc.expectSummaryUpdate {
					require.Len(t, tc.run.Summary.Update, 1)
					assert.Equal(t, "loss", tc.run.Summary.Update[0].Key)
				}

				if tc.expectConfigUpdate {
					require.Len(t, configCopy, 1)
					value, ok := configCopy["lr"]
					require.True(t, ok, "Expected key 'lr' in config")
					assert.Equal(t, 0.001, value)
				}

				if tc.expectTagsUpdate {
					require.Len(t, tc.run.Tags, 2)
					assert.Contains(t, tc.run.Tags, "tag1")
					assert.Contains(t, tc.run.Tags, "tag2")
				}
			}
		})
	}
}
