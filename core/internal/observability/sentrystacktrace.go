package observability

import (
	"reflect"
	"strings"

	"github.com/getsentry/sentry-go"
)

// coreLoggerPackage is the Go import path for the CoreLogger.
//
// Specifically, "github.com/wandb/wandb/core/internal/observability".
var coreLoggerPackage = reflect.TypeFor[CoreLogger]().PkgPath()

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
	return strings.HasPrefix(frame.Module, coreLoggerPackage)
}
