//go:build cloud_http

package filetransfer

import (
	"compress/gzip"
	"context"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"slices"
	"strconv"
	"strings"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"

	"github.com/wandb/wandb/core/internal/observability"
)

// azureReadBucket retains gocloud's environment configuration and key mapping.
// Artifact references use literal object names and do not use this mapping.
type azureReadBucket struct {
	client *azureAccountHTTPClient
	bucket string
}

func newAzureReadBucket(
	ctx context.Context,
	bucket string,
	_ *observability.CoreLogger,
) (CloudReadBucket, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	configuration, err := azureReadConfigFromEnv(os.Getenv)
	if err != nil {
		return nil, err
	}
	var credential azcore.TokenCredential
	options := &azcore.ClientOptions{}
	switch configuration.auth {
	case azureReadSharedKey:
		signer, err := newAzureSharedKeyPolicy(configuration.account, configuration.key)
		if err != nil {
			return nil, err
		}
		options.PerRetryPolicies = []policy.Policy{signer}
	case azureReadDefaultCredential:
		credential, err = azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			return nil, fmt.Errorf("create Azure credentials: %w", err)
		}
	}
	client, err := newAzureAccountHTTPClient(configuration.endpoint, credential, options)
	if err != nil {
		return nil, err
	}
	return &azureReadBucket{client: client, bucket: bucket}, nil
}

func (b *azureReadBucket) ListPage(
	ctx context.Context,
	prefix, token string,
) (CloudObjectPage, error) {
	page, err := b.client.ListBlobs(ctx, b.bucket, azureCloudEscapeKey(prefix, true), token, false)
	if err != nil {
		return CloudObjectPage{}, err
	}
	if page.NextMarker != "" && page.NextMarker == token {
		return CloudObjectPage{}, fmt.Errorf("azure blob listing repeated its continuation token")
	}
	result := CloudObjectPage{Keys: make([]string, 0, len(page.Items)), NextToken: page.NextMarker}
	for _, item := range page.Items {
		result.Keys = append(result.Keys, azureCloudUnescapeKey(item.Name))
	}
	slices.Sort(result.Keys)
	return result, nil
}

// Each call observes the latest blob; neither a size nor an ETag is cached
// across opens, since TensorBoard event files can grow after reaching EOF.
func (b *azureReadBucket) NewRangeReader(
	ctx context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	if offset < 0 {
		return nil, fmt.Errorf("azure read offset must be non-negative")
	}
	u := azureObjectURL(b.client.endpoint, b.bucket, azureCloudEscapeKey(key, false))
	headers := http.Header{"Accept-Encoding": {"identity"}}
	if offset > 0 {
		properties, err := b.readProperties(ctx, u)
		if err != nil {
			return nil, err
		}
		if properties.gzip {
			return b.readFullRange(ctx, u, offset)
		}
		if properties.size >= 0 && offset >= properties.size {
			return http.NoBody, nil
		}
		headers.Set("Range", fmt.Sprintf("bytes=%d-", offset))
	}
	response, err := b.client.http.do(ctx, http.MethodGet, u, headers, nil)
	if err != nil {
		return b.readRangeError(ctx, u, err, offset)
	}
	if offset == 0 {
		return azureReadFullResponse(response, 0)
	}
	if azureResponseIsGzip(response) {
		// The blob may have changed encoding since HEAD. A byte range into a
		// gzip stream cannot be decoded; reopen the complete current version.
		response.Body.Close()
		return b.readFullRange(ctx, u, offset)
	}
	length, err := azureReadResponseLength(response, offset)
	if err != nil {
		response.Body.Close()
		return nil, err
	}
	if length < 0 {
		return response.Body, nil
	}
	return &azureRangeReader{ReadCloser: response.Body, remaining: length}, nil
}

type azureReadProperties struct {
	size int64
	gzip bool
}

func (b *azureReadBucket) readProperties(
	ctx context.Context,
	u *url.URL,
) (azureReadProperties, error) {
	response, err := b.client.http.do(
		ctx,
		http.MethodHead,
		u,
		http.Header{"Accept-Encoding": {"identity"}},
		nil,
	)
	if err != nil {
		return azureReadProperties{}, err
	}
	response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return azureReadProperties{}, fmt.Errorf("azure returned invalid blob properties")
	}
	return azureReadProperties{
		size: response.ContentLength,
		gzip: azureResponseIsGzip(response),
	}, nil
}

func azureResponseIsGzip(response *http.Response) bool {
	return strings.EqualFold(strings.TrimSpace(response.Header.Get("Content-Encoding")), "gzip")
}

func (b *azureReadBucket) readFullRange(
	ctx context.Context,
	u *url.URL,
	offset int64,
) (io.ReadCloser, error) {
	response, err := b.client.http.do(
		ctx,
		http.MethodGet,
		u,
		http.Header{"Accept-Encoding": {"identity"}},
		nil,
	)
	if err != nil {
		return nil, err
	}
	return azureReadFullResponse(response, offset)
}

