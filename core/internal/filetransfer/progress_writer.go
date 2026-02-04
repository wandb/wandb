package filetransfer

import "io"

// ProgressWriter is a writer that tracks the progress of a download.
type ProgressWriter struct {
	// destination is the writer to the destination file being downloaded.
	destination io.Writer

	// len is the length of the source file being downloaded.
	len int64

	// written is the number of bytes written to the destination file.
	written int64

	// callback is the callback to execute on progress updates.
	callback func(processed, total int64)
}

func NewProgressWriter(
	destination io.Writer,
	size int64,
	callback func(processed, total int64),
) *ProgressWriter {
	return &ProgressWriter{
		destination: destination,
		len:         size,
		callback:    callback,
	}
}

// Write implements io.Writer.Write.
func (pw *ProgressWriter) Write(p []byte) (n int, err error) {
	n, err = pw.destination.Write(p)
	pw.written += int64(n)
	if err != nil {
		return n, err
	}

	if pw.callback != nil {
		pw.callback(pw.written, pw.len)
	}

	return n, nil
}
