package runbranching_test

// import (
// 	"testing"

// 	"github.com/stretchr/testify/assert"
// 	"github.com/stretchr/testify/require"
// 	"github.com/wandb/wandb/core/internal/gql"
// 	"github.com/wandb/wandb/core/internal/runbranching"
// 	"github.com/wandb/wandb/core/internal/runconfig"
// 	"github.com/wandb/wandb/core/pkg/observability"
// 	"github.com/wandb/wandb/core/pkg/service"
// )

// func TestGetFileStreamOffset_NilReceiver(t *testing.T) {
// 	var resumeState *runbranching.ResumeState
// 	assert.Nil(t, resumeState.GetFileStreamOffset(), "GetFileStreamOffset should return nil when receiver is nil")
// }

// func TestGetFileStreamOffset_Empty(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	resumeState := runbranching.NewResumeState(logger, runbranching.None)
// 	assert.Empty(t, resumeState.GetFileStreamOffset(), "GetFileStreamOffset should return an empty map when no offsets are set")
// }

// func TestGetFileStreamOffset_WithOffsets(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	resumeState := runbranching.NewResumeState(logger, runbranching.None)
// 	resumeState.AddOffset(1, 100)
// 	offsets := resumeState.GetFileStreamOffset()
// 	assert.Equal(t, 100, offsets[1], "GetFileStreamOffset should return correct offset for a given key")
// }

// func TestAddOffset_InitializeMap(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	resumeState := runbranching.NewResumeState(logger, runbranching.None)
// 	resumeState.AddOffset(1, 100)
// 	assert.Equal(t, 100, resumeState.FileStreamOffset[1], "AddOffset should initialize map and add offset correctly")
// }

// func TestAddOffset_UpdateExistingMap(t *testing.T) {
// 	logger := observability.NewNoOpLogger()
// 	resumeState := runbranching.NewResumeState(logger, runbranching.None)
// 	resumeState.AddOffset(1, 100) // First add
// 	resumeState.AddOffset(1, 200) // Update
// 	assert.Equal(t, 200, resumeState.FileStreamOffset[1], "AddOffset should update existing offset correctly")
// }

// func createBucketRawData(historyLineCount, eventsLineCount, logLineCount int, history, config, summary *string, tags []string, wandbConfig *string) *gql.RunResumeStatusModelProjectBucketRun {

// 	return &gql.RunResumeStatusModelProjectBucketRun{
// 		HistoryLineCount: &historyLineCount,
// 		EventsLineCount:  &eventsLineCount,
// 		LogLineCount:     &logLineCount,
// 		HistoryTail:      history,
// 		Config:           config,
// 		SummaryMetrics:   summary,
// 		Tags:             tags,
// 		WandbConfig:      wandbConfig,
// 	}
// }

// func TestUpdate(t *testing.T) {
// 	logger := observability.NewNoOpLogger()

// 	validHistory := `["{\"_step\":1,\"_runtime\":50}"]`
// 	validHistoryStep0 := `["{\"_step\":0}"]`
// 	validSummary := `{"loss": 0.5}`
// 	validConfig := `{"lr": {"value": 0.001}}`
// 	invalidHistoryOrConfig := `{"_step":0}`
// 	invalidHistory := `["invalid_history"]`
// 	invalidConfig := `{"_step": {"other": 2}}`
// 	nullString := "null"
// 	wandbConfigWithTelemetry := `{"_wandb": {"value": {"t":{"1": "asdasd"}}}}`

