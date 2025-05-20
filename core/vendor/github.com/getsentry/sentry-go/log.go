package sentry

import (
	"context"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/getsentry/sentry-go/attribute"
)

type LogLevel string

const (
	LogLevelTrace Level = "trace"
	LogLevelDebug Level = "debug"
	LogLevelInfo  Level = "info"
	LogLevelWarn  Level = "warn"
	LogLevelError Level = "error"
	LogLevelFatal Level = "fatal"
)

const (
	LogSeverityTrace   int = 1
	LogSeverityDebug   int = 5
	LogSeverityInfo    int = 9
	LogSeverityWarning int = 13
	LogSeverityError   int = 17
	LogSeverityFatal   int = 21
)

var mapTypesToStr = map[attribute.Type]string{
	attribute.INVALID: "",
	attribute.BOOL:    "boolean",
	attribute.INT64:   "integer",
	attribute.FLOAT64: "double",
	attribute.STRING:  "string",
}

type sentryLogger struct {
	client     *Client
	attributes map[string]Attribute
}

// NewLogger returns a Logger that emits logs to Sentry. If logging is turned off, all logs get discarded.
func NewLogger(ctx context.Context) Logger {
	var hub *Hub
	hub = GetHubFromContext(ctx)
	if hub == nil {
		hub = CurrentHub()
	}

	client := hub.Client()
	if client != nil && client.batchLogger != nil {
		return &sentryLogger{client, make(map[string]Attribute)}
	}

	DebugLogger.Println("fallback to noopLogger: enableLogs disabled")
	return &noopLogger{} // fallback: does nothing
}

func (l *sentryLogger) Write(p []byte) (int, error) {
	// Avoid sending double newlines to Sentry
	msg := strings.TrimRight(string(p), "\n")
	l.log(context.Background(), LevelInfo, LogSeverityInfo, msg)
	return len(p), nil
}

func (l *sentryLogger) log(ctx context.Context, level Level, severity int, message string, args ...interface{}) {
	if message == "" {
		return
	}
	hub := GetHubFromContext(ctx)
	if hub == nil {
		hub = CurrentHub()
	}

	var traceID TraceID
	var spanID SpanID

	span := hub.Scope().span
	if span != nil {
		traceID = span.TraceID
		spanID = span.SpanID
	} else {
		traceID = hub.Scope().propagationContext.TraceID
	}

	attrs := map[string]Attribute{}
	if len(args) > 0 {
		attrs["sentry.message.template"] = Attribute{
			Value: message, Type: "string",
		}
		for i, p := range args {
			attrs[fmt.Sprintf("sentry.message.parameters.%d", i)] = Attribute{
				Value: fmt.Sprint(p), Type: "string",
			}
		}
	}

	// If `log` was called with SetAttributes, pass the attributes to attrs
	if len(l.attributes) > 0 {
		for k, v := range l.attributes {
			attrs[k] = v
		}
		// flush attributes from logger after send
		clear(l.attributes)
	}

	// Set default attributes
	if release := l.client.options.Release; release != "" {
		attrs["sentry.release"] = Attribute{Value: release, Type: "string"}
	}
	if environment := l.client.options.Environment; environment != "" {
		attrs["sentry.environment"] = Attribute{Value: environment, Type: "string"}
	}
	if serverName := l.client.options.ServerName; serverName != "" {
		attrs["sentry.server.address"] = Attribute{Value: serverName, Type: "string"}
	} else if serverAddr, err := os.Hostname(); err == nil {
		attrs["sentry.server.address"] = Attribute{Value: serverAddr, Type: "string"}
	}
	if spanID.String() != "0000000000000000" {
		attrs["sentry.trace.parent_span_id"] = Attribute{Value: spanID.String(), Type: "string"}
	}
	if sdkIdentifier := l.client.sdkIdentifier; sdkIdentifier != "" {
		attrs["sentry.sdk.name"] = Attribute{Value: sdkIdentifier, Type: "string"}
	}
	if sdkVersion := l.client.sdkVersion; sdkVersion != "" {
		attrs["sentry.sdk.version"] = Attribute{Value: sdkVersion, Type: "string"}
	}
	attrs["sentry.origin"] = Attribute{Value: "auto.logger.log", Type: "string"}

	log := &Log{
		Timestamp:  time.Now(),
		TraceID:    traceID,
		Level:      level,
		Severity:   severity,
		Body:       fmt.Sprintf(message, args...),
		Attributes: attrs,
	}

	if l.client.options.BeforeSendLog != nil {
		log = l.client.options.BeforeSendLog(log)
	}

	if log != nil {
		l.client.batchLogger.logCh <- *log
	}

	if l.client.options.Debug {
		DebugLogger.Printf(message, args...)
	}
}

func (l *sentryLogger) SetAttributes(attrs ...attribute.Builder) {
	for _, v := range attrs {
		t, ok := mapTypesToStr[v.Value.Type()]
		if !ok || t == "" {
			DebugLogger.Printf("invalid attribute type set: %v", t)
			continue
		}

		l.attributes[v.Key] = Attribute{
			Value: v.Value.AsInterface(),
			Type:  t,
		}
	}
}

func (l *sentryLogger) Trace(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelTrace, LogSeverityTrace, fmt.Sprint(v...))
}
func (l *sentryLogger) Debug(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelDebug, LogSeverityDebug, fmt.Sprint(v...))
}
func (l *sentryLogger) Info(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelInfo, LogSeverityInfo, fmt.Sprint(v...))
}
func (l *sentryLogger) Warn(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelWarn, LogSeverityWarning, fmt.Sprint(v...))
}
func (l *sentryLogger) Error(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelError, LogSeverityError, fmt.Sprint(v...))
}
func (l *sentryLogger) Fatal(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelFatal, LogSeverityFatal, fmt.Sprint(v...))
	os.Exit(1)
}
func (l *sentryLogger) Panic(ctx context.Context, v ...interface{}) {
	l.log(ctx, LogLevelFatal, LogSeverityFatal, fmt.Sprint(v...))
	panic(fmt.Sprint(v...))
}
func (l *sentryLogger) Tracef(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelTrace, LogSeverityTrace, format, v...)
}
func (l *sentryLogger) Debugf(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelDebug, LogSeverityDebug, format, v...)
}
func (l *sentryLogger) Infof(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelInfo, LogSeverityInfo, format, v...)
}
func (l *sentryLogger) Warnf(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelWarn, LogSeverityWarning, format, v...)
}
func (l *sentryLogger) Errorf(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelError, LogSeverityError, format, v...)
}
func (l *sentryLogger) Fatalf(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelFatal, LogSeverityFatal, format, v...)
	os.Exit(1)
}
func (l *sentryLogger) Panicf(ctx context.Context, format string, v ...interface{}) {
	l.log(ctx, LogLevelFatal, LogSeverityFatal, format, v...)
	panic(fmt.Sprint(v...))
}
