package sentry_test

import (
	"errors"
	"testing"
	"time"

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
				Dsn:    sentry.SentryDsn,
				Commit: "commit",
			},
		},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := sentry.New(tt.args.disabled, tt.args.commit); got.Dsn != tt.want.Dsn || got.Commit != tt.want.Commit {
				t.Errorf("New() = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestSentryClient_CaptureException(t *testing.T) {
	type fields struct {
		Dsn          string
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
				Dsn:          sentry.SentryDsn,
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
				Dsn:          sentry.SentryDsn,
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
				Dsn:          sentry.SentryDsn,
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
				Dsn:          tt.fields.Dsn,
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
		Dsn          string
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
				Dsn:          sentry.SentryDsn,
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
				Dsn:          tt.fields.Dsn,
				Commit:       tt.fields.Commit,
				RecentErrors: tt.fields.RecentErrors,
			}
			sc.CaptureMessage(tt.args.msg, tt.args.tags)
		})
	}
}
