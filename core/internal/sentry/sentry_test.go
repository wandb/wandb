package sentry_test

import (
	"errors"
	"testing"
	"time"

	sentrygo "github.com/getsentry/sentry-go"
	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/sentry"
	"github.com/wandb/wandb/core/pkg/observability"
)

func TestNew(t *testing.T) {
	type args struct {
		disabled bool
		commit   string
	}
	tests := []struct {
		name string
		args args
		want *sentry.SentryClient
	}{
		{
			name: "TestNew",
			args: args{
				disabled: false,
				commit:   "commit",
			},
			want: &sentry.SentryClient{
				DSN:    sentry.SentryDSN,
				Commit: "commit",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := sentry.New(tt.args.disabled, tt.args.commit); got.DSN != tt.want.DSN || got.Commit != tt.want.Commit {
				t.Errorf("New() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestSentryClient_CaptureException(t *testing.T) {
	type fields struct {
		DSN          string
		Commit       string
		RecentErrors map[string]time.Time
	}
	type args struct {
		errs []error
		tags observability.Tags
	}
	tests := []struct {
		name        string
		fields      fields
		args        args
		numCaptures int
	}{
		{
			name: "TestCaptureException",
			fields: fields{
				DSN:          "some-dsn",
				Commit:       "commit",
				RecentErrors: map[string]time.Time{},
			},
			args: args{
				errs: []error{errors.New("error")},
				tags: observability.Tags{},
			},
			numCaptures: 1,
		},

		{
			name: "TestCaptureExceptionDuplicate",
			fields: fields{
				DSN:          "some-dsn",
				Commit:       "commit",
				RecentErrors: map[string]time.Time{},
			},
			args: args{
				errs: []error{errors.New("error"), errors.New("error")},
				tags: observability.Tags{},
			},
			numCaptures: 1,
		},

		{
			name: "TestCaptureExceptionMultiple",
			fields: fields{
				DSN:          "some-dsn",
				Commit:       "commit",
				RecentErrors: map[string]time.Time{},
			},
			args: args{
				errs: []error{errors.New("error1"), errors.New("error2")},
				tags: observability.Tags{},
			},
			numCaptures: 2,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := &sentry.SentryClient{
				DSN:          tt.fields.DSN,
				Commit:       tt.fields.Commit,
				RecentErrors: tt.fields.RecentErrors,
			}

			for _, err := range tt.args.errs {
				sc.CaptureException(err, tt.args.tags)
			}

			if len(sc.RecentErrors) != tt.numCaptures {
				t.Errorf("CaptureException() = %v, want %v", len(sc.RecentErrors), tt.numCaptures)
			}
		})
	}
}

func TestSentryClient_CaptureMessage(t *testing.T) {
	type fields struct {
		DSN          string
		Commit       string
		RecentErrors map[string]time.Time
	}
	type args struct {
		msg  string
		tags observability.Tags
	}
	tests := []struct {
		name   string
		fields fields
		args   args
	}{
		{
			name: "TestCaptureMessage",
			fields: fields{
				DSN:          sentry.SentryDSN,
				Commit:       "commit",
				RecentErrors: map[string]time.Time{},
			},
			args: args{
				msg:  "message",
				tags: observability.Tags{},
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			sc := &sentry.SentryClient{
				DSN:          tt.fields.DSN,
				Commit:       tt.fields.Commit,
				RecentErrors: tt.fields.RecentErrors,
			}
			sc.CaptureMessage(tt.args.msg, tt.args.tags)
		})
	}
}

func TestRemoveBottomFrames(t *testing.T) {
	// Mock event with stack trace containing frames to be removed
	event := &sentrygo.Event{
		Exception: []sentrygo.Exception{
			{
				Stacktrace: &sentrygo.Stacktrace{
					Frames: []sentrygo.Frame{
						{AbsPath: "/path/to/file1.go"},
						{AbsPath: "/path/to/file2.go"},
						{AbsPath: "/path/to/sentry.go"},
						{AbsPath: "/path/to/logging.go"},
					},
				},
			},
		},
	}

	// Mock hint (not used in our function, so it can be nil)
	hint := (*sentrygo.EventHint)(nil)

	// Call the function under test
	modifiedEvent := sentry.RemoveBottomFrames(event, hint)

	// Validate the result: The last two frames should be preserved,
	// as well as the first non-matching frame before the last two.
	expectedFrames := []sentrygo.Frame{
		{AbsPath: "/path/to/file1.go"},
		{AbsPath: "/path/to/file2.go"},
	}

	actualFrames := modifiedEvent.Exception[0].Stacktrace.Frames
	assert.Equal(t, expectedFrames, actualFrames, "The bottom-most sentry.go and logging.go frames should be removed")
}
