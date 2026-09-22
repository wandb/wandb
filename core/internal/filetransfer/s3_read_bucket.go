//go:build cloud_http

package filetransfer

import (
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net/http"
	"slices"
	"strconv"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/ratelimit"
	awsretry "github.com/aws/aws-sdk-go-v2/aws/retry"
	"github.com/aws/aws-sdk-go-v2/config"

	"github.com/wandb/wandb/core/internal/observability"
)

// s3ReadBucket retains the key mapping used by gocloud's S3 driver. Artifact
// references use raw S3 keys instead, so the mapping belongs in this adapter.
type s3ReadBucket struct {
	client *s3HTTPClient
	bucket string
}

func newS3ReadBucket(
	ctx context.Context,
	bucket string,
	_ *observability.CoreLogger,
) (CloudReadBucket, error) {
	// Bare s3:// URLs in gocloud use the default AWS configuration and a standard
	// retryer without its token limiter. TensorBoard never forwards URL options.
	cfg, err := config.LoadDefaultConfig(ctx, config.WithRetryer(func() aws.Retryer {
		return awsretry.NewStandard(
			func(options *awsretry.StandardOptions) { options.RateLimiter = ratelimit.None },
		)
	}))
	if err != nil {
		return nil, fmt.Errorf("load S3 read-bucket configuration: %w", err)
	}
	client, err := newS3HTTPClient(ctx, &cfg)
	if err != nil {
		return nil, err
	}
	if _, err := client.objectURL(S3Object{Bucket: bucket}, nil); err != nil {
		return nil, err
	}
	return &s3ReadBucket{client: client, bucket: bucket}, nil
}

func (b *s3ReadBucket) ListPage(
	ctx context.Context,
	prefix, token string,
) (CloudObjectPage, error) {
	page, err := b.client.ListObjects(ctx, b.bucket, s3CloudEscapeKey(prefix), token)
	if err != nil {
		return CloudObjectPage{}, err
	}
	result := CloudObjectPage{Keys: make([]string, 0, len(page.Keys))}
	for _, key := range page.Keys {
		result.Keys = append(result.Keys, s3CloudUnescapeKey(key))
	}
	slices.Sort(result.Keys)
	if page.Truncated {
		if page.NextToken == "" || page.NextToken == token {
			return CloudObjectPage{}, fmt.Errorf(
				"S3 returned a truncated page without a new continuation token",
			)
		}
		result.NextToken = page.NextToken
	}
	return result, nil
}

// NewRangeReader opens the latest object each time. In particular, reaching EOF
// does not pin a version or size, allowing a later call to see an appended log.
func (b *s3ReadBucket) NewRangeReader(
	ctx context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	if offset < 0 {
		return nil, fmt.Errorf("S3 read offset must be non-negative")
	}
	headers := http.Header{"Accept-Encoding": {"identity"}}
	if offset > 0 {
		headers.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	} else if b.client.validateChecksums {
		headers.Set("X-Amz-Checksum-Mode", "ENABLED")
	}
	response, err := b.client.getResponse(
		ctx,
		S3Object{Bucket: b.bucket, Key: s3CloudEscapeKey(key)},
		nil,
		headers,
	)
	if err != nil {
		return nil, err
	}
	if response.StatusCode == http.StatusRequestedRangeNotSatisfiable {
		defer response.Body.Close()
		return s3ReadRangeEOF(response, offset)
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		return nil, cloudResponseError(response)
	}
	reader, err := b.responseReader(response, offset)
	if err != nil {
		response.Body.Close()
		return nil, err
	}
	return reader, nil
}

func (b *s3ReadBucket) responseReader(
	response *http.Response,
	offset int64,
) (io.ReadCloser, error) {
	if offset == 0 {
		if response.StatusCode != http.StatusOK {
			return nil, fmt.Errorf("S3 returned a partial response to a full-object request")
		}
		if b.client.validateChecksums {
			return s3CheckedBody(response)
		}
		return response.Body, nil
	}
	if response.StatusCode != http.StatusPartialContent {
		return nil, fmt.Errorf("S3 ignored the requested byte range")
	}
	length, err := s3ReadRangeLength(response.Header.Get("Content-Range"), offset)
	if err != nil {
		return nil, err
	}
	if response.ContentLength >= 0 && response.ContentLength != length {
		return nil, fmt.Errorf("S3 range Content-Length does not match Content-Range")
	}
	// A partial response must not be compared against a full-object checksum.
	return &s3RangeReader{ReadCloser: response.Body, remaining: length}, nil
}

