package filestream

import (
	"sync"
	"testing"
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

func TestAcceptSummaryDelta_Feedback(t *testing.T) {
	tests := []struct {
		name     string
		feedback []map[string]any
		want     bool
	}{
		{"default false", nil, false},
		{"accepted", []map[string]any{{"accept_summary_delta": true}}, true},
		{
			"absent is false",
			[]map[string]any{{"accept_summary_delta": true}, {"stopped": false}},
			false,
		},
		{
			"undecodable response is ignored",
			[]map[string]any{{"accept_summary_delta": true}, nil},
			true,
		},
		{"non-bool is false", []map[string]any{{"accept_summary_delta": "yes"}}, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var fs fileStream
			ch := make(chan map[string]any, len(tc.feedback))
			var wg sync.WaitGroup
			fs.startProcessingFeedback(ch, &wg)

			for _, res := range tc.feedback {
				ch <- res
			}
			close(ch)
			wg.Wait()

			if got := fs.acceptSummaryDelta.Load(); got != tc.want {
				t.Fatalf("acceptSummaryDelta = %v, want %v", got, tc.want)
			}
		})
	}
}
