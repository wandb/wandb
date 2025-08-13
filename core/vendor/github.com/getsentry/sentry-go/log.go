package sentry

import (
	"context"
	"fmt"
	"maps"
	"os"
	"strings"
	"time"

	"github.com/getsentry/sentry-go/attribute"
)

type LogLevel string

const (
	LogLevelTrace LogLevel = "trace"
	LogLevelDebug LogLevel = "debug"
	LogLevelInfo  LogLevel = "info"
	LogLevelWarn  LogLevel = "warn"
	LogLevelError LogLevel = "error"
	LogLevelFatal LogLevel = "fatal"
)

const (
	LogSeverityTrace   int = 1
	LogSeverityDebug   int = 5
	LogSeverityInfo    int = 9
	LogSeverityWarning int = 13
	LogSeverityError   int = 17
	LogSeverityFatal   int = 21
)

var mapTypesToStr = map[attribute.Type]AttrType{
	attribute.INVALID: AttributeInvalid,
	attribute.BOOL:    AttributeBool,
	attribute.INT64:   AttributeInt,
	attribute.FLOAT64: AttributeFloat,
	attribute.STRING:  AttributeString,
}

type sentryLogger struct {
	ctx        context.Context
	client     *Client
	attributes map[string]Attribute
}

type logEntry struct {
	logger      *sentryLogger
	ctx         context.Context
	level       LogLevel
	severity    int
	attributes  map[string]Attribute
	shouldPanic bool
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
		return &sentryLogger{ctx, client, make(map[string]Attribute)}
	}

	DebugLogger.Println("fallback to noopLogger: enableLogs disabled")
	return &noopLogger{} // fallback: does nothing
}

func (l *sentryLogger) Write(p []byte) (int, error) {
	// Avoid sending double newlines to Sentry
	msg := strings.TrimRight(string(p), "\n")
	l.Info().Emit(msg)
	return len(p), nil
}

func (l *sentryLogger) log(ctx context.Context, level LogLevel, severity int, message string, entryAttrs map[string]Attribute, args ...interface{}) {
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
			Value: message, Type: AttributeString,
		}
		for i, p := range args {
			attrs[fmt.Sprintf("sentry.message.parameters.%d", i)] = Attribute{
				Value: fmt.Sprintf("%+v", p), Type: AttributeString,
			}
		}
	}

	for k, v := range l.attributes {
		attrs[k] = v
	}
	for k, v := range entryAttrs {
		attrs[k] = v
	}

	// Set default attributes
	if release := l.client.options.Release; release != "" {
		attrs["sentry.release"] = Attribute{Value: release, Type: AttributeString}
	}
	if environment := l.client.options.Environment; environment != "" {
		attrs["sentry.environment"] = Attribute{Value: environment, Type: AttributeString}
	}
	if serverName := l.client.options.ServerName; serverName != "" {
		attrs["sentry.server.address"] = Attribute{Value: serverName, Type: AttributeString}
	} else if serverAddr, err := os.Hostname(); err == nil {
		attrs["sentry.server.address"] = Attribute{Value: serverAddr, Type: AttributeString}
	}
	scope := hub.Scope()
	if scope != nil {
		user := scope.user
		if !user.IsEmpty() {
			if user.ID != "" {
				attrs["user.id"] = Attribute{Value: user.ID, Type: AttributeString}
			}
			if user.Name != "" {
				attrs["user.name"] = Attribute{Value: user.Name, Type: AttributeString}
			}
			if user.Email != "" {
				attrs["user.email"] = Attribute{Value: user.Email, Type: AttributeString}
			}
		}
	}
	if span != nil {
		attrs["sentry.trace.parent_span_id"] = Attribute{Value: spanID.String(), Type: AttributeString}
	}
	if sdkIdentifier := l.client.sdkIdentifier; sdkIdentifier != "" {
		attrs["sentry.sdk.name"] = Attribute{Value: sdkIdentifier, Type: AttributeString}
	}
	if sdkVersion := l.client.sdkVersion; sdkVersion != "" {
		attrs["sentry.sdk.version"] = Attribute{Value: sdkVersion, Type: AttributeString}
	}

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

func (l *sentryLogger) Trace() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelTrace,
		severity:   LogSeverityTrace,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Debug() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelDebug,
		severity:   LogSeverityDebug,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Info() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelInfo,
		severity:   LogSeverityInfo,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Warn() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelWarn,
		severity:   LogSeverityWarning,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Error() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelError,
		severity:   LogSeverityError,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Fatal() LogEntry {
	return &logEntry{
		logger:     l,
		ctx:        l.ctx,
		level:      LogLevelFatal,
		severity:   LogSeverityFatal,
		attributes: make(map[string]Attribute),
	}
}

func (l *sentryLogger) Panic() LogEntry {
	return &logEntry{
		logger:      l,
		ctx:         l.ctx,
		level:       LogLevelFatal,
		severity:    LogSeverityFatal,
		attributes:  make(map[string]Attribute),
		shouldPanic: true, // this should panic instead of exit
	}
}

func (l *sentryLogger) GetCtx() context.Context {
	return l.ctx
}

func (e *logEntry) WithCtx(ctx context.Context) LogEntry {
	return &logEntry{
		logger:      e.logger,
		ctx:         ctx,
		level:       e.level,
		severity:    e.severity,
		attributes:  maps.Clone(e.attributes),
		shouldPanic: e.shouldPanic,
	}
}

func (e *logEntry) String(key, value string) LogEntry {
	e.attributes[key] = Attribute{Value: value, Type: AttributeString}
	return e
}

func (e *logEntry) Int(key string, value int) LogEntry {
	e.attributes[key] = Attribute{Value: int64(value), Type: AttributeInt}
	return e
}

func (e *logEntry) Int64(key string, value int64) LogEntry {
	e.attributes[key] = Attribute{Value: value, Type: AttributeInt}
	return e
}

func (e *logEntry) Float64(key string, value float64) LogEntry {
	e.attributes[key] = Attribute{Value: value, Type: AttributeFloat}
	return e
}

func (e *logEntry) Bool(key string, value bool) LogEntry {
	e.attributes[key] = Attribute{Value: value, Type: AttributeBool}
	return e
}

func (e *logEntry) Emit(args ...interface{}) {
	e.logger.log(e.ctx, e.level, e.severity, fmt.Sprint(args...), e.attributes)

	if e.level == LogLevelFatal {
		if e.shouldPanic {
			panic(fmt.Sprint(args...))
		}
		os.Exit(1)
	}
}

func (e *logEntry) Emitf(format string, args ...interface{}) {
	e.logger.log(e.ctx, e.level, e.severity, format, e.attributes, args...)

	if e.level == LogLevelFatal {
		if e.shouldPanic {
			formattedMessage := fmt.Sprintf(format, args...)
			panic(formattedMessage)
		}
		os.Exit(1)
	}
}
