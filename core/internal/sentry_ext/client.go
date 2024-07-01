package sentry_ext

import (
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/getsentry/sentry-go"
)

type Params struct {
	// DSN is the Data Source Name for the sentry client
	DSN string
	// AttachStacktrace is a flag to attach stacktrace to the sentry event
	AttachStacktrace bool
	// Release is the version of the application
	Release string
	// Commit is the git commit hash
	Commit string
	// Environment is the environment the application is running in
	Environment string
	// BeforeSend is a callback to modify the event before sending it to sentry
	BeforeSend func(*sentry.Event, *sentry.EventHint) *sentry.Event
	// LRUSize is the size of the LRU cache
	LRUSize int
}

type Client struct {
	// Recent is the cache of recent errors sent to sentry to avoid sending
	// the same error multiple times
	Recent *cache
}

// New initializes the sentry client.
//
// If the DSN is not set, the client is effectively disabled and will not send
// any errors to sentry.
// If we can't create the cache, we will log an error and return nil.
func New(params Params) *Client {

	if params.BeforeSend == nil {
		params.BeforeSend = RemoveBottomFrames
	}
	if err := sentry.Init(
		sentry.ClientOptions{
			Dsn:              params.DSN,
			AttachStacktrace: params.AttachStacktrace,
			Release:          params.Release,
			Dist:             params.Commit,
			BeforeSend:       params.BeforeSend,
			Environment:      params.Environment,
		}); err != nil {
		slog.Error("sentry_ext: New: failed to initialize sentry", "err", err)
	}

	if params.DSN == "" {
		slog.Debug("sentry_ext: New: sentry is disabled, no DSN provided")
	} else {
		slog.Debug("sentry_ext: New: sentry is enabled", "dsn", params.DSN)
	}

	cache, err := newCache(params.LRUSize)
	if err != nil {
		slog.Error("sentry_ext: New: failed to create cache", "err", err)
		return nil
	}

	// If the DSN is not set, the client is effectively disabled.
	return &Client{
		Recent: cache,
	}
}

// SetUser sets the user information for the sentry client.
func (s *Client) SetUser(id, email, name string) {
	sentry.ConfigureScope(func(scope *sentry.Scope) {
		scope.SetUser(sentry.User{
			ID:    id,
			Email: email,
			Name:  name,
		})
	})
}

// CaptureException captures an error and sends it to sentry.
// Used for capturing errors. The error is sent to sentry as an error level
// event. The event is enriched with the tags provided.
func (s *Client) CaptureException(err error, tags map[string]string) {
	if !s.Recent.shouldCapture(err) {
		return
	}

	// Send the error to sentry
	localHub := sentry.CurrentHub().Clone()
	localHub.ConfigureScope(
		func(scope *sentry.Scope) {
			scope.SetTags(tags)
		},
	)
	localHub.CaptureException(err)
}

// CaptureMessage captures a message and sends it to sentry.
// Used for capturing non-error messages. The message is sent to sentry as an
// info level event. The event is enriched with the tags provided.
func (s *Client) CaptureMessage(msg string, tags map[string]string) {
	if !s.Recent.shouldCapture(errors.New(msg)) {
		return
	}

	localHub := sentry.CurrentHub().Clone()
	localHub.ConfigureScope(
		func(scope *sentry.Scope) {
			scope.SetTags(tags)
		},
	)
	localHub.CaptureMessage(msg)
}

// Reraise captures an error and re-raises it.
// Used to capture unexpected panics.
func (s *Client) Reraise(err any, tags map[string]string) {
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
func (s *Client) Flush(timeout time.Duration) bool {
	hub := sentry.CurrentHub()
	return hub.Flush(timeout)
}

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
		// will come from client.go and logging.go, so we remove them
		if framesLen < 3 {
			continue
		}
		for j := framesLen - 1; j >= framesLen-3; j-- {
			frame := frames[j]
			// TODO: think of a better way to do this without hard-coding the
			// file names this is a hack to remove the bottom-most 3 frames that
			// are internal to core
			if strings.HasSuffix(frame.AbsPath, "client.go") || strings.HasSuffix(frame.AbsPath, "logging.go") {
				frames = frames[:j]
			} else {
				break
			}
		}
		event.Exception[i].Stacktrace.Frames = frames
	}
	return event
}
