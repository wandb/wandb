package filestream

import (
	"context"
	"encoding/json"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"testing"

	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/wboperation"
)

func TestStopState_FeedbackTable(t *testing.T) {
	tests := []struct {
		name     string
		feedback []any
		want     bool
	}{
		{"default false", nil, false},
		{"false only -> false", []any{false}, false},
		{"true only -> true", []any{true}, true},
		{"false, non-bool, true -> true", []any{false, true}, true},
		{"true, non-bool, false -> true", []any{true, false}, true},
		{"non-bool ignored", []any{"nope", 1}, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var fs fileStream
			ch := make(chan map[string]any, len(tc.feedback))
			var wg sync.WaitGroup
			fs.startProcessingFeedback(ch, &wg)

			for _, v := range tc.feedback {
				ch <- map[string]any{"stopped": v}
			}
			close(ch)
			wg.Wait()

			if got := fs.IsStopped(); got != tc.want {
				t.Fatalf("StopState = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestSend_LogsMatchingRequestID(t *testing.T) {
	logger, recordedLogs := observabilitytest.NewRecordingTestLogger(t)
	client := apitest.NewFakeClient("https://api.wandb.ai")
	client.SetResponse(&apitest.TestResponse{
		StatusCode: http.StatusOK,
		Body:       `{}`,
	}, nil)
	fs := fileStream{
		beforeRunEndCtx: context.Background(),
		settings:        settings.New(),
		featureProvider: featurechecker.NewPreloaded(nil),
		logger:          logger,
		operations:      wboperation.NewOperations(),
		apiClient:       client,
		baseURL: &url.URL{
			Scheme: "https",
			Host:   "api.wandb.ai",
		},
		path: "files/entity/project/run/file_stream",
	}

	feedback := make(chan map[string]any, 1)
	err := fs.send(&FileStreamRequestJSON{
		Files: map[string]OffsetAndContent{
			HistoryFileName: {
				Offset:  7,
				Content: []string{`{"_step":7}`},
			},
		},
	}, feedback)

	require.NoError(t, err)
	require.Equal(t, map[string]any{}, <-feedback)

	var logs []map[string]any
	for _, line := range strings.Split(strings.TrimSpace(recordedLogs.String()), "\n") {
		var log map[string]any
		require.NoError(t, json.Unmarshal([]byte(line), &log))
		logs = append(logs, log)
	}

	require.Len(t, logs, 2)
	require.Equal(t, "filestream: sending request", logs[0]["msg"])
	require.Equal(t, "filestream: request sent", logs[1]["msg"])

	requestID, ok := logs[0]["request_id"].(string)
	require.True(t, ok)
	require.NotEmpty(t, requestID)
	for _, log := range logs[1:] {
		require.Equal(t, requestID, log["request_id"])
	}
}
