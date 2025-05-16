package sentry

import (
	"context"
	"fmt"
	"os"

	"github.com/getsentry/sentry-go/attribute"
)

// Fallback, no-op logger if logging is disabled.
type noopLogger struct{}

func (*noopLogger) Trace(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelTrace)
}
func (*noopLogger) Debug(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelDebug)
}
func (*noopLogger) Info(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelInfo)
}
func (*noopLogger) Warn(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelWarn)
}
func (*noopLogger) Error(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelError)
}
func (*noopLogger) Fatal(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal)
	os.Exit(1)
}
func (*noopLogger) Panic(_ context.Context, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal)
	panic(fmt.Sprintf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal))
}
func (*noopLogger) Tracef(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelTrace)
}
func (*noopLogger) Debugf(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelDebug)
}
func (*noopLogger) Infof(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelInfo)
}
func (*noopLogger) Warnf(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelWarn)
}
func (*noopLogger) Errorf(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelError)
}
func (*noopLogger) Fatalf(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal)
	os.Exit(1)
}
func (*noopLogger) Panicf(_ context.Context, _ string, _ ...interface{}) {
	DebugLogger.Printf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal)
	panic(fmt.Sprintf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelFatal))
}
func (*noopLogger) SetAttributes(...attribute.Builder) {
	DebugLogger.Printf("No attributes attached. Turn on logging via EnableLogs")
}
func (*noopLogger) Write(_ []byte) (n int, err error) {
	return 0, fmt.Errorf("Log with level=[%v] is being dropped. Turn on logging via EnableLogs", LogLevelInfo)
}
