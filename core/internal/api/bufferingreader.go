package api

import (
	"bytes"
	"io"
)

// BufferingReader is a Reader that can reconstruct its source after reading.
type BufferingReader struct {
	source io.Reader     // the underlying reader
	buffer *bytes.Buffer // buffered data from the source
}

func NewBufferingReader(source io.Reader) *BufferingReader {
	return &BufferingReader{source: source, buffer: &bytes.Buffer{}}
}

type reconstructedReader struct {
	prefix *bytes.Buffer // the buffer to read from first
	suffix io.Reader     // the reader to read from after the buffer
}

// Read reads the source Reader.
func (r *BufferingReader) Read(p []byte) (int, error) {
	nRead, err := r.source.Read(p)

	// bytes.Buffer.Write() never returns an error.
	_, _ = r.buffer.Write(p[:nRead])

	return nRead, err
}

// Reconstruct returns a reconstruction of the original reader.
func (r *BufferingReader) Reconstruct() io.ReadCloser {
	return &reconstructedReader{prefix: r.buffer, suffix: r.source}
}

// Read first reads from the prefix buffer, then from the suffix reader.
func (r *reconstructedReader) Read(p []byte) (int, error) {
	// bytes.Buffer.Read() only returns an error if it's empty. Can ignore.
	nPrefix, _ := r.prefix.Read(p)

	if nPrefix < len(p) {
		nSuffix, err := r.suffix.Read(p[nPrefix:])
		return nPrefix + nSuffix, err
	} else {
		return nPrefix, nil
	}
}

// Close closes the suffix reader, if it's closeable.
func (r *reconstructedReader) Close() error {
	if closer, ok := r.suffix.(io.Closer); ok {
		return closer.Close()
	} else {
		return nil
	}
}
