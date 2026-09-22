//go:build cloud_http

package filetransfer

import (
	"compress/gzip"
	"context"
	"encoding/base64"
	"encoding/binary"
	"errors"
	"fmt"
	"hash/crc32"
	"io"
	"net/http"
	"net/url"
	"strconv"
	"strings"
)

// gcsReader retries interrupted response bodies at a generation-pinned offset.
// It validates the checksum on the stored bytes, before any gzip decoding.
// Both memory use and the number of stream reopen attempts are bounded.
type gcsReader struct {
	ft         *GCSFileTransfer
	ctx        context.Context
	endpoint   string
	attrs      *gcsObjectAttrs
	body       io.ReadCloser
	seen       int64
	opened     bool
	reopens    int
	crc        uint32
	wantCRC    uint32
	checkCRC   bool
	transcoded bool
	compressed bool
}

type gcsGzipReader struct {
	*gzip.Reader
	raw *gcsReader
}

func (r *gcsGzipReader) Close() error {
	_ = r.Reader.Close()
	return r.raw.Close()
}

func (ft *GCSFileTransfer) openGCSReader(
	ctx context.Context,
	bucket, name string,
	attrs *gcsObjectAttrs,
) (io.ReadCloser, error) {
	return ft.openGCSRangeReader(ctx, bucket, name, attrs, 0)
}

// openGCSRangeReader starts at a stored-byte offset. Callers seeking within a
// decoded gzip stream must instead read from zero and discard decoded bytes.
func (ft *GCSFileTransfer) openGCSRangeReader(
	ctx context.Context,
	bucket, name string,
	attrs *gcsObjectAttrs,
	offset int64,
) (io.ReadCloser, error) {
	r := &gcsReader{
		ft:    ft,
		ctx:   ctx,
		attrs: attrs,
		seen:  offset,
		endpoint: ft.objectURL(
			bucket,
			name,
			url.Values{"alt": {"media"}, "generation": {attrs.Generation}},
		),
	}
	if offset == 0 && attrs.CRC32C != "" {
		checksum, err := base64.StdEncoding.DecodeString(attrs.CRC32C)
		if err != nil || len(checksum) != 4 {
			return nil, errors.New("invalid GCS CRC32C metadata")
		}
		r.wantCRC, r.checkCRC = binary.BigEndian.Uint32(checksum), true
	}
	if err := r.open(); err != nil {
		return nil, err
	}
	if r.compressed {
		gz, err := gzip.NewReader(r)
		if err != nil {
			_ = r.Close()
			return nil, err
		}
		return &gcsGzipReader{Reader: gz, raw: r}, nil
	}
	return r, nil
}

func (r *gcsReader) open() error {
	req, err := http.NewRequestWithContext(r.ctx, http.MethodGet, r.endpoint, http.NoBody)
	if err != nil {
		return err
	}
	// Request the stored representation. net/http won't transparently decode
	// with this explicit header, allowing CRC32C verification before decoding.
	req.Header.Set("Accept-Encoding", "gzip")
	if r.seen > 0 {
		req.Header.Set("Range", "bytes="+strconv.FormatInt(r.seen, 10)+"-")
	}
	resp, err := r.ft.client.Do(req)
	if err != nil {
		return err
	}
	closeWithError := func(err error) error { _ = resp.Body.Close(); return err }
	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusPartialContent {
		return cloudResponseError(resp)
	}
	if gen := resp.Header.Get("X-Goog-Generation"); gen != "" && gen != r.attrs.Generation {
		return closeWithError(
			fmt.Errorf("GCS generation changed: got %s, want %s", gen, r.attrs.Generation),
		)
	}
	if err := r.validateResponseEncoding(resp); err != nil {
		return closeWithError(err)
	}
	if err := r.validateResponseRange(resp); err != nil {
		return closeWithError(err)
	}
	if err := r.readResponseChecksum(resp); err != nil {
		return closeWithError(err)
	}
	r.body = resp.Body
	r.opened = true
	return nil
}

func (r *gcsReader) validateResponseEncoding(resp *http.Response) error {
	compressed := resp.Header.Get("Content-Encoding") == "gzip" && !resp.Uncompressed
	transcoded := resp.Uncompressed ||
		(resp.Header.Get("X-Goog-Stored-Content-Encoding") == "gzip" && !compressed)
	if !r.opened {
		r.transcoded, r.compressed = transcoded, compressed
		if transcoded {
			r.checkCRC = false
		}
	} else if transcoded != r.transcoded || compressed != r.compressed {
		return errors.New("GCS response encoding changed while resuming download")
	}
	return nil
}

func (r *gcsReader) validateResponseRange(resp *http.Response) error {
	if resp.StatusCode == http.StatusPartialContent {
		var first, last, size int64
		value := resp.Header.Get("Content-Range")
		if n, err := fmt.Sscanf(
			value,
			"bytes %d-%d/%d",
			&first,
			&last,
			&size,
		); err != nil || n != 3 || first != r.seen || last < first || last >= size ||
			(!r.transcoded && size != r.attrs.Size) {
			return fmt.Errorf("invalid GCS Content-Range %q at offset %d", value, r.seen)
		}
	} else if r.seen > 0 {
		if !r.transcoded {
			return errors.New("GCS did not honor range request")
		}
		// GCS may ignore ranges when transcoding. Skip the already delivered
		// bytes from the complete, decompressed response before continuing.
		if _, err := io.CopyN(io.Discard, resp.Body, r.seen); err != nil {
			return err
		}
	}
	return nil
}

// Some compatible endpoints only expose the checksum on the media response.
func (r *gcsReader) readResponseChecksum(resp *http.Response) error {
	if r.seen != 0 || r.checkCRC || r.transcoded {
		return nil
	}
	for _, header := range resp.Header.Values("X-Goog-Hash") {
		for _, hash := range strings.Split(header, ",") {
			if value, ok := strings.CutPrefix(strings.TrimSpace(hash), "crc32c="); ok {
				checksum, err := base64.StdEncoding.DecodeString(value)
				if err != nil || len(checksum) != 4 {
					return errors.New("invalid GCS CRC32C response header")
				}
				r.wantCRC, r.checkCRC = binary.BigEndian.Uint32(checksum), true
			}
		}
	}
	return nil
}

var gcsCRC32CTable = crc32.MakeTable(crc32.Castagnoli)

func (r *gcsReader) Read(p []byte) (int, error) {
	if err := r.ctx.Err(); err != nil {
		return 0, err
	}
	for {
		n, err := r.body.Read(p)
		r.seen += int64(n)
		if r.checkCRC {
			r.crc = crc32.Update(r.crc, gcsCRC32CTable, p[:n])
		}
		if err == io.EOF {
			if !r.transcoded && r.seen != r.attrs.Size {
				if r.seen > r.attrs.Size {
					return n, fmt.Errorf("GCS download exceeded object size %d", r.attrs.Size)
				}
				err = io.ErrUnexpectedEOF
			} else if r.checkCRC && r.crc != r.wantCRC {
				return n, fmt.Errorf("GCS CRC32C mismatch: got %08x, want %08x", r.crc, r.wantCRC)
			}
		}
		if err == nil || err == io.EOF {
			return n, err
		}
		if r.ctx.Err() != nil {
			return n, r.ctx.Err()
		}
		if r.reopens >= 4 {
			return n, fmt.Errorf("GCS download interrupted after 5 stream attempts: %w", err)
		}
		r.reopens++
		_ = r.body.Close()
		if err := r.open(); err != nil {
			return n, err
		}
		if n > 0 {
			return n, nil
		}
	}
}

func (r *gcsReader) Close() error { return r.body.Close() }