func azureReadFullResponse(response *http.Response, offset int64) (io.ReadCloser, error) {
	length, err := azureReadResponseLength(response, 0)
	if err != nil {
		response.Body.Close()
		return nil, err
	}
	reader := response.Body
	if length >= 0 {
		reader = &azureRangeReader{ReadCloser: reader, remaining: length}
	}
	if azureResponseIsGzip(response) {
		decoded, err := gzip.NewReader(reader)
		if err != nil {
			reader.Close()
			return nil, fmt.Errorf("decode Azure gzip blob: %w", err)
		}
		reader = &azureGzipReader{Reader: decoded, body: reader}
	}
	if offset > 0 {
		if _, err := io.CopyN(io.Discard, reader, offset); err != nil {
			reader.Close()
			if errors.Is(err, io.EOF) {
				return http.NoBody, nil
			}
			return nil, fmt.Errorf("seek Azure blob: %w", err)
		}
	}
	return reader, nil
}

type azureGzipReader struct {
	*gzip.Reader
	body io.Closer
}

func (r *azureGzipReader) Close() error {
	return errors.Join(r.Reader.Close(), r.body.Close())
}

func (b *azureReadBucket) readRangeError(
	ctx context.Context,
	u *url.URL,
	err error,
	offset int64,
) (io.ReadCloser, error) {
	var responseError *azureHTTPError
	if !errors.As(err, &responseError) ||
		responseError.status != http.StatusRequestedRangeNotSatisfiable ||
		offset <= 0 {
		return nil, err
	}
	// Azure doesn't always return Content-Range on 416. Recheck the current
	// properties in case the object shrank or changed encoding after HEAD.
	properties, propertiesErr := b.readProperties(ctx, u)
	if propertiesErr != nil {
		return nil, propertiesErr
	}
	if properties.gzip {
		return b.readFullRange(ctx, u, offset)
	}
	value, ok := strings.CutPrefix(responseError.header.Get("Content-Range"), "bytes */")
	if ok {
		length, parseErr := strconv.ParseInt(value, 10, 64)
		if parseErr == nil && length >= 0 && offset >= length {
			return http.NoBody, nil
		}
	}
	if properties.size >= 0 && offset >= properties.size {
		return http.NoBody, nil
	}
	return nil, err
}

func azureReadResponseLength(response *http.Response, offset int64) (int64, error) {
	if offset == 0 {
		if response.StatusCode != http.StatusOK {
			return 0, fmt.Errorf("azure returned a partial response to a full-blob request")
		}
		return response.ContentLength, nil
	}
	if response.StatusCode != http.StatusPartialContent {
		return 0, fmt.Errorf("azure ignored the requested byte range")
	}
	length, err := azureReadRangeLength(response.Header.Get("Content-Range"), offset)
	if err != nil {
		return 0, err
	}
	if response.ContentLength >= 0 && response.ContentLength != length {
		return 0, fmt.Errorf("azure range Content-Length does not match Content-Range")
	}
	return length, nil
}

func azureReadRangeLength(value string, offset int64) (int64, error) {
	invalid := fmt.Errorf("azure returned an invalid Content-Range")
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

type azureRangeReader struct {
	io.ReadCloser
	remaining int64
}

func (r *azureRangeReader) Read(buffer []byte) (int, error) {
	if len(buffer) == 0 {
		return 0, nil
	}
	if r.remaining == 0 {
		return 0, io.EOF
	}
	if int64(len(buffer)) > r.remaining {
		buffer = buffer[:r.remaining]
	}
	n, err := r.ReadCloser.Read(buffer)
	r.remaining -= int64(n)
	if errors.Is(err, io.EOF) && r.remaining > 0 {
		err = io.ErrUnexpectedEOF
	}
	return n, err
}

func azureCloudEscapeKey(key string, isPrefix bool) string {
	var result strings.Builder
	runes := []rune(key)
	for i, r := range runes {
		special := r == '\\' || r < 32 || r == '"' || r == '#' || r == '%' || r == '?' || r == 127
		// Retain the legacy driver's byte-length check for trailing slashes,
		// including its behavior when the key contains multibyte characters.
		trailingSlash := !isPrefix && i == len(key)-1 && r == '/'
		parentSlash := i > 1 && r == '/' && runes[i-1] == '.' && runes[i-2] == '.'
		if special || trailingSlash || parentSlash {
			fmt.Fprintf(&result, "__%#x__", r)
		} else {
			result.WriteRune(r)
		}
	}
	return result.String()
}

func azureCloudUnescapeKey(key string) string {
	var result strings.Builder
	for key != "" {
		start := strings.Index(key, "__0x")
		if start < 0 {
			result.WriteString(key)
			break
		}
		result.WriteString(key[:start])
		key = key[start:]
		if end := strings.Index(key[4:], "__"); end >= 0 {
			value, err := strconv.ParseInt(key[4:4+end], 16, 32)
			if err == nil {
				result.WriteRune(rune(value))
				key = key[end+6:]
				continue
			}
		}
		result.WriteString(key[:4])
		key = key[4:]
	}
	return result.String()
}