// 	testCases := []struct {
// 		name                string
// 		resumeMode          runbranching.Mode
// 		bucket              *gql.RunResumeStatusModelProjectBucketRun
// 		run                 *service.RunRecord
// 		expectResumed       bool
// 		expectStartingStep  int64
// 		expectRuntime       int32
// 		expectSummaryUpdate bool
// 		expectConfigUpdate  bool
// 		expectTagsUpdate    bool
// 		expectError         bool
// 	}{
// 		{
// 			name:          "MustResumeNonExistentRun",
// 			resumeMode:    runbranching.Must,
// 			bucket:        nil,
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "NeverResumeExistingRun",
// 			resumeMode:    runbranching.Never,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:               "MustResumeValidHistory",
// 			resumeMode:         runbranching.Must,
// 			bucket:             createBucketRawData(1, 0, 0, &validHistory, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:                &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:      true,
// 			expectStartingStep: 2,
// 			expectRuntime:      50,
// 			expectError:        false,
// 		},
// 		{
// 			name:               "MustResumeValidHistoryStep0",
// 			resumeMode:         runbranching.Must,
// 			bucket:             createBucketRawData(0, 0, 0, &nullString, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:                &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:      true,
// 			expectStartingStep: 0,
// 			expectError:        false,
// 		},
// 		{
// 			name:               "MustResumeValidHistoryStep0WithOneLine",
// 			resumeMode:         runbranching.Must,
// 			bucket:             createBucketRawData(1, 0, 0, &validHistoryStep0, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:                &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:      true,
// 			expectStartingStep: 1,
// 			expectError:        false,
// 		},
// 		{
// 			name:                "MustResumeValidSummary",
// 			resumeMode:          runbranching.Must,
// 			bucket:              createBucketRawData(0, 0, 0, &nullString, &nullString, &validSummary, nil, &wandbConfigWithTelemetry),
// 			run:                 &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:       true,
// 			expectSummaryUpdate: true,
// 			expectError:         false,
// 		},
// 		{
// 			name:               "MustResumeValidConfig",
// 			resumeMode:         runbranching.Must,
// 			bucket:             createBucketRawData(0, 0, 0, &nullString, &validConfig, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:                &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:      true,
// 			expectConfigUpdate: true,
// 			expectError:        false,
// 		},
// 		{
// 			name:             "MustResumeValidTags",
// 			resumeMode:       runbranching.Must,
// 			bucket:           createBucketRawData(0, 0, 0, &nullString, &nullString, &nullString, []string{"tag1", "tag2"}, &wandbConfigWithTelemetry),
// 			run:              &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed:    true,
// 			expectTagsUpdate: true,
// 			expectError:      false,
// 		},
// 		{
// 			name:          "MustResumeInvalidHistoryResponse",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &invalidHistoryOrConfig, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeInvalidHistoryContent",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &invalidHistory, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeInvalidSummaryMetrics",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &nullString, &invalidHistory, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeInvalidConfig",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &invalidHistory, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeInvalidConfigContent",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &invalidHistoryOrConfig, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: true,
// 			expectError:   false,
// 		},
// 		{
// 			name:          "MustResumeInvalidConfigNoContent",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &invalidConfig, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: true,
// 			expectError:   false,
// 		},
// 		{
// 			name:          "MustResumeNullHistory",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, nil, &nullString, &nullString, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeNullConfig",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &validHistory, nil, nil, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "MustResumeNullSummary",
// 			resumeMode:    runbranching.Must,
// 			bucket:        createBucketRawData(0, 0, 0, &validHistory, &validConfig, nil, nil, &wandbConfigWithTelemetry),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   true,
// 		},
// 		{
// 			name:          "AllowResumeNotStartedRun",
// 			resumeMode:    runbranching.Allow,
// 			bucket:        createBucketRawData(0, 0, 0, &nullString, &nullString, &nullString, nil, nil),
// 			run:           &service.RunRecord{Project: "test", RunId: "abc123"},
// 			expectResumed: false,
// 			expectError:   false,
// 		},
// 	}

// 	for _, tc := range testCases {
// 		t.Run(tc.name, func(t *testing.T) {
// 			rs := runbranching.NewResumeState(logger, tc.resumeMode)
// 			fakeResp := &gql.RunResumeStatusResponse{
// 				Model: &gql.RunResumeStatusModelProject{
// 					Bucket: tc.bucket,
// 				},
// 			}

// 			configCopy := runconfig.New()
// 			_, err := rs.Update(fakeResp, tc.run, configCopy)

// 			if tc.expectError {
// 				require.Error(t, err, "Expected error in Update")
// 			} else {
// 				require.NoError(t, err, "Unexpected error in Update")
// 				assert.Equal(t, tc.expectResumed, tc.run.Resumed, "Unexpected resumed state")

// 				if tc.expectStartingStep > 0 {
// 					assert.Equal(t, tc.expectStartingStep, tc.run.StartingStep, "Unexpected starting step")
// 				}

// 				if tc.expectRuntime > 0 {
// 					assert.Equal(t, tc.expectRuntime, tc.run.Runtime, "Unexpected runtime")
// 				}

// 				if tc.expectSummaryUpdate {
// 					require.Len(t, tc.run.Summary.Update, 1)
// 					assert.Equal(t, "loss", tc.run.Summary.Update[0].Key)
// 				}

// 				if tc.expectConfigUpdate {
// 					require.Len(t, configCopy.Tree(), 1)
// 					value, ok := configCopy.Tree()["lr"]
// 					require.True(t, ok, "Expected key 'lr' in config")
// 					assert.Equal(t, 0.001, value)
// 				}

// 				if tc.expectTagsUpdate {
// 					require.Len(t, tc.run.Tags, 2)
// 					assert.Contains(t, tc.run.Tags, "tag1")
// 					assert.Contains(t, tc.run.Tags, "tag2")
// 				}
// 			}
// 		})
// 	}
// }
