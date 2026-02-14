// Package wberrors defines a rich error type for wandb-core.
//
// `fmt.Errorf` is replaced by Newf, Enrichf and Bubblef:
//
//   - Newf constructs an error from a formatted message.
//   - Enrichf is like Newf, but it preserves an underlying error's data.
//     It is like using `fmt.Errorf` with the `%v` verb.
//   - Bubblef is like Enrichf, but it exposes the underlying error.
//     It is like using `fmt.Errorf` with the `%w` verb.
//
// `errors.Join` has no replacement; using it to combine errors will discard
// enrichment data.
//
// The methods SkipSentryIf, Attr and Fingerprint enrich an error; see their
// documentation. All of them return the error itself to allow for method
// chaining:
//
//	return wberrors.Enrichf(err, "failed to open %s", filename).
//		Attr(slog.String("path", path)).
//		SkipSentryIf(os.IsPermission(err))
//
// To ensure enriched attributes make it to the logging code, all code must
// use Newf, Enrichf and Bubblef. Never use `fmt.Errorf` to wrap an error, since
// that will discard its extra data. For consistency, never use `fmt.Errorf`
// or `errors.New` even to create a fresh error; prefer Newf.
//
// Become familiar with https://google.github.io/styleguide/go/best-practices.html#error-handling
package wberrors

import (
	"fmt"
	"log/slog"
	"maps"
	"slices"
)

// Attrs returns any slog attrs stored in the error.
func Attrs(err error) []slog.Attr {
	if wberr, ok := err.(*Error); ok {
		attrs := make([]slog.Attr, 0, len(wberr.attrs))

		for key, value := range wberr.attrs {
			attrs = append(attrs, slog.Attr{Key: key, Value: value})
		}

		return attrs
	}

	return nil
}

// Tags returns the Sentry tags stored in the error.
func Tags(err error) map[string]string {
	if wberr, ok := err.(*Error); ok {
		tags := make(map[string]string, len(wberr.attrs))

		for key, value := range wberr.attrs {
			tags[key] = value.String()
		}

		return tags
	}

	return nil
}

// SkipSentry returns true if the error was marked as not needing to be
// captured.
//
// This allows lower-level code to filter out uninteresting error conditions.
func SkipSentry(err error) bool {
	if wberr, ok := err.(*Error); ok {
		return wberr.noSentry
	}

	return false
}

// ExtraFingerprint returns additional parts to include in the error's Sentry
// fingerprint.
func ExtraFingerprint(err error) []string {
	if wberr, ok := err.(*Error); ok {
		return wberr.fingerprint
	}

	return nil
}

// Error is a standard Go error with additional info for W&B observability.
//
// Errors are *not* safe for concurrent use. Prefer to construct and mutate an
// error in a single statement using method chaining. Never mutate an error
// you didn't construct or that was constructed in a different goroutine.
//
// See the package documentation.
type Error struct {
	msg string // error message or context
	err error  // wrapped error or nil

	noSentry    bool     // whether to skip Sentry upload
	fingerprint []string // extra Sentry fingerprint data

	// attrs is structured data to associate to the error.
	//
	// It is meant to be included in structured logging using slog and also
	// uploaded as tags to Sentry if the error is captured.
	attrs map[string]slog.Value
}

// Newf creates a new error using Sprintf to construct the message.
func Newf(format string, args ...any) *Error {
	return &Error{msg: fmt.Sprintf(format, args...)}
}

// Enrichf enriches an error without exposing it through `errors.Unwrap`.
//
// Given an empty format string, the resulting error's string representation
// is the same as the given error's. Otherwise, Sprintf is used to construct
// a message that is prepended to the given error's message with a separating
// colon.
//
// If the given error is already enriched, then its fingerprint and attrs are
// copied over. If it skips Sentry upload, the resulting error will skip Sentry
// upload too.
func Enrichf(err error, format string, args ...any) *Error {
	return wrap(fmt.Sprintf(format, args...), err, false)
}

// Bubblef is like Enrichf, but exposes the given error through `errors.Unwrap`.
//
// The resulting error matches the inner error using `errors.Is`.
//
// In most cases, you should use Enrichf instead. A function may use Bubblef
// when it's intentionally designed to propagate inner errors for the caller
// to inspect using `errors.Is` or `errors.As`. Do not bubble an error if it
// would expose implementation details.
//
// See https://go.dev/blog/go1.13-errors#whether-to-wrap
func Bubblef(err error, format string, args ...any) *Error {
	return wrap(fmt.Sprintf(format, args...), err, true)
}

func wrap(msg string, err error, shouldWrap bool) *Error {
	if err == nil {
		panic("wberrors: cannot wrap nil error")
	}

	wrapped := &Error{}

	switch {
	case shouldWrap:
		wrapped.msg = msg
		wrapped.err = err
	case msg == "":
		wrapped.msg = err.Error()
	default:
		wrapped.msg = fmt.Sprintf("%s: %v", msg, err)
	}

	if wberr, ok := err.(*Error); ok {
		wrapped.noSentry = wberr.noSentry
		wrapped.fingerprint = slices.Clone(wberr.fingerprint)
		wrapped.attrs = maps.Clone(wberr.attrs)
	}

	return wrapped
}

// Attr associates structured data to the error and returns the error.
//
// The key-value pair is included when the error is logged via `slog`.
//
// It is also added as a tag in the associated Sentry event if this error is
// captured.
//
// If the error already has an attr with the same key, it is overwritten.
// These attrs take precedence over attrs included by the logger.
func (e *Error) Attr(attr slog.Attr) *Error {
	if e.attrs == nil {
		e.attrs = make(map[string]slog.Value)
	}

	e.attrs[attr.Key] = attr.Value
	return e
}

// SkipSentryIf marks the error as one that should not be uploaded to Sentry
// if the condition is true, and returns it.
//
// If the condition is false, the error is unchanged.
func (e *Error) SkipSentryIf(condition bool) *Error {
	e.noSentry = e.noSentry || condition
	return e
}

// Fingerprint appends to the error's Sentry fingerprint and returns the error.
//
// Sentry events with the same fingerprint are grouped into the same issue.
// Appending extra information to the error, like an HTTP status code,
// results in more granular Sentry issues.
//
// See https://docs.sentry.io/platforms/go/usage/sdk-fingerprinting/.
func (e *Error) Fingerprint(parts ...string) *Error {
	e.fingerprint = append(e.fingerprint, parts...)
	return e
}

// Error implements error.Error.
func (e *Error) Error() string {
	switch {
	case e.err == nil:
		return e.msg
	case e.msg == "":
		return e.err.Error()
	default:
		return fmt.Sprintf("%s: %v", e.msg, e.err)
	}
}

// Unwrap returns the inner error.
//
// This works with the `errors.Unwrap()` and `errors.Is()` functions.
func (e *Error) Unwrap() error {
	return e.err
}
