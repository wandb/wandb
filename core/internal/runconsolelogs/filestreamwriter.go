package runconsolelogs

import (
	"time"

	"golang.org/x/time/rate"

	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/sparselist"
)

// filestreamWriter sends modified console log lines to the filestream.
type filestreamWriter struct {
	debouncer  *debouncedWriter
	FileStream filestream.FileStream

	// Structured reports whether to use the structured (JSON) line format.
	//
	// It is a function so the underlying server feature check is
	// evaluated lazily here, off the hot path that creates the writer.
	//
	// If false, the legacy plain text format is used:
	//
	// ERROR 2023-04-05T10:15:30.000000 [node-1-rank-0] Critical error occurred
	//
	// If true, then the JSON format is used:
	//
	//  {
	//    "level":"error",
	//    "ts":"2023-04-05T10:15:30.000000",
	//    "label":"node-1-rank-0",
	//    "content":"Division by zero",
	//  }
	Structured func() bool
}

func NewFileStreamWriter(
	structured func() bool,
	fileStream filestream.FileStream,
) *filestreamWriter {
	if structured == nil {
		// Default to the legacy format.
		structured = func() bool { return false }
	}

	w := &filestreamWriter{
		FileStream: fileStream,
		Structured: structured,
	}

	w.debouncer = NewDebouncedWriter(
		// This short delay prevents every single character change from
		// triggering a relatively expensive merging logic.
		rate.NewLimiter(rate.Every(10*time.Millisecond), 1),
		w.sendBatch,
	)

	return w
}

// UpdateLine sends a console logs update through FileStream.
func (w *filestreamWriter) UpdateLine(lineNum int, line *RunLogsLine) {
	w.debouncer.OnChanged(lineNum, line)
}

func (w *filestreamWriter) sendBatch(
	lines *sparselist.SparseList[*RunLogsLine],
) {
	w.FileStream.StreamUpdate(&filestream.LogsUpdate{
		Lines: sparselist.Map(lines, func(line *RunLogsLine) string {
			if w.Structured() {
				if s, err := line.StructuredFormat(); err == nil {
					return s
				} else {
					return line.LegacyFormat()
				}
			}

			return line.LegacyFormat()
		}),
	})
}

// Finish flushes all accumulated updates.
func (w *filestreamWriter) Finish() {
	w.debouncer.Finish()
}
