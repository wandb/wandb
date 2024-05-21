package observability

import (
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/wandb/wandb/core/internal/version"

	"github.com/getsentry/sentry-go"
)

type SentryClient struct {
	Dsn    string
	Commit string
}

func InitSentry(dsn string, disabled bool, commit string) {
	s := &SentryClient{
		Commit: commit,
	}

	// The DSN to use. If the DSN is not set, the client is effectively disabled.
	if !disabled {
		s.Dsn = dsn
	}

	err := sentry.Init(sentry.ClientOptions{
		Dsn:              s.Dsn,
		AttachStacktrace: true,
		Release:          version.Version,
		Dist:             s.Commit,
		BeforeSend: func(event *sentry.Event, hint *sentry.EventHint) *sentry.Event {
			// Modify the stack trace by checking the file name of the bottom-most 3 frames.
			for i, exception := range event.Exception {
				if exception.Stacktrace == nil {
					continue
				}
				frames := exception.Stacktrace.Frames
				framesLen := len(frames)
				// for the recovered panics, the bottom-most 3 frames of the stacktrace
				// will come from sentry.go and logging.go, so we remove them
				if framesLen < 3 {
					continue
				}
				for j := framesLen - 1; j >= framesLen-3; j-- {
					frame := frames[j]
					// todo: think of a better way to do this without hard-coding the file names
					//  this is a hack to remove the bottom-most 3 frames that are internal to core
					if strings.HasSuffix(frame.AbsPath, "sentry.go") || strings.HasSuffix(frame.AbsPath, "logging.go") {
						frames = frames[:j]
					} else {
						break
					}
				}
				event.Exception[i].Stacktrace.Frames = frames
			}
			return event
		},
	})

	if err != nil {
		slog.Error("sentry.Init failed", "err", err)
	}

	if !disabled {
		slog.Debug("sentry.Init succeeded", "dsn", s.Dsn)
	} else {
		slog.Debug("sentry is disabled")
	}
}

func CaptureException(err error, tags Tags) {
	localHub := sentry.CurrentHub().Clone()
	localHub.ConfigureScope(func(scope *sentry.Scope) {
		for k, v := range tags {
			if v != "" {
				scope.SetTag(k, v)
			}
		}
	})
	localHub.CaptureException(err)
}

func CaptureMessage(msg string, tags Tags) {
	localHub := sentry.CurrentHub().Clone()
	localHub.ConfigureScope(func(scope *sentry.Scope) {
		for k, v := range tags {
			scope.SetTag(k, v)
		}
	})
	localHub.CaptureMessage(msg)
}

// Reraise captures an error and re-raises it.
// Used to capture unexpected panics.
func Reraise(err any, tags Tags) {
	if err != nil {
		var e error
		if errors.As(e, &err) {
			CaptureException(e, tags)
		} else {
			e = fmt.Errorf("%v", err)
			CaptureException(e, tags)
		}
		sentry.Flush(time.Second * 2)
		panic(err)
	}
}
