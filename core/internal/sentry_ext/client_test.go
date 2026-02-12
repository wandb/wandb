package sentry_ext_test

import (
	"testing"

	"github.com/getsentry/sentry-go"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/sentry_ext"
)

func TestNew(t *testing.T) {
	type args struct {
		params sentry_ext.Params
	}
	tests := []struct {
		name string
		args args
	}{
		{
			name: "TestNew",
			args: args{
				params: sentry_ext.Params{
					DSN:    "",
					Commit: "commit",
				},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := sentry_ext.New(tt.args.params)
			assert.NotNil(t, sc, "New() should return a non-nil sentry client")
		})
	}
}

func TestRemoveBottomFrames(t *testing.T) {
	// Mock event with stack trace containing frames to be removed
	event := &sentry.Event{
		Exception: []sentry.Exception{
			{
				Stacktrace: &sentry.Stacktrace{
					Frames: []sentry.Frame{
						{AbsPath: "/path/to/file1.go"},
						{AbsPath: "/path/to/file2.go"},
						{AbsPath: "/path/to/client.go"},
						{AbsPath: "/path/to/logging.go"},
					},
				},
			},
		},
	}

	// Mock hint (not used in our function, so it can be nil)
	hint := (*sentry.EventHint)(nil)

	// Call the function under test
	modifiedEvent := sentry_ext.RemoveBottomFrames(event, hint)

	// Validate the result: The last two frames should be preserved,
	// as well as the first non-matching frame before the last two.
	expectedFrames := []sentry.Frame{
		{AbsPath: "/path/to/file1.go"},
		{AbsPath: "/path/to/file2.go"},
	}

	actualFrames := modifiedEvent.Exception[0].Stacktrace.Frames
	assert.Equal(
		t,
		expectedFrames,
		actualFrames,
		"The bottom-most sentry.go and logging.go frames should be removed",
	)
}
