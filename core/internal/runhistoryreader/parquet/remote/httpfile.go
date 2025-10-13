package remote

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"

	"github.com/apache/arrow-go/v18/parquet"
)

// getObjectSize gets the size of an object at the given URL.
//
// getObjectSize makes an HTTP HEAD request to the given URL.
// If the response is successful, it returns the Content-Length header value.
// If any error occurs, or if a error status code is returned (>=400),
// it returns -1, and the error that occurred or the status code.
func getObjectSize(
	ctx context.Context,
	client *http.Client,
	url string,
) (int64, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodHead, url, nil)
	if err != nil {
		return -1, err
	}

	resp, err := client.Do(req)
	if err != nil {
		return -1, err
	}
	if resp.StatusCode >= http.StatusBadRequest {
		return -1, fmt.Errorf(
			"failed to get object size with status code: %d",
			resp.StatusCode,
		)
	}
	defer resp.Body.Close()

	return resp.ContentLength, nil
}

type HttpFileReader struct {
	ctx context.Context

	client   *http.Client
	fileSize int64
	offset   int64
	url      string
}

var _ parquet.ReaderAtSeeker = &HttpFileReader{}

func NewHttpFileReader(
	ctx context.Context,
	client *http.Client,
	url string,
) (parquet.ReaderAtSeeker, error) {
	fileSize, err := getObjectSize(ctx, client, url)
	if err != nil {
		return nil, err
	}

	return &HttpFileReader{
		ctx: ctx,

		client:   client,
		fileSize: fileSize,
		offset:   0,
		url:      url,
	}, nil
}

// ReadAt implements io.ReaderAt.ReadAt
//
// ReadAt reads up to len(p) bytes from object at o.url
// starting from the offset 'off'.
//
// ReadAt returns the number of bytes read and an error.
// If the number of bytes read is less than the length of the buffer,
// the error is io.ErrUnexpectedEOF.
func (o *HttpFileReader) ReadAt(p []byte, off int64) (int, error) {
	if off < 0 {
		return 0, errors.New("negative offset")
	}

	// calculate range to read for request
	start := off
	end := min(off+int64(len(p)), o.fileSize)

	req, err := http.NewRequestWithContext(o.ctx, http.MethodGet, o.url, nil)
	if err != nil {
		return 0, err
	}
	// set range header to read only specified bytes from file
	req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end))

	resp, err := o.client.Do(req)
	if err != nil {
		return 0, err
	}
	if resp.StatusCode >= http.StatusBadRequest {
		return 0, fmt.Errorf(
			"failed to read with status code: %d",
			resp.StatusCode,
		)
	}
	defer resp.Body.Close()

	wantedBytes := end - start
	n, err := io.ReadAtLeast(resp.Body, p, int(wantedBytes))
	if int64(n) == wantedBytes && n < len(p) {
		err = io.EOF
	}

	o.offset += int64(n)
	return n, err
}

// Seek implements io.Seeker.Seek
func (o *HttpFileReader) Seek(offset int64, whence int) (int64, error) {
	switch whence {
	case io.SeekStart:
		if err := o.validateOffset(offset); err != nil {
			return -1, err
		}
		o.offset = offset
	case io.SeekCurrent:
		newOffset := o.offset + offset
		if err := o.validateOffset(newOffset); err != nil {
			return -1, err
		}
		o.offset = newOffset
	case io.SeekEnd:
		newOffset := o.fileSize + offset
		if err := o.validateOffset(newOffset); err != nil {
			return -1, err
		}
		o.offset = newOffset
	default:
		return 0, fmt.Errorf("invalid whence: %d", whence)
	}
	return o.offset, nil
}

func (o *HttpFileReader) validateOffset(offset int64) error {
	if offset < 0 {
		return errors.New("offset start before file")
	}
	if offset > o.fileSize {
		return errors.New("offset exceeds file size")
	}
	return nil
}
