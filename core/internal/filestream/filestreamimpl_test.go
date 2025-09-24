package filestream

import (
	"sync"
	"testing"
)

func TestStopState_FeedbackTable(t *testing.T) {
	tests := []struct {
		name     string
		feedback []any
		want     StopState
	}{
		{"default unknown", nil, StopUnknown},
		{"false only -> false", []any{false}, StopFalse},
		{"true only -> true", []any{true}, StopTrue},
		{"false then true -> true", []any{false, true}, StopTrue},
		{"true then false -> true", []any{true, false}, StopTrue},
		{"non-bool ignored -> unknown", []any{"nope", 1}, StopUnknown},
		{"non-bool then false -> false", []any{"nope", false}, StopFalse},
		{"non-bool then true -> true", []any{0, true}, StopTrue},
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

			if got := fs.StopState(); got != tc.want {
				t.Fatalf("StopState = %v, want %v", got, tc.want)
			}
		})
	}
}
