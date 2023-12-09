package observability_test

import (
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/observability"
)

func TestNewTags(t *testing.T) {
	testCases := []struct {
		name   string
		input  []interface{}
		expect observability.Tags
	}{
		{
			name:   "Tags from slog.Attr",
			input:  []interface{}{slog.Attr{Key: "key1", Value: slog.Int64Value(123)}},
			expect: observability.Tags{"key1": "123"},
		},
		{
			name:   "Tags from string and slog.Any",
			input:  []interface{}{"key2", 456},
			expect: observability.Tags{"key2": "456"},
		},
		{
			name:   "Tags from a mix of slog.Attr, string, and slog.Any",
			input:  []interface{}{slog.Attr{Key: "key3", Value: slog.StringValue("value3")}, "key4", 789, slog.Any("key5", "value5")},
			expect: observability.Tags{"key3": "value3", "key4": "789", "key5": "value5"},
		},
		{
			name:   "Empty Tags",
			input:  []interface{}{},
			expect: observability.Tags{},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			tags := observability.NewTags(tc.input...)
			assert.Equal(t, tc.expect, tags, "Unexpected result for test case: %s", tc.name)
		})
	}
}
