package sentry_ext

import (
	"errors"
	"fmt"
	"log/slog"
	"strings"
	"time"

	"github.com/getsentry/sentry-go"
	"github.com/wandb/wandb/core/pkg/observability"
)

type Params struct {
	DSN              string
	AttachStacktrace bool
	Release          string
	Commit           string
	Environment      string
	BeforeSend       func(*sentry.Event, *sentry.EventHint) *sentry.Event
	LRUSize          int
}

type Client struct {
	Recent *cache
}

// New initializes the sentry client.
func New(params Params) *Client {

	if params.BeforeSend == nil {
		params.BeforeSend = RemoveBottomFrames
	}

	err := sentry.Init(sentry.ClientOptions{
		Dsn:              params.DSN,
		AttachStacktrace: params.AttachStacktrace,
		Release:          params.Release,
		Dist:             params.Commit,
		BeforeSend:       params.BeforeSend,
		Environment:      params.Environment,
	})

	if err != nil {
		slog.Error("sentry: New: failed to initialize sentry", "err", err)
	}

	if params.DSN != "" {
		slog.Debug("sentry: New: sentry is enabled", "dsn", params.DSN)
	} else {
		slog.Debug("sentry is disabled")
	}

	cache, err := newCache(params.LRUSize)
	if err != nil {
		slog.Error("failed to create LRU cache", "err", err)
		return nil
	}

	// If the DSN is not set, the client is effectively disabled.
	s := &Client{
		Recent: cache,
	}

	return s
}

func (s *Client) SetUser(id, email, name string) {

	localHub := sentry.CurrentHub().Clone()
	localHub.ConfigureScope(func(scope *sentry.Scope) {
		scope.SetUser(sentry.User{
			ID:    id,
			Email: email,
			Name:  name,
		})
	})
}

// CaptureException captures an error and sends it to sentry.
func (s *Client) CaptureException(err error, tags observability.Tags) {
	if !s.Recent.shouldCapture(err) {
		return
	}

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
func (s *Client) CaptureMessage(msg string, tags observability.Tags) {
	if !s.Recent.shouldCapture(errors.New(msg)) {
		return
	}

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
func (s *Client) Reraise(err any, tags observability.Tags) {
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
