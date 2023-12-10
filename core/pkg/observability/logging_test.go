package observability_test

import (
	"bytes"
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
			name:   "Tags from string and int",
			input:  []interface{}{"key2", 456},
			expect: observability.Tags{"key2": "456"},
		},
		{
			name:   "Tags from a mix of slog.Attr, string, and int",
			input:  []interface{}{slog.Attr{Key: "key3", Value: slog.StringValue("value3")}, "key4", 789, slog.Any("key5", "value5")},
			expect: observability.Tags{"key3": "value3", "key4": "789", "key5": "value5"},
		},
		{
			name:   "Tags from slog.Attr and string",
			input:  []interface{}{slog.Attr{Key: "key6", Value: slog.Int64Value(123)}, "key7"},
			expect: observability.Tags{"key6": "123"},
		},
		{
			name:   "Tags from empty input",
			input:  []interface{}{},
			expect: observability.Tags{},
		},
		{
			name:   "Tags from a mix of slog.Attr, map[string]string, string, and int",
			input:  []interface{}{slog.Attr{Key: "key8", Value: slog.Int64Value(123)}, map[string]string{"key9": "value9"}, "key10", 10},
			expect: observability.Tags{"key8": "123", "key10": "10"},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			tags := observability.NewTags(tc.input...)
			assert.Equal(t, tc.expect, tags, "Unexpected result for test case: %s", tc.name)
		})
	}
}

func TestNewNoOpLogger(t *testing.T) {
	// Call the function to get a CoreLogger
	logger := observability.NewNoOpLogger()

	// Assert that the logger has the expected configuration
	assert.NotNil(t, logger)
	assert.NotNil(t, logger.GetLogger())
	assert.NotNil(t, logger.GetTags())
	assert.NotNil(t, logger.GetCaptureException())
	assert.NotNil(t, logger.GetCaptureMessage())
}

func TestNewCoreLoggerWithTags(t *testing.T) {
	// Mock logger for testing
	var buf bytes.Buffer
	mockLogger := slog.New(
		slog.NewTextHandler(&buf,
			&slog.HandlerOptions{
				ReplaceAttr: func(groups []string, a slog.Attr) slog.Attr {
					if a.Key == slog.TimeKey && len(groups) == 0 {
						return slog.Attr{}
					}
					return a
				},
			},
		),
	)
	// Create tags for testing
	tags := observability.Tags{"key1": "value1", "key2": "value2"}

	// Create a CoreLogger with tags
	logger := observability.NewCoreLogger(mockLogger, observability.WithTags(tags))

	// Assert that the logger has the expected configuration
	assert.NotNil(t, logger)
	assert.NotNil(t, logger.Logger)

	// Assert that the logger has the expected tags
	assert.Equal(t, tags, logger.GetTags(), "Unexpected tags in the logger")

	// Assert that the slog logger has the expected tags
	logger.Info("Test message")
	assert.Equal(t, "level=INFO msg=\"Test message\" key1=value1 key2=value2\n", buf.String(), "Unexpected log message")
}
