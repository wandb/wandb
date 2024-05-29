package observability

import (
	"crypto/md5"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/version"

	"github.com/getsentry/sentry-go"
)

const sentryDsn = "https://0d0c6674e003452db392f158c42117fb@o151352.ingest.sentry.io/4505513612214272"

type SentryClient struct {
	Dsn          string
	Commit       string
	mu           sync.Mutex
	RecentErrors map[string]time.Time
}

var recentErrorDuration = time.Minute * 5

// removeBottomFrames modifies the stack trace by checking the file name of the bottom-most 3 frames
// and removing them if they are internal to core
func removeBottomFrames(event *sentry.Event, hint *sentry.EventHint) *sentry.Event {
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
}

func InitSentry(disabled bool, commit string) {
	s := &SentryClient{
		Commit:       commit,
		RecentErrors: make(map[string]time.Time),
	}

	// The DSN to use. If the DSN is not set, the client is effectively disabled.
	if !disabled {
		s.Dsn = sentryDsn
	}

	err := sentry.Init(sentry.ClientOptions{
		Dsn:              s.Dsn,
		AttachStacktrace: true,
		Release:          version.Version,
		Dist:             s.Commit,
		BeforeSend:       removeBottomFrames,
	})

	if err != nil {
		slog.Error("sentry.Init failed", "err", err)
	}

	if !disabled {
		slog.Debug("sentry.Init succeeded", "dsn", s.Dsn)
	} else {
		slog.Debug("sentry is disabled")
	}

	// CaptureException captures an error and sends it to sentry.
	captureWithErrorCache := func(err error, tags Tags) {
		s.mu.Lock()
		defer s.mu.Unlock()

		// Generate a hash of the error message
		h := md5.New()
		h.Write([]byte(err.Error()))
		hash := hex.EncodeToString(h.Sum(nil))

		now := time.Now()
		if lastSent, exists := s.RecentErrors[hash]; exists {
			if now.Sub(lastSent) < recentErrorDuration {
				return // Skip sending the error if it's too recent
			}
		}

		// Update the timestamp for the error
		s.RecentErrors[hash] = now
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

	CaptureException = captureWithErrorCache
}

// CaptureException captures an error and sends it to sentry.
var CaptureException func(err error, tags Tags) = func(err error, tags Tags) {}

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
