package sentry_ext_test

import (
	"testing"

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