func s3ReadRangeLength(value string, offset int64) (int64, error) {
	invalid := fmt.Errorf("S3 returned an invalid Content-Range")
	text, ok := strings.CutPrefix(value, "bytes ")
	if !ok {
		return 0, invalid
	}
	bounds, totalText, ok := strings.Cut(text, "/")
	if !ok {
		return 0, invalid
	}
	startText, endText, ok := strings.Cut(bounds, "-")
	if !ok {
		return 0, invalid
	}
	start, err := strconv.ParseInt(startText, 10, 64)
	if err != nil || start != offset {
		return 0, invalid
	}
	end, err := strconv.ParseInt(endText, 10, 64)
	if err != nil || end < start {
		return 0, invalid
	}
	total, err := strconv.ParseInt(totalText, 10, 64)
	if err != nil || total <= end || end != total-1 {
		return 0, invalid
	}
	return end - start + 1, nil
}

func s3ReadRangeEOF(response *http.Response, offset int64) (io.ReadCloser, error) {
	if offset <= 0 {
		return nil, fmt.Errorf("S3 rejected a full-object request as an invalid range")
	}
	if totalText, ok := strings.CutPrefix(response.Header.Get("Content-Range"), "bytes */"); ok {
		total, err := strconv.ParseInt(totalText, 10, 64)
		if err == nil && total >= 0 && offset >= total {
			return http.NoBody, nil
		}
		return nil, fmt.Errorf("S3 rejected a byte range before the end of the object")
	}
	// S3 reports ActualObjectSize in its XML InvalidRange error; S3-compatible
	// servers commonly use the Content-Range header above instead.
	var detail struct {
		Code string `xml:"Code"`
		Size *int64 `xml:"ActualObjectSize"`
	}
	if err := xml.NewDecoder(io.LimitReader(response.Body, 4096)).Decode(&detail); err != nil {
		return nil, fmt.Errorf("decode S3 range error: %w", err)
	}
	if detail.Code != "InvalidRange" || detail.Size == nil || *detail.Size < 0 ||
		offset < *detail.Size {
		return nil, fmt.Errorf("S3 returned an invalid range error")
	}
	return http.NoBody, nil
}

type s3RangeReader struct {
	io.ReadCloser
	remaining int64
}

func (r *s3RangeReader) Read(buffer []byte) (int, error) {
	if r.remaining == 0 {
		return 0, io.EOF
	}
	if int64(len(buffer)) > r.remaining {
		buffer = buffer[:r.remaining]
	}
	n, err := r.ReadCloser.Read(buffer)
	r.remaining -= int64(n)
	if err == io.EOF && r.remaining > 0 {
		err = io.ErrUnexpectedEOF
	}
	return n, err
}

// gocloud's S3 key encoding predates URL encoding: control characters and the
// slash in "../" become __0xN__. Keep it for existing TensorBoard objects.
func s3CloudEscapeKey(key string) string {
	runes := []rune(key)
	needsEscape := false
	for i, char := range runes {
		if char < 32 || (i > 1 && char == '/' && runes[i-1] == '.' && runes[i-2] == '.') {
			needsEscape = true
			break
		}
	}
	if !needsEscape {
		return key
	}
	var result strings.Builder
	for i, char := range runes {
		if char < 32 || (i > 1 && char == '/' && runes[i-1] == '.' && runes[i-2] == '.') {
			fmt.Fprintf(&result, "__%#x__", char)
		} else {
			result.WriteRune(char)
		}
	}
	return result.String()
}

func s3CloudUnescapeKey(key string) string {
	if !strings.Contains(key, "__0x") {
		return key
	}
	runes := []rune(key)
	var result strings.Builder
	changed := false
	for i := 0; i < len(runes); i++ {
		char, last, ok := s3CloudUnescapeRune(runes, i)
		if ok {
			changed = true
			result.WriteRune(char)
			i = last
		} else {
			result.WriteRune(runes[i])
		}
	}
	if !changed {
		return key
	}
	return result.String()
}

func s3CloudUnescapeRune(runes []rune, start int) (rune, int, bool) {
	if len(runes)-start < 7 || string(runes[start:start+4]) != "__0x" {
		return 0, 0, false
	}
	end := start + 4
	for end < len(runes) && runes[end] != '_' {
		end++
	}
	if end+1 >= len(runes) || runes[end+1] != '_' {
		return 0, 0, false
	}
	value, err := strconv.ParseInt(string(runes[start+4:end]), 16, 32)
	if err != nil {
		return 0, 0, false
	}
	return rune(value), end + 1, true
}
