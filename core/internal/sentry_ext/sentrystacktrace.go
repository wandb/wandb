package sentry_ext

import (
	"reflect"
	"strings"

	"github.com/getsentry/sentry-go"
)

var (
	// coreLoggerPackage is the Go import path for the CoreLogger.
	//
	// Hard-coded to avoid import cycle. Correctness checked in unit test
	// using reflection.
	coreLoggerPackage = "github.com/wandb/wandb/core/internal/observability"

	// sentryExtPackage is the Go import path for this package.
	//
	// Specifically, "github.com/wandb/wandb/core/internal/sentry_ext".
	sentryExtPackage = reflect.TypeFor[Client]().PkgPath()
)

// RemoveLoggerFrames is a [sentry.EventProcessor] that strips internal
// logging infrastructure frames from the top of each stack trace.
//
// For Sentry events captured via [CoreLogger.CaptureError] and similar methods,
// the stack trace's top frame will be the caller of the logger method.
func RemoveLoggerFrames(
	event *sentry.Event,
	hint *sentry.EventHint,
) *sentry.Event {
	for _, exception := range event.Exception {
		if exception.Stacktrace == nil {
			continue
		}

		// Frames are ordered caller-first (caller before callee).
		frames := exception.Stacktrace.Frames
		for len(frames) > 0 && shouldHideFrame(&frames[len(frames)-1]) {
			frames = frames[:len(frames)-1]
		}

		exception.Stacktrace.Frames = frames
	}

	return event
}

// shouldHideFrame reports whether a stack frame should be hidden in Sentry.
//
// Accepts sentry.Frame by pointer as it is a large struct.
func shouldHideFrame(frame *sentry.Frame) bool {
	// Same strategy the Sentry SDK uses to filter out its own frames.
	return strings.HasPrefix(frame.Module, coreLoggerPackage) ||
		strings.HasPrefix(frame.Module, sentryExtPackage)
}
