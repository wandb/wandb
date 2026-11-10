package filestream

import (
	"cmp"
	"errors"
	"fmt"
	"maps"
	"slices"
	"sync/atomic"
)

// minRejectedRequestBytes is the request size at or below which a 413
// response is not treated as a size problem.
//
// Proxies that reject requests this small are not expected, so such a 413
// more likely means something other than the request's size is wrong.
const minRejectedRequestBytes = 64 << 10

// RequestSizeLimit is a request size cap that can only decrease.
//
// It is safe for concurrent use. A nil limit applies no cap.
type RequestSizeLimit struct {
	bytes atomic.Int64 // 0 if not lowered
}

// Apply returns maxBytes, lowered to the limit if there is one.
func (l *RequestSizeLimit) Apply(maxBytes int) int {
	if l == nil {
		return maxBytes
	}

	if limit := int(l.bytes.Load()); limit > 0 && limit < maxBytes {
		return limit
	}
	return maxBytes
}

// Lower sets the limit to n bytes if that is lower than the current limit.
func (l *RequestSizeLimit) Lower(n int) {
	for {
		current := l.bytes.Load()
		if current > 0 && current <= int64(n) {
			return
		}
		if l.bytes.CompareAndSwap(current, int64(n)) {
			return
		}
	}
}

// requestTooLargeError is returned by send when the server responds
// with 413 Content Too Large.
type requestTooLargeError struct {
	// WireBytes is the size of the request body as sent, after any
	// compression.
	WireBytes int

	// JSONBytes is the size of the uncompressed JSON request.
	JSONBytes int

	err error
}

func (e *requestTooLargeError) Error() string { return e.err.Error() }
func (e *requestTooLargeError) Unwrap() error { return e.err }

// sendSplittingIfTooLarge sends a request, splitting it in two and sending
// each part in order if the server rejects it as too large.
//
// After a rejection, later requests are built at most half the rejected size.
//
// It returns an error, which stops the uploader, if a rejected part cannot be
// split (a single line or file name), or is no larger than a request that was
// already accepted or than minRejectedRequestBytes, since splitting is then
// unlikely to help. Parts after a failed part are not sent, so the run is
// never marked complete with data missing.
func (fs *fileStream) sendSplittingIfTooLarge(
	data *FileStreamRequestJSON,
	feedbackChan chan<- map[string]any,
) error {
	err := fs.send(data, feedbackChan)

	tooLarge, ok := errors.AsType[*requestTooLargeError](err)
	if !ok {
		return err
	}

	if tooLarge.WireBytes <= max(fs.largestAcceptedWireBytes, minRejectedRequestBytes) {
		return fmt.Errorf(
			"filestream: request of %d bytes rejected as too large,"+
				" but a request of %d bytes was accepted: %w",
			tooLarge.WireBytes,
			fs.largestAcceptedWireBytes,
			err,
		)
	}

	fs.sizeLimit.Lower(max(tooLarge.JSONBytes/2, minRejectedRequestBytes))

	first, second, ok := splitRequest(data)
	if !ok {
		return fmt.Errorf(
			"filestream: request of %d bytes rejected as too large"+
				" cannot be split: %w",
			tooLarge.WireBytes,
			err,
		)
	}

	fs.logger.Info(
		"filestream: request too large, splitting",
		"wire_bytes", tooLarge.WireBytes,
		"json_bytes", tooLarge.JSONBytes,
	)

	if err := fs.sendSplittingIfTooLarge(first, feedbackChan); err != nil {
		return err
	}
	return fs.sendSplittingIfTooLarge(second, feedbackChan)
}

// hasMetadata reports whether the request has anything besides files.
func hasMetadata(r *FileStreamRequestJSON) bool {
	return len(r.Uploaded) > 0 ||
		r.Preempting != nil ||
		r.Complete != nil ||
		r.ExitCode != nil
}

// hasFlags reports whether the request has a preempting or exit state.
func hasFlags(r *FileStreamRequestJSON) bool {
	return r.Preempting != nil || r.Complete != nil || r.ExitCode != nil
}

// fileOrder is the order in which files are split off a request.
var fileOrder = map[string]int{
	HistoryFileName: 0,
	EventsFileName:  1,
	SummaryFileName: 2,
	OutputFileName:  3,
}

// splitRequest splits a request into two that, sent in order, have the
// same effect.
//
// It splits off one file if there are several, otherwise splits the file's
// lines in half, and otherwise splits the list of uploaded files in half.
// The second request keeps the preempting flag and exit state, so a run is
// only marked complete after all of its data is sent.
//
// It returns false if the request has only one line, or only one uploaded
// file, and nothing else.
func splitRequest(
	r *FileStreamRequestJSON,
) (first, second *FileStreamRequestJSON, ok bool) {
	names := slices.SortedFunc(maps.Keys(r.Files), func(a, b string) int {
		ia, aKnown := fileOrder[a]
		ib, bKnown := fileOrder[b]
		switch {
		case aKnown && bKnown:
			return cmp.Compare(ia, ib)
		case aKnown != bKnown:
			if aKnown {
				return -1
			}
			return 1
		default:
			return cmp.Compare(a, b)
		}
	})

	second = &FileStreamRequestJSON{
		Files:      maps.Clone(r.Files),
		Uploaded:   r.Uploaded,
		Preempting: r.Preempting,
		Complete:   r.Complete,
		ExitCode:   r.ExitCode,
	}

	switch {
	case len(names) >= 2:
		first = &FileStreamRequestJSON{
			Files: map[string]OffsetAndContent{names[0]: r.Files[names[0]]},
		}
		delete(second.Files, names[0])
		return first, second, true

	case len(names) == 1 && len(r.Files[names[0]].Content) >= 2:
		chunk := r.Files[names[0]]
		half := len(chunk.Content) / 2

		first = &FileStreamRequestJSON{
			Files: map[string]OffsetAndContent{names[0]: {
				Offset:  chunk.Offset,
				Content: chunk.Content[:half],
			}},
		}
		second.Files[names[0]] = OffsetAndContent{
			Offset:  chunk.Offset + half,
			Content: chunk.Content[half:],
		}
		return first, second, true

	case len(names) == 1 && hasMetadata(r):
		first = &FileStreamRequestJSON{Files: r.Files}
		second.Files = nil
		return first, second, true

	case len(names) == 0 && len(r.Uploaded) >= 2:
		half := len(r.Uploaded) / 2
		first = &FileStreamRequestJSON{Uploaded: r.Uploaded[:half]}
		second.Uploaded = r.Uploaded[half:]
		return first, second, true

	case len(names) == 0 && len(r.Uploaded) == 1 && hasFlags(r):
		first = &FileStreamRequestJSON{Uploaded: r.Uploaded}
		second.Uploaded = nil
		return first, second, true

	default:
		return nil, nil, false
	}
}
