package transactionlogtest

import (
	"errors"
	"io"
)

// readSeekCloser combines independent io.Reader, io.Seeker and io.Closer
// instances.
type readSeekCloser struct {
	io.Reader
	io.Seeker
	io.Closer
}

// nopCloser contains a no-op Close method.
type nopCloser struct{}

func (s *nopCloser) Close() error { return nil }

// errSeeker contains a Seek method that always errors out.
type errSeeker struct {
}

// Seek implements io.Seeker.Seek.
func (s *errSeeker) Seek(offset int64, whence int) (int64, error) {
	return 0, errors.New("errSeeker")
}
