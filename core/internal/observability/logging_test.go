package observability_test

import (
	"errors"
	"fmt"
	"log/slog"
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
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
			name: "Tags from a mix of slog.Attr, string, and int",
			input: []interface{}{
				slog.Attr{Key: "key3", Value: slog.StringValue("value3")},
				"key4",
				789,
				slog.Any("key5", "value5"),
			},
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
			name: "Tags from a mix of slog.Attr, map[string]string, string, and int",
			input: []interface{}{
				slog.Attr{Key: "key8", Value: slog.Int64Value(123)},
				map[string]string{"key9": "value9"},
				"key10",
				10,
			},
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
	// Set up the logger
	logger := observability.NewNoOpLogger()

	// Assert that the logger has the expected configuration
	assert.NotNil(t, logger, "Expected logger to be created")
	assert.NotNil(t, logger.Logger, "Expected logger to be created")
	assert.Equal(t, observability.Tags{}, logger.GetTags(), "Unexpected tags in the logger")
}

func TestReraise(t *testing.T) {
	t.Run("no panic", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)

		defer func() {
			assert.Nil(t, recover())
			assert.Empty(t, logs)
		}()

		defer logger.Reraise()
	})

	t.Run("panic with error", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)
		testErr := errors.New("test error")

		defer func() {
			assert.Equal(t, testErr, recover())
			assert.Contains(t, logs.String(), "test error")
		}()

		defer logger.Reraise()
		panic(testErr)
	})

	t.Run("panic with string", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)

		defer func() {
			assert.Equal(t, fmt.Errorf("test error string"), recover())
			assert.Contains(t, logs.String(), "test error string")
		}()

		defer logger.Reraise()
		panic("test error string")
	})
}

func TestCaptureFatalAndPanic_Nil(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)

	defer func() {
		assert.ErrorContains(t, recover().(error), "panicked with nil error")
	}()

	logger.CaptureFatalAndPanic(nil)
}
