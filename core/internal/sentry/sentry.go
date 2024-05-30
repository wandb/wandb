package sentry

import (
	"crypto/md5"
	"encoding/hex"
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"sync"
	"time"

	"github.com/getsentry/sentry-go"
	lru "github.com/hashicorp/golang-lru"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/pkg/observability"
)

const SentryDSN = "https://0d0c6674e003452db392f158c42117fb@o151352.ingest.sentry.io/4505513612214272"

type SentryClient struct {
	DSN          string
	Commit       string
	mu           sync.Mutex
	RecentErrors *lru.Cache
}

var recentErrorDuration = time.Minute * 5

// RemoveBottomFrames modifies the stack trace by checking the file name of the bottom-most 3 frames
// and removing them if they are internal to core
func RemoveBottomFrames(event *sentry.Event, hint *sentry.EventHint) *sentry.Event {
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
			// TODO: think of a better way to do this without hard-coding the file names
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

// New initializes the sentry client.
func New(disabled bool, commit string) *SentryClient {
	cache, err := lru.New(100) // Set the max size of the cache
	if err != nil {
		slog.Error("failed to create LRU cache", "err", err)
		return nil
	}
	s := &SentryClient{
		Commit:       commit,
		RecentErrors: cache,
	}

	// The DSN to use. If the DSN is not set, the client is effectively disabled.
	if !disabled {
		s.DSN = SentryDSN
	}

	err = sentry.Init(sentry.ClientOptions{
		Dsn:              s.DSN,
		AttachStacktrace: true,
		Release:          version.Version,
		Dist:             s.Commit,
		BeforeSend:       RemoveBottomFrames,
	})

	if err != nil {
		slog.Error("sentry.Init failed", "err", err)
	}

	if !disabled {
		slog.Debug("sentry.Init succeeded", "dsn", s.DSN)
	} else {
		slog.Debug("sentry is disabled")
	}

	return s
}

// CaptureException captures an error and sends it to sentry.
func (s *SentryClient) CaptureException(err error, tags observability.Tags) {
	s.mu.Lock()
	defer s.mu.Unlock()

	// Generate a hash of the error message
	h := md5.New()
	h.Write([]byte(err.Error()))
	hash := hex.EncodeToString(h.Sum(nil))

	now := time.Now()
	if lastSent, exists := s.RecentErrors.Get(hash); exists {
		if now.Sub(lastSent.(time.Time)) < recentErrorDuration {
			return // Skip sending the error if it's too recent
		}
	}

	// Update the timestamp for the error
	s.RecentErrors.Add(hash, now)

	// Send the error to sentry
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

// CaptureMessage captures a message and sends it to sentry.
func (s *SentryClient) CaptureMessage(msg string, tags observability.Tags) {
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
func (s *SentryClient) Reraise(err any, tags observability.Tags) {
	if err != nil {
		var e error
		if errors.As(e, &err) {
			s.CaptureException(e, tags)
		} else {
			e = fmt.Errorf("%v", err)
			s.CaptureException(e, tags)
		}
		sentry.Flush(time.Second * 2)
		panic(err)
	}
}

// Flush flushes the sentry client.
func (s *SentryClient) Flush(timeout time.Duration) bool {
	hub := sentry.CurrentHub()
	return hub.Flush(timeout)
}
