package sentry_ext_test

import (
	"errors"
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

func TestSentryClient_CaptureException(t *testing.T) {
	type fields struct {
		DSN     string
		Commit  string
		LRUSize int
	}
	type args struct {
		errs []error
		tags map[string]string
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
				DSN:     "",
				Commit:  "commit",
				LRUSize: 2,
			},
			args: args{
				errs: []error{errors.New("error")},
				tags: map[string]string{},
			},
			numCaptures: 1,
		},

		{
			name: "TestCaptureExceptionDuplicate",
			fields: fields{
				DSN:     "",
				Commit:  "commit",
				LRUSize: 2,
			},
			args: args{
				errs: []error{errors.New("error"), errors.New("error")},
				tags: map[string]string{},
			},
			numCaptures: 1,
		},

		{
			name: "TestCaptureExceptionMultiple",
			fields: fields{
				DSN:     "",
				Commit:  "commit",
				LRUSize: 2,
			},
			args: args{
				errs: []error{errors.New("error1"), errors.New("error2")},
				tags: map[string]string{},
			},
			numCaptures: 2,
		},

		{
			name: "TestCaptureExceptionMultipleExceedsCache",
			fields: fields{
				DSN:     "",
				Commit:  "commit",
				LRUSize: 2,
			},
			args: args{
				errs: []error{errors.New("error1"), errors.New("error2"), errors.New("error3")},
				tags: map[string]string{},
			},
			numCaptures: 2,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			params := sentry_ext.Params{
				DSN:     tt.fields.DSN,
				Commit:  tt.fields.Commit,
				LRUSize: tt.fields.LRUSize,
			}
			sc := sentry_ext.New(params)

			for _, err := range tt.args.errs {
				sc.CaptureException(err, tt.args.tags)
			}

			if sc.Recent.Len() != tt.numCaptures {
				t.Errorf("CaptureException() = %v, want %v", sc.Recent.Len(), tt.numCaptures)
			}
		})
	}
}

func TestSentryClient_CaptureMessage(t *testing.T) {
	type fields struct {
		DSN     string
		Commit  string
		LRUSize int
	}
	type args struct {
		msg  string
		tags map[string]string
	}
	tests := []struct {
		name        string
		fields      fields
		args        args
		numCaptures int
	}{
		{
			name: "TestCaptureMessage",
			fields: fields{
				DSN:     "",
				Commit:  "commit",
				LRUSize: 2,
			},
			args: args{
				msg:  "message",
				tags: map[string]string{},
			},
			numCaptures: 1,
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			params := sentry_ext.Params{
				DSN:     tt.fields.DSN,
				Commit:  tt.fields.Commit,
				LRUSize: tt.fields.LRUSize,
			}
			sc := sentry_ext.New(params)

			sc.CaptureMessage(tt.args.msg, tt.args.tags)

			if sc.Recent.Len() != tt.numCaptures {
				t.Errorf("CaptureMessage() = %v, want %v", sc.Recent.Len(), tt.numCaptures)
			}
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
	assert.Equal(t, expectedFrames, actualFrames, "The bottom-most sentry.go and logging.go frames should be removed")
}
