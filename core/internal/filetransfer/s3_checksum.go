//go:build cloud_http

package filetransfer

import (
	"bytes"
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"fmt"
	"hash"
	"hash/crc32"
	"hash/crc64"
	"io"
	"net/http"
	"strings"
)

// s3CheckedBody preserves the SDK's supported GetObject response checksums.
// Composite multipart checksums (the "-N" suffix) cannot be checked from the
// concatenated payload and are skipped, as by the SDK. MD5 and XXHASH response
// headers are also not in the vendored SDK's supported algorithm set.
func s3CheckedBody(resp *http.Response) (io.ReadCloser, error) {
	if resp.StatusCode != http.StatusOK {
		return resp.Body, nil
	}
	var checksum string
	var hasher hash.Hash
	// As in the SDK, a later supported algorithm wins if more than one is present.
	algorithms := []struct {
		name    string
		newHash func() hash.Hash
	}{
		{"crc64nvme", func() hash.Hash { return crc64.New(crc64.MakeTable(0x9a6c9329ac4bc9b5)) }},
		{"crc32", func() hash.Hash { return crc32.NewIEEE() }},
		{"crc32c", func() hash.Hash { return crc32.New(crc32.MakeTable(crc32.Castagnoli)) }},
		{"sha256", sha256.New},
		{"sha1", sha1.New},
		{"sha512", sha512.New},
	}
	for _, algorithm := range algorithms {
		if value := resp.Header.Get("x-amz-checksum-" + algorithm.name); value != "" {
			checksum = value
			hasher = algorithm.newHash()
		}
	}
	if checksum == "" || strings.Contains(checksum, "-") {
		return resp.Body, nil
	}
	expected, err := base64.StdEncoding.DecodeString(checksum)
	if err != nil || len(expected) != hasher.Size() {
		return nil, fmt.Errorf("S3 response contains an invalid checksum")
	}
	return &s3ChecksumReader{ReadCloser: resp.Body, hash: hasher, expected: expected}, nil
}

type s3ChecksumReader struct {
	io.ReadCloser
	hash     hash.Hash
	expected []byte
	finalErr error
	finished bool
}

func (r *s3ChecksumReader) Read(p []byte) (int, error) {
	if r.finished {
		return 0, r.finalErr
	}
	n, err := r.ReadCloser.Read(p)
	if n > 0 {
		_, _ = r.hash.Write(p[:n])
	}
	if err == io.EOF {
		if !bytes.Equal(r.hash.Sum(nil), r.expected) {
			err = fmt.Errorf("S3 response checksum mismatch")
		}
		r.finished = true
		r.finalErr = err
	}
	return n, err
}
