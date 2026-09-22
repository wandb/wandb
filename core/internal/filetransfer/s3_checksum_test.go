//go:build cloud_http

package filetransfer

import (
	"crypto/sha1"
	"crypto/sha256"
	"crypto/sha512"
	"encoding/base64"
	"io"
	"net/http"
	"strings"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestS3ResponseChecksums(t *testing.T) {
	const payload = "123456789"
	sha1sum := sha1.Sum([]byte(payload))
	sha256sum := sha256.Sum256([]byte(payload))
	sha512sum := sha512.Sum512([]byte(payload))
	checksums := map[string]string{
		"crc32":     "y/Q5Jg==",
		"crc32c":    "4waSgw==",
		"crc64nvme": "rosUhgp5mIg=",
		"sha1":      base64.StdEncoding.EncodeToString(sha1sum[:]),
		"sha256":    base64.StdEncoding.EncodeToString(sha256sum[:]),
		"sha512":    base64.StdEncoding.EncodeToString(sha512sum[:]),
	}
	for algorithm, checksum := range checksums {
		t.Run(algorithm, func(t *testing.T) {
			for _, content := range []string{payload, "corrupted payload"} {
				resp := &http.Response{
					StatusCode: 200,
					Header:     make(http.Header),
					Body:       io.NopCloser(strings.NewReader(content)),
				}
				resp.Header.Set("x-amz-checksum-"+algorithm, checksum)
				body, err := s3CheckedBody(resp)
				require.NoError(t, err)
				got, err := io.ReadAll(body)
				body.Close()
				if content == payload {
					require.NoError(t, err)
					assert.Equal(t, payload, string(got))
				} else {
					require.ErrorContains(t, err, "checksum mismatch")
				}
			}
		})
	}
}

func TestS3ChecksumModes(t *testing.T) {
	for _, checksum := range []string{"abc-2", ""} {
		original := io.NopCloser(strings.NewReader("content"))
		resp := &http.Response{StatusCode: 200, Header: make(http.Header), Body: original}
		resp.Header.Set("x-amz-checksum-sha256", checksum)
		body, err := s3CheckedBody(resp)
		require.NoError(t, err)
		assert.Equal(t, original, body)
	}
	resp := &http.Response{
		StatusCode: 200,
		Header:     make(http.Header),
		Body:       io.NopCloser(strings.NewReader("content")),
	}
	resp.Header.Set("x-amz-checksum-sha256", "!invalid")
	_, err := s3CheckedBody(resp)
	require.ErrorContains(t, err, "invalid checksum")
	cfg := s3TestConfig("https://s3.example.test", nil)
	cfg.ResponseChecksumValidation = aws.ResponseChecksumValidationWhenRequired
	client, err := newS3HTTPClient(t.Context(), cfg)
	require.NoError(t, err)
	assert.False(t, client.validateChecksums)
}
