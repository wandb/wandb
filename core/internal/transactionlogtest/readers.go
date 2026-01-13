package transactionlogtest

import (
	"errors"
	"io"
)

// ToggleableReadSeeker wraps an io.ReadSeeker to return errors when toggled.
type ToggleableReadSeeker struct {
	r       io.ReadSeeker
	readErr error
	seekErr error
}

func NewToggleableReadSeeker(r io.ReadSeeker) *ToggleableReadSeeker {
	return &ToggleableReadSeeker{r, nil, nil}
}

// SetError sets or clears the error for both Read and Seek.
func (rs *ToggleableReadSeeker) SetError(err error) {
	rs.readErr = err
	rs.seekErr = err
}

// SetSeekError sets or clears just the error for Seek.
func (rs *ToggleableReadSeeker) SetSeekError(err error) {
	rs.seekErr = err
}

// Read implements io.Reader.Read.
func (rs *ToggleableReadSeeker) Read(p []byte) (int, error) {
	if rs.readErr != nil {
		return 0, rs.readErr
	} else {
		return rs.r.Read(p)
	}
}

// Seek implements io.Seeker.Seek.
func (rs *ToggleableReadSeeker) Seek(offset int64, whence int) (int64, error) {
	if rs.seekErr != nil {
		return 0, rs.seekErr
	} else {
		return rs.r.Seek(offset, whence)
	}
}

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
