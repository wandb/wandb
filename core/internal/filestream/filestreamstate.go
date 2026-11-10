package filestream

import (
	"fmt"
	"maps"
	"slices"
	"time"

	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
)

// FileStreamState turns a [FileStreamRequest] into sequence
// of [FileStreamRequestJSON].
type FileStreamState struct {
	// MaxRequestSizeBytes is an approximate maximum FileStream request size
	// in bytes.
	MaxRequestSizeBytes int

	// MaxFileLineSize is an approximate maximum per-line size in bytes for
	// the "Files" uploaded in FileStream.
	MaxFileLineSize int

	// HistoryLineNum is the line number where to append history.
	HistoryLineNum int

	// EventsLineNum is the line number where to append system metrics.
	EventsLineNum int

	// SummaryLineNum is the line number where to write the summary.
	//
	// The same line is always overwritten. The reason we don't solely
	// update line 0 is for compatibility with previous versions which
	// appended summaries. The backend only looks at the last line, so
	// to properly resume such a run we must update the last line.
	SummaryLineNum int

	// RunSummary is the run's full summary.
	//
	// It may be nil if the run has no summary.
	RunSummary *runsummary.RunSummary

	// UnsentSummary is the serialized RunSummary if it did not fit in
	// a previous request.
	UnsentSummary string

	// LastRunSummarySize is the size in bytes of the RunSummary's
	// last successfully serialized JSON value.
	//
	// If there is a non-empty UnsentSummary, this is its length.
	LastRunSummarySize int

	// ConsoleLineOffset is an offset to add to all console updates.
	//
	// This is used when resuming a run, in which case we want the new
	// console logs to be appended to the old ones.
	ConsoleLineOffset int

	// AcceptSummaryDelta reports whether the backend accepts summary deltas.
	//
	// If nil, the full summary is always sent.
	AcceptSummaryDelta func() bool

	// summaryDelta is the summary changes since the last summary sent.
	//
	// It is nil until a summary is sent while the backend accepts deltas,
	// so the first summary of a stream is always full.
	summaryDelta *runsummary.Updates

	// unsentSummaryIsDelta is whether UnsentSummary holds summaryDelta.
	unsentSummaryIsDelta bool

	// deltaSinceFull is whether a delta was sent or dropped after the last
	// full summary.
	deltaSinceFull bool
}

