package settings_test

import (
	"bytes"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestFileStreamHistoryEncoding(t *testing.T) {
	for _, tt := range []struct {
		name  string
		value *wrapperspb.StringValue
		want  string
		warn  bool
	}{
		{name: "unset", want: "jsonl"},
		{name: "jsonl", value: wrapperspb.String("jsonl"), want: "jsonl"},
		{name: "proto", value: wrapperspb.String(" Proto+V1 "), want: "proto+v1"},
		{name: "invalid", value: wrapperspb.String("cbor"), want: "jsonl", warn: true},
		{name: "empty", value: wrapperspb.String(""), want: "jsonl", warn: true},
	} {
		t.Run(tt.name, func(t *testing.T) {
			var logs bytes.Buffer
			logger := slog.New(slog.NewTextHandler(&logs, nil))
			s := settings.From(&spb.Settings{XFileStreamHistoryEncoding: tt.value})

			assert.Equal(t, tt.want, s.FileStreamHistoryEncoding(logger))
			if tt.warn {
				assert.Contains(t, logs.String(), "Ignoring unsupported x_file_stream_history_encoding")
			} else {
				assert.Empty(t, logs.String())
			}
		})
	}
}
