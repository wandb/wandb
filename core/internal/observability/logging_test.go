package observability_test

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	collogspb "go.opentelemetry.io/proto/otlp/collector/logs/v1"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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
}

func TestReraise(t *testing.T) {
	t.Run("no panic", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)

		defer func() {
			assert.Nil(t, recover())
			assert.Empty(t, logs)
		}()

		defer logger.Reraise("logging_test")
	})

	t.Run("panic with error", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)
		testErr := errors.New("test error")

		defer func() {
			assert.Equal(t, testErr, recover())
			assert.Contains(t, logs.String(), "test error")
		}()

		defer logger.Reraise("logging_test")
		panic(testErr)
	})

	t.Run("panic with string", func(t *testing.T) {
		logger, logs := observabilitytest.NewRecordingTestLogger(t)

		defer func() {
			assert.Equal(t, fmt.Errorf("test error string"), recover())
			assert.Contains(t, logs.String(), "test error string")
		}()

		defer logger.Reraise("logging_test")
		panic("test error string")
	})
}

func TestCaptureFatalAndPanic_Nil(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)

	defer func() {
		assert.ErrorContains(t, recover().(error), "panicked with nil error")
	}()

	logger.CaptureFatalAndPanic("logging_test", nil)
}

func TestLoggerHierarchy(t *testing.T) {
	baseLogger, logs, sentry := observabilitytest.NewSentryTestLogger(t)

	childLogger := baseLogger.With(
		[]any{"attr", "attr-value"},
		map[string]string{"child-tag": "child-value"},
	)

	baseLogger.CaptureInfo("base message")
	childLogger.CaptureInfo("child message")

	sentryEvents := sentry.Events()
	require.Len(t, sentryEvents, 2)
	assert.Empty(t, sentryEvents[0].Tags)
	assert.Equal(t, map[string]string{
		// Sentry tags include attrs and tags passed to With().
		"attr":      "attr-value",
		"child-tag": "child-value",
	}, sentryEvents[1].Tags)

	logRecords := observabilitytest.ExtractLogs(t, logs)
	require.Len(t, logRecords, 2)
	assert.Equal(t, map[string]string{
		"level": "INFO",
		"msg":   "base message",
	}, logRecords[0])
	assert.Equal(t, map[string]string{
		"level": "INFO",
		"msg":   "child message",
		// slog only includes the attrs passed to With().
		"attr": "attr-value",
	}, logRecords[1])
}

func captureTelemetryLog(
	t *testing.T,
	record func(*observability.CoreLogger),
) map[string]string {
	t.Helper()

	type exportResult struct {
		request *collogspb.ExportLogsServiceRequest
		err     error
	}
	exported := make(chan exportResult, 1)
	server := httptest.NewServer(http.HandlerFunc(
		func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != "/sdk/otel/v1/logs" {
				w.WriteHeader(http.StatusOK)
				return
			}

			body, err := io.ReadAll(r.Body)
			if err != nil {
				exported <- exportResult{err: err}
				w.WriteHeader(http.StatusInternalServerError)
				return
			}

			request := &collogspb.ExportLogsServiceRequest{}
			err = proto.Unmarshal(body, request)
			exported <- exportResult{request: request, err: err}
			w.WriteHeader(http.StatusOK)
		},
	))
	t.Cleanup(server.Close)

	settings := wbsettings.From(&spb.Settings{
		BaseUrl: wrapperspb.String(server.URL),
		ApiKey:  wrapperspb.String("test-api-key"),
	})
	proxy := analytics.NewOpenTelemetryProxy(t.Context(), settings)
	require.NotNil(t, proxy)
	recorder := analytics.NewTelemetryRecorder(
		proxy,
		analytics.NewTelemetryContext(),
	)
	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(io.Discard, nil)),
		nil,
		recorder,
	)

	record(logger)
	require.NoError(t, proxy.Shutdown(context.Background()))

	result := <-exported
	require.NoError(t, result.err)
	resourceLogs := result.request.GetResourceLogs()
	require.Len(t, resourceLogs, 1)
	scopeLogs := resourceLogs[0].GetScopeLogs()
	require.Len(t, scopeLogs, 1)
	records := scopeLogs[0].GetLogRecords()
	require.Len(t, records, 1)

	attributes := make(map[string]string)
	for _, attribute := range records[0].GetAttributes() {
		attributes[attribute.GetKey()] = attribute.GetValue().GetStringValue()
	}
	return attributes
}

func TestCaptureInfo_IncludesDerivedTelemetryTags(t *testing.T) {
	attributes := captureTelemetryLog(t, func(logger *observability.CoreLogger) {
		logger.With(
			[]any{"logger-attr", "attr-value"},
			map[string]string{"logger-tag": "tag-value"},
		).CaptureInfo(
			"test message",
			slog.String("call-attr", "call-value"),
			slog.Int("call-int", 123),
		)
	})

	assert.Equal(t, "attr-value", attributes["logger-attr"])
	assert.Equal(t, "tag-value", attributes["logger-tag"])
	assert.Equal(t, "call-value", attributes["call-attr"])
	assert.Equal(t, "123", attributes["call-int"])
}

func TestCaptureError_AttributesCaller(t *testing.T) {
	attributes := captureTelemetryLog(t, func(logger *observability.CoreLogger) {
		logger.CaptureError("logging_test", assert.AnError)
	})

	assert.Equal(t, "logging_test", attributes["error.originator"])
}

func TestCaptureFatal_AttributesCaller(t *testing.T) {
	attributes := captureTelemetryLog(t, func(logger *observability.CoreLogger) {
		logger.CaptureFatal("logging_test", assert.AnError)
	})

	assert.Equal(t, "logging_test", attributes["error.originator"])
}