// IsAtSizeLimit returns true if the next JSON chunk of the request could
// contain more than around maxBytes of data.
func (s *FileStreamState) IsAtSizeLimit(request *FileStreamRequest) bool {
	approxSize := 0

	for _, line := range request.HistoryLines {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	for _, line := range request.EventsLines {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	// Use the last summary size to approximate the next.
	// It is too expensive to serialize the summary every time and too complex
	// to track its size incrementally.
	if !request.SummaryUpdates.IsEmpty() || s.UnsentSummary != "" {
		approxSize += s.LastRunSummarySize
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	for line := range request.ConsoleLines.FirstRunValues() {
		approxSize += len(line)
		if approxSize >= s.MaxRequestSizeBytes {
			return true
		}
	}

	return false
}

// Pop extracts a chunk of data from the request, limiting its JSON
// representation to approximately the maximum size.
//
// The second return value is true if there remains unsent data in the request.
func (s *FileStreamState) Pop(
	request *FileStreamRequest,
	logger *observability.CoreLogger,
	printer *observability.Printer,
) (*FileStreamRequestJSON, bool) {
	builder := &requestJSONBuilder{}
	builder.MaxSizeBytes = s.MaxRequestSizeBytes

	s.popHistory(builder, request)
	s.popEvents(builder, request)
	s.popSummary(builder, request, logger, printer)
	s.popConsoleLines(builder, request)

	s.popUploadedFiles(builder, request)
	s.popPreempting(builder, request)

	if !builder.HasMore && request.Complete {
		builder.Complete = true
		builder.ExitCode = request.ExitCode
	}

	return builder.Build(), builder.HasMore
}

func (s *FileStreamState) popHistory(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	poppedLines := false
	defer func() {
		if poppedLines {
			// Free unused memory.
			request.HistoryLines = slices.Clone(request.HistoryLines)
		}
	}()

	builder.HistoryChunk.Offset = s.HistoryLineNum

	for len(request.HistoryLines) > 0 {
		line := request.HistoryLines[0]

		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		poppedLines = true
		builder.HistoryChunk.Content = append(builder.HistoryChunk.Content, line)
		request.HistoryLines = request.HistoryLines[1:]
		s.HistoryLineNum++
	}
}

func (s *FileStreamState) popEvents(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	poppedLines := false
	defer func() {
		if poppedLines {
			// Free unused memory.
			request.EventsLines = slices.Clone(request.EventsLines)
		}
	}()

	builder.EventsChunk.Offset = s.EventsLineNum

	for len(request.EventsLines) > 0 {
		line := request.EventsLines[0]

		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		poppedLines = true
		builder.EventsChunk.Content = append(builder.EventsChunk.Content, line)
		request.EventsLines = request.EventsLines[1:]
		s.EventsLineNum++
	}
}

func (s *FileStreamState) popSummary(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
	logger *observability.CoreLogger,
	printer *observability.Printer,
) {
	acceptDelta := s.AcceptSummaryDelta != nil && s.AcceptSummaryDelta()
	if !acceptDelta {
		s.summaryDelta = nil
	}

	if !request.SummaryUpdates.IsEmpty() {
		if s.RunSummary == nil {
			s.RunSummary = runsummary.New()
		}

		err := request.SummaryUpdates.Apply(s.RunSummary)

		if err != nil {
			// A partial success is possible, so we log and continue.
			logger.CaptureError(
				"filestream",
				fmt.Errorf("filestream: error applying summary updates: %v", err),
			)
		}

		if s.summaryDelta != nil {
			s.summaryDelta.Merge(request.SummaryUpdates)
		}
		request.SummaryUpdates = nil

		// A delta cannot express a removal.
		s.serializeSummary(logger,
			s.summaryDelta != nil && !s.summaryDelta.HasRemovals())
	}

	// Send the full summary instead of a delta the backend no longer
	// accepts, and on the final request.
	if (s.unsentSummaryIsDelta && !acceptDelta) ||
		(request.Complete && (s.unsentSummaryIsDelta || s.deltaSinceFull)) {
		s.serializeSummary(logger, false)
	}

	if s.UnsentSummary == "" {
		return
	}

	if len(s.UnsentSummary) > s.MaxFileLineSize {
		logger.Warn(
			"filestream: run summary line too long, skipping",
			"len", len(s.UnsentSummary),
			"max", s.MaxFileLineSize,
		)
		printer.
			AtMostEvery(time.Minute).
			Warnf(
				"Skipped uploading summary data that exceeded"+
					" size limit (%d > %d bytes).",
				len(s.UnsentSummary),
				s.MaxFileLineSize,
			)

		// Clear the unsent value; we will not attempt to send it unless
		// it is modified, in which case it'll be serialized again.
		s.clearUnsentSummary(acceptDelta)
		return
	}

	if !builder.TryAddSize(len(s.UnsentSummary)) {
		builder.HasMore = true
		return
	}

	builder.SummaryChunk.Offset = s.SummaryLineNum
	builder.SummaryChunk.Content = []string{s.UnsentSummary}
	builder.SummaryDelta = s.unsentSummaryIsDelta
	s.clearUnsentSummary(acceptDelta)
}

// serializeSummary sets UnsentSummary to summaryDelta or to the full summary.
func (s *FileStreamState) serializeSummary(
	logger *observability.CoreLogger,
	asDelta bool,
) {
	serialize := s.RunSummary.Serialize
	if asDelta {
		serialize = s.summaryDelta.Serialize
	}

	summaryJSON, err := serialize()
	if err != nil {
		// On error, we don't modify UnsentSummary so that we still upload
		// a previous successfully-serialized value.
		logger.CaptureError(
			"filestream",
			fmt.Errorf("filestream: failed to serialize summary: %v", err),
		)
		return
	}

	// An empty delta has nothing to send.
	if asDelta && string(summaryJSON) == "{}" {
		s.UnsentSummary = ""
		s.unsentSummaryIsDelta = false
		return
	}

	s.UnsentSummary = string(summaryJSON)
	s.unsentSummaryIsDelta = asDelta
	s.LastRunSummarySize = len(summaryJSON)
	if !asDelta {
		s.deltaSinceFull = false
	}
}

// clearUnsentSummary marks UnsentSummary as sent or dropped.
func (s *FileStreamState) clearUnsentSummary(acceptDelta bool) {
	if s.unsentSummaryIsDelta {
		s.deltaSinceFull = true
	}

	s.summaryDelta = nil
	if acceptDelta {
		s.summaryDelta = runsummary.NoUpdates()
	}

	s.UnsentSummary = ""
	s.unsentSummaryIsDelta = false
}

func (s *FileStreamState) popConsoleLines(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.ConsoleLinesChunk.Offset =
		s.ConsoleLineOffset + request.ConsoleLines.FirstIndex()

	for idx, line := range request.ConsoleLines.FirstRun() {
		if !builder.TryAddSize(len(line)) {
			builder.HasMore = true
			return
		}

		builder.ConsoleLinesChunk.Content = append(
			builder.ConsoleLinesChunk.Content,
			line,
		)
		request.ConsoleLines.Delete(idx)
	}

	// We can only upload one consecutive run of console lines at a time.
	if request.ConsoleLines.Len() > 0 {
		builder.HasMore = true
	}
}

func (s *FileStreamState) popUploadedFiles(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.Uploaded = slices.Collect(maps.Keys(request.UploadedFiles))
	request.UploadedFiles = nil
}

func (s *FileStreamState) popPreempting(
	builder *requestJSONBuilder,
	request *FileStreamRequest,
) {
	builder.Preempting = request.Preempting
	request.Preempting = false
}

// requestJSONBuilder builds a [FileStreamRequestJSON].
type requestJSONBuilder struct {
	ApproxSizeBytes, MaxSizeBytes int
	HasMore                       bool

	HistoryChunk      OffsetAndContent
	EventsChunk       OffsetAndContent
	SummaryChunk      OffsetAndContent
	ConsoleLinesChunk OffsetAndContent

	Uploaded     []string
	Preempting   bool
	SummaryDelta bool

	Complete bool
	ExitCode int32 // only sent if Complete
}

// TryAddSize returns whether n more bytes can be added to the request
// and updates the request size if so.
func (b *requestJSONBuilder) TryAddSize(n int) bool {
	newSize := b.ApproxSizeBytes + n

	if b.ApproxSizeBytes == 0 || newSize <= b.MaxSizeBytes {
		b.ApproxSizeBytes = newSize
		return true
	} else {
		return false
	}
}

// Build returns the JSON value to upload.
func (x *requestJSONBuilder) Build() *FileStreamRequestJSON {
	json := &FileStreamRequestJSON{}
	json.Files = make(map[string]OffsetAndContent)

	if len(x.HistoryChunk.Content) > 0 {
		json.Files[HistoryFileName] = x.HistoryChunk
	}
	if len(x.EventsChunk.Content) > 0 {
		json.Files[EventsFileName] = x.EventsChunk
	}
	if len(x.SummaryChunk.Content) > 0 {
		json.Files[SummaryFileName] = x.SummaryChunk
		json.SummaryDelta = nullify.NilIfZero(x.SummaryDelta)
	}
	if len(x.ConsoleLinesChunk.Content) > 0 {
		json.Files[OutputFileName] = x.ConsoleLinesChunk
	}

	json.Uploaded = x.Uploaded
	json.Preempting = nullify.NilIfZero(x.Preempting)

	if x.Complete {
		complete := x.Complete
		json.Complete = &complete

		exitCode := x.ExitCode
		json.ExitCode = &exitCode
	}

	return json
}
