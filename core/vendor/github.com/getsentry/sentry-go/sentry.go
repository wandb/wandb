package sentry

import (
	"context"
	"time"
)

// The version of the SDK.
const SDKVersion = "0.34.1"

// apiVersion is the minimum version of the Sentry API compatible with the
// sentry-go SDK.
const apiVersion = "7"

// Init initializes the SDK with options. The returned error is non-nil if
// options is invalid, for instance if a malformed DSN is provided.
func Init(options ClientOptions) error {
	hub := CurrentHub()
	client, err := NewClient(options)
	if err != nil {
		return err
	}
	hub.BindClient(client)
	return nil
}

// AddBreadcrumb records a new breadcrumb.
//
// The total number of breadcrumbs that can be recorded are limited by the
// configuration on the client.
func AddBreadcrumb(breadcrumb *Breadcrumb) {
	hub := CurrentHub()
	hub.AddBreadcrumb(breadcrumb, nil)
}

// CaptureMessage captures an arbitrary message.
func CaptureMessage(message string) *EventID {
	hub := CurrentHub()
	return hub.CaptureMessage(message)
}

// CaptureException captures an error.
func CaptureException(exception error) *EventID {
	hub := CurrentHub()
	return hub.CaptureException(exception)
}

// CaptureCheckIn captures a (cron) monitor check-in.
func CaptureCheckIn(checkIn *CheckIn, monitorConfig *MonitorConfig) *EventID {
	hub := CurrentHub()
	return hub.CaptureCheckIn(checkIn, monitorConfig)
}

// CaptureEvent captures an event on the currently active client if any.
//
// The event must already be assembled. Typically code would instead use
// the utility methods like CaptureException. The return value is the
// event ID. In case Sentry is disabled or event was dropped, the return value will be nil.
func CaptureEvent(event *Event) *EventID {
	hub := CurrentHub()
	return hub.CaptureEvent(event)
}

// Recover captures a panic.
func Recover() *EventID {
	if err := recover(); err != nil {
		hub := CurrentHub()
		return hub.Recover(err)
	}
	return nil
}

// RecoverWithContext captures a panic and passes relevant context object.
func RecoverWithContext(ctx context.Context) *EventID {
	err := recover()
	if err == nil {
		return nil
	}

	hub := GetHubFromContext(ctx)
	if hub == nil {
		hub = CurrentHub()
	}

	return hub.RecoverWithContext(ctx, err)
}

// WithScope is a shorthand for CurrentHub().WithScope.
func WithScope(f func(scope *Scope)) {
	hub := CurrentHub()
	hub.WithScope(f)
}

// ConfigureScope is a shorthand for CurrentHub().ConfigureScope.
func ConfigureScope(f func(scope *Scope)) {
	hub := CurrentHub()
	hub.ConfigureScope(f)
}

// PushScope is a shorthand for CurrentHub().PushScope.
func PushScope() {
	hub := CurrentHub()
	hub.PushScope()
}

// PopScope is a shorthand for CurrentHub().PopScope.
func PopScope() {
	hub := CurrentHub()
	hub.PopScope()
}

// Flush waits until the underlying Transport sends any buffered events to the
// Sentry server, blocking for at most the given timeout. It returns false if
// the timeout was reached. In that case, some events may not have been sent.
//
// Flush should be called before terminating the program to avoid
// unintentionally dropping events.
//
// Do not call Flush indiscriminately after every call to CaptureEvent,
// CaptureException or CaptureMessage. Instead, to have the SDK send events over
// the network synchronously, configure it to use the HTTPSyncTransport in the
// call to Init.
func Flush(timeout time.Duration) bool {
	hub := CurrentHub()
	return hub.Flush(timeout)
}

// FlushWithContext waits until the underlying Transport sends any buffered events
// to the Sentry server, blocking for at most the duration specified by the context.
// It returns false if the context is canceled before the events are sent. In such a case,
// some events may not be delivered.
//
// FlushWithContext should be called before terminating the program to ensure no
// events are unintentionally dropped.
//
// Avoid calling FlushWithContext indiscriminately after each call to CaptureEvent,
// CaptureException, or CaptureMessage. To send events synchronously over the network,
// configure the SDK to use HTTPSyncTransport during initialization with Init.

func FlushWithContext(ctx context.Context) bool {
	hub := CurrentHub()
	return hub.FlushWithContext(ctx)
}

// LastEventID returns an ID of last captured event.
func LastEventID() EventID {
	hub := CurrentHub()
	return hub.LastEventID()
}
