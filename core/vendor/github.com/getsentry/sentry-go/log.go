package sentry

import (
	"context"
	"fmt"
	"maps"
	"os"
	"strings"
	"sync"
	"time"

	"github.com/getsentry/sentry-go/attribute"
	"github.com/getsentry/sentry-go/internal/debuglog"
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
	ctx               context.Context
	client            *Client
	attributes        map[string]Attribute
	defaultAttributes map[string]Attribute
	mu                sync.RWMutex
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
func NewLogger(ctx context.Context) Logger { // nolint: dupl
	var hub *Hub
	hub = GetHubFromContext(ctx)
	if hub == nil {
		hub = CurrentHub()
	}

	client := hub.Client()
	if client != nil && client.options.EnableLogs {
		// Build default attrs
		serverAddr := client.options.ServerName
		if serverAddr == "" {
			serverAddr, _ = os.Hostname()
		}

		defaults := map[string]string{
			"sentry.release":        client.options.Release,
			"sentry.environment":    client.options.Environment,
			"sentry.server.address": serverAddr,
			"sentry.sdk.name":       client.sdkIdentifier,
			"sentry.sdk.version":    client.sdkVersion,
		}

		defaultAttrs := make(map[string]Attribute)
		for k, v := range defaults {
			if v != "" {
				defaultAttrs[k] = Attribute{Value: v, Type: AttributeString}
			}
		}

		return &sentryLogger{
			ctx:               ctx,
			client:            client,
			attributes:        make(map[string]Attribute),
			defaultAttributes: defaultAttrs,
			mu:                sync.RWMutex{},
		}
	}

	debuglog.Println("fallback to noopLogger: enableLogs disabled")
	return &noopLogger{}
}

func (l *sentryLogger) Write(p []byte) (int, error) {
	msg := strings.TrimRight(string(p), "\n")
	l.Info().Emit(msg)
	return len(p), nil
}

func (l *sentryLogger) log(ctx context.Context, level LogLevel, severity int, message string, entryAttrs map[string]Attribute, args ...interface{}) {
	if message == "" {
		return
	}

	scope, traceID, spanID := resolveScopeAndTrace(ctx, l.ctx)

	// Pre-allocate with capacity hint to avoid map growth reallocations
	estimatedCap := len(l.defaultAttributes) + len(entryAttrs) + len(args) + 8 // scope ~3 + instance ~5
	attrs := make(map[string]Attribute, estimatedCap)

	// attribute precedence: default -> scope -> instance (from SetAttrs) -> entry-specific
	for k, v := range l.defaultAttributes {
		attrs[k] = v
	}
	scope.populateAttrs(attrs)

	l.mu.RLock()
	for k, v := range l.attributes {
		attrs[k] = v
	}
	l.mu.RUnlock()

	for k, v := range entryAttrs {
		attrs[k] = v
	}

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

	log := &Log{
		Timestamp:  time.Now(),
		TraceID:    traceID,
		SpanID:     spanID,
		Level:      level,
		Severity:   severity,
		Body:       fmt.Sprintf(message, args...),
		Attributes: attrs,
	}

	l.client.captureLog(log, scope)

	if l.client.options.Debug {
		debuglog.Printf(message, args...)
	}
}

func (l *sentryLogger) SetAttributes(attrs ...attribute.Builder) {
	l.mu.Lock()
	defer l.mu.Unlock()

	for _, v := range attrs {
		t, ok := mapTypesToStr[v.Value.Type()]
		if !ok || t == "" {
			debuglog.Printf("invalid attribute type set: %v", t)
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
		shouldPanic: true,
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
