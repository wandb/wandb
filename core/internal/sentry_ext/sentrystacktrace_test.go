package sentry_ext_test

import (
	"reflect"
	"testing"

	"github.com/getsentry/sentry-go"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/sentry_ext"
)

// makeStacktrace creates a stacktrace with the given sequence of modules
// as its frames.
func makeStacktrace(modules ...string) *sentry.Stacktrace {
	stacktrace := &sentry.Stacktrace{}

	for _, module := range modules {
		stacktrace.Frames = append(stacktrace.Frames,
			sentry.Frame{Module: module})
	}

	return stacktrace
}

func TestRemoveLoggerFrames(t *testing.T) {
	tests := []struct {
		name     string
		input    *sentry.Stacktrace
		expected *sentry.Stacktrace
	}{
		{"skips nil stacktrace", nil, nil},

		{
			name: "removes trailing logger frames",
			input: makeStacktrace(
				"github.com/wandb/wandb/core/internal/sentry_ext",
				"github.com/wandb/wandb/core/pkg/server",
				"github.com/wandb/wandb/core/internal/observability",
				"github.com/wandb/wandb/core/pkg/server",
				"github.com/wandb/wandb/core/pkg/server",
				"github.com/wandb/wandb/core/internal/observability",
				reflect.TypeFor[observability.CoreLogger]().PkgPath(),
				"github.com/wandb/wandb/core/internal/sentry_ext",
			),
			expected: makeStacktrace(
				"github.com/wandb/wandb/core/internal/sentry_ext",
				"github.com/wandb/wandb/core/pkg/server",
				"github.com/wandb/wandb/core/internal/observability",
				"github.com/wandb/wandb/core/pkg/server",
				"github.com/wandb/wandb/core/pkg/server",
			),
		},
	}

	// Apply RemoveLoggerFrames to all stack traces in one go
	// to test that it loops over an event's exceptions.
	event := &sentry.Event{}
	for _, tt := range tests {
		event.Exception = append(event.Exception,
			sentry.Exception{Stacktrace: tt.input})
	}
	result := sentry_ext.RemoveLoggerFrames(event, nil)

	for i, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			assert.Equal(t,
				tt.expected,
				result.Exception[i].Stacktrace,
			)
		})
	}
}
