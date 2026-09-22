//go:build cloud_http

package filetransfer

import (
	"bytes"
	"compress/gzip"
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func s3TestReadBucket(t *testing.T, server *httptest.Server) *s3ReadBucket {
	t.Helper()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	client.http.retryDelay = func(int, *http.Response) time.Duration { return 0 }
	return &s3ReadBucket{client: client, bucket: "bucket"}
}

func TestS3ReadBucketDefaultConfiguration(t *testing.T) {
	dir := t.TempDir()
	for key, value := range map[string]string{
		"AWS_CONFIG_FILE":             filepath.Join(dir, "config"),
		"AWS_SHARED_CREDENTIALS_FILE": filepath.Join(dir, "credentials"),
		"AWS_PROFILE":                 "", "AWS_DEFAULT_PROFILE": "",
		"AWS_REGION": "us-west-2", "AWS_DEFAULT_REGION": "",
		"AWS_ACCESS_KEY_ID":         s3TestCredentials.AccessKeyID,
		"AWS_SECRET_ACCESS_KEY":     s3TestCredentials.SecretAccessKey,
		"AWS_SESSION_TOKEN":         s3TestCredentials.SessionToken,
		"AWS_EC2_METADATA_DISABLED": "true",
		"AWS_USE_FIPS_ENDPOINT":     "false", "AWS_USE_DUALSTACK_ENDPOINT": "false",
		"AWS_IGNORE_CONFIGURED_ENDPOINT_URLS": "false", "AWS_ENDPOINT_URL": "",
	} {
		t.Setenv(key, value)
	}
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requests++
		checkS3Signature(t, req)
		assert.Equal(t, "/bucket/events", req.URL.Path)
		fmt.Fprint(w, "events")
	}))
	defer server.Close()
	t.Setenv("AWS_ENDPOINT_URL_S3", server.URL)
	bucket, err := newS3ReadBucket(t.Context(), "bucket", nil)
	require.NoError(t, err)
	body, err := bucket.NewRangeReader(t.Context(), "events", 0)
	require.NoError(t, err)
	got, err := io.ReadAll(body)
	require.NoError(t, err)
	require.NoError(t, body.Close())
	assert.Equal(t, "events", string(got))
	assert.Equal(t, 1, requests)

	for _, invalid := range []string{"", "arn:aws:s3:us-west-2:123456789012:accesspoint/example", "logs--usw2-az1--x-s3"} {
		_, err = newS3ReadBucket(t.Context(), invalid, nil)
		require.Error(t, err)
	}
	t.Setenv("AWS_REGION", "")
	_, err = newS3ReadBucket(t.Context(), "bucket", nil)
	require.ErrorContains(t, err, "region is not configured")
	assert.Equal(t, 1, requests, "invalid configuration must fail before any request")
}

func TestS3ReadBucketListPages(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requests++
		checkS3Signature(t, req)
		assert.Equal(t, "2", req.URL.Query().Get("list-type"))
		assert.Equal(t, "url", req.URL.Query().Get("encoding-type"))
		assert.Equal(t, "logs/..__0x2f____0xa__/", req.URL.Query().Get("prefix"))
		if requests == 1 {
			assert.Empty(t, req.URL.Query().Get("continuation-token"))
			_, _ = io.WriteString(
				w,
				`<ListBucketResult><EncodingType>url</EncodingType><Contents><Key>logs/..__0x2f____0xa__/z%2B%25</Key></Contents><Contents><Key>logs/..__0x2f____0xa__/a</Key></Contents><IsTruncated>true</IsTruncated><NextContinuationToken>opaque+/=</NextContinuationToken></ListBucketResult>`,
			)
		} else {
			assert.Equal(t, "opaque+/=", req.URL.Query().Get("continuation-token"))
			_, _ = io.WriteString(
				w,
				`<ListBucketResult><EncodingType>url</EncodingType><Contents><Key>logs/..__0x2f____0xa__/%E9%9B%AA</Key></Contents></ListBucketResult>`,
			)
		}
	}))
	defer server.Close()
	bucket := s3TestReadBucket(t, server)
	page, err := bucket.ListPage(t.Context(), "logs/../\n/", "")
	require.NoError(t, err)
	assert.Equal(
		t,
		CloudObjectPage{Keys: []string{"logs/../\n/a", "logs/../\n/z+%"}, NextToken: "opaque+/="},
		page,
	)
	page, err = bucket.ListPage(t.Context(), "logs/../\n/", page.NextToken)
	require.NoError(t, err)
	assert.Equal(t, CloudObjectPage{Keys: []string{"logs/../\n/雪"}}, page)
	assert.Equal(t, 2, requests)
}

func TestS3ReadBucketListErrors(t *testing.T) {
	for _, tc := range []struct {
		name, response, token string
		status                int
	}{
		{"missing token", `<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>`, "", 200},
		{"repeated token", `<ListBucketResult><IsTruncated>true</IsTruncated><NextContinuationToken>same</NextContinuationToken></ListBucketResult>`, "same", 200},
		{"malformed XML", `<ListBucketResult>`, "", 200},
		{"forbidden", `<Error><Code>AccessDenied</Code></Error>`, "", 403},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := &s3TrackedBody{Reader: strings.NewReader(tc.response)}
			bucket := s3ReadBucket{bucket: "bucket", client: &s3HTTPClient{}}
			cfg := s3TestConfig("http://127.0.0.1:9000", nil)
			cfg.HTTPClient = s3TestDoer(func(*http.Request) (*http.Response, error) {
				return &http.Response{
					StatusCode: tc.status,
					Header:     make(http.Header),
					Body:       body,
				}, nil
			})
			var err error
			bucket.client, err = newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			_, err = bucket.ListPage(t.Context(), "", tc.token)
			require.Error(t, err)
			assert.True(t, body.closed)
		})
	}
}

func TestS3ReadBucketRangeAndGrowingObject(t *testing.T) {
	requests := 0
	content := "123456789"
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requests++
		checkS3Signature(t, req)
		assert.Equal(t, "/bucket/logs/..__0x2f____0xa__%2B%25", req.URL.EscapedPath())
		assert.Empty(t, req.URL.Query().Get("versionId"))
		assert.Empty(t, req.Header.Get("If-Match"))
		assert.Equal(t, "identity", req.Header.Get("Accept-Encoding"))
		switch requests {
		case 1:
			assert.Empty(t, req.Header.Get("Range"))
			assert.Equal(t, "ENABLED", req.Header.Get("X-Amz-Checksum-Mode"))
			w.Header().Set("X-Amz-Checksum-Crc32", "y/Q5Jg==")
			fmt.Fprint(w, content)
		case 2:
			assert.Equal(t, "bytes=3-", req.Header.Get("Range"))
			assert.Empty(t, req.Header.Get("X-Amz-Checksum-Mode"))
			w.Header().Set("Content-Range", "bytes 3-8/9")
			// This is the checksum of the whole object, not of the requested bytes.
			w.Header().Set("X-Amz-Checksum-Crc32", "y/Q5Jg==")
			w.WriteHeader(http.StatusPartialContent)
			fmt.Fprint(w, content[3:])
		case 3:
			assert.Equal(t, "bytes=9-", req.Header.Get("Range"))
			w.Header().Set("Content-Range", "bytes */9")
			w.WriteHeader(http.StatusRequestedRangeNotSatisfiable)
			fmt.Fprint(w, `<Error><Code>InvalidRange</Code></Error>`)
		case 4:
			assert.Equal(t, "bytes=9-", req.Header.Get("Range"))
			w.Header().Set("Content-Range", "bytes 9-11/12")
			w.WriteHeader(http.StatusPartialContent)
			fmt.Fprint(w, content[9:])
		}
	}))
	defer server.Close()
	bucket := s3TestReadBucket(t, server)
	for _, tc := range []struct {
		offset int64
		want   string
	}{
		{0, "123456789"}, {3, "456789"}, {9, ""}, {9, "abc"},
	} {
		if requests == 3 {
			content += "abc"
		}
		reader, err := bucket.NewRangeReader(t.Context(), "logs/../\n+%", tc.offset)
		require.NoError(t, err)
		got, err := io.ReadAll(reader)
		require.NoError(t, err)
		require.NoError(t, reader.Close())
		assert.Equal(t, tc.want, string(got))
	}
	assert.Equal(t, 4, requests)
}

func TestS3ReadBucketRangeValidation(t *testing.T) {
	for _, tc := range []struct {
		name, contentRange, body string
		status                   int
		offset, contentLength    int64
		wantEmpty, wantTruncated bool
	}{
		{name: "ignored range", status: 200, offset: 3, contentLength: 6, body: "abcdef"},
		{name: "unexpected partial", status: 206, offset: 0, contentLength: 3, contentRange: "bytes 0-2/3", body: "abc"},
		{name: "missing content range", status: 206, offset: 3, contentLength: 3, body: "def"},
		{name: "wrong start", status: 206, offset: 3, contentLength: 3, contentRange: "bytes 2-4/5", body: "cde"},
		{name: "partial end", status: 206, offset: 3, contentLength: 2, contentRange: "bytes 3-4/6", body: "de"},
		{name: "unknown total", status: 206, offset: 3, contentLength: 3, contentRange: "bytes 3-5/*", body: "def"},
		{name: "wrong length", status: 206, offset: 3, contentLength: 2, contentRange: "bytes 3-5/6", body: "de"},
		{name: "truncated stream", status: 206, offset: 3, contentLength: 3, contentRange: "bytes 3-5/6", body: "de", wantTruncated: true},
		{name: "at eof header", status: 416, offset: 3, contentRange: "bytes */3", wantEmpty: true},
		{name: "past eof header", status: 416, offset: 4, contentRange: "bytes */3", wantEmpty: true},
		{name: "empty object range", status: 416, offset: 1, contentRange: "bytes */0", wantEmpty: true},
		{name: "spurious eof header", status: 416, offset: 2, contentRange: "bytes */3"},
		{name: "malformed eof header", status: 416, offset: 3, contentRange: "bytes */oops"},
		{name: "at eof XML", status: 416, offset: 3, body: `<Error><Code>InvalidRange</Code><ActualObjectSize>3</ActualObjectSize></Error>`, wantEmpty: true},
		{name: "past eof XML", status: 416, offset: 4, body: `<Error><Code>InvalidRange</Code><ActualObjectSize>3</ActualObjectSize></Error>`, wantEmpty: true},
		{name: "spurious eof XML", status: 416, offset: 2, body: `<Error><Code>InvalidRange</Code><ActualObjectSize>3</ActualObjectSize></Error>`},
		{name: "unknown size XML", status: 416, offset: 3, body: `<Error><Code>InvalidRange</Code></Error>`},
		{name: "wrong error XML", status: 416, offset: 3, body: `<Error><Code>OtherError</Code><ActualObjectSize>3</ActualObjectSize></Error>`},
		{name: "malformed XML", status: 416, offset: 3, body: `<Error>`},
		{name: "full request cannot be invalid range", status: 416, offset: 0, contentRange: "bytes */0"},
		{name: "missing object", status: 404, offset: 3, body: `<Error><Code>NoSuchKey</Code></Error>`},
		{name: "forbidden", status: 403, offset: 3, body: `<Error><Code>AccessDenied</Code></Error>`},
		{name: "full empty object", status: 200, offset: 0, contentLength: 0, wantEmpty: true},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := &s3TrackedBody{Reader: strings.NewReader(tc.body)}
			cfg := s3TestConfig("http://127.0.0.1:9000", nil)
			cfg.HTTPClient = s3TestDoer(func(*http.Request) (*http.Response, error) {
				return &http.Response{
					StatusCode: tc.status, Header: http.Header{"Content-Range": {tc.contentRange}},
					ContentLength: tc.contentLength, Body: body,
				}, nil
			})
			client, err := newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			bucket := s3ReadBucket{client: client, bucket: "bucket"}
			reader, err := bucket.NewRangeReader(t.Context(), "key", tc.offset)
			if tc.wantEmpty || tc.wantTruncated {
				require.NoError(t, err)
				got, readErr := io.ReadAll(reader)
				if tc.wantEmpty {
					require.NoError(t, readErr)
					assert.Empty(t, got)
				} else {
					require.ErrorIs(t, readErr, io.ErrUnexpectedEOF)
					assert.Equal(t, "de", string(got))
				}
				require.NoError(t, reader.Close())
			} else {
				require.Error(t, err)
				assert.Nil(t, reader)
			}
			assert.True(t, body.closed)
		})
	}
}

func TestS3ReadBucketPreservesGzipBytes(t *testing.T) {
	var compressed bytes.Buffer
	writer := gzip.NewWriter(&compressed)
	_, err := writer.Write([]byte("TensorBoard bytes"))
	require.NoError(t, err)
	require.NoError(t, writer.Close())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		assert.Equal(t, "identity", req.Header.Get("Accept-Encoding"))
		w.Header().Set("Content-Encoding", "gzip")
		data := compressed.Bytes()
		if req.Header.Get("Range") != "" {
			assert.Equal(t, "bytes=4-", req.Header.Get("Range"))
			w.Header().Set("Content-Range", fmt.Sprintf("bytes 4-%d/%d", len(data)-1, len(data)))
			w.WriteHeader(http.StatusPartialContent)
			data = data[4:]
		}
		_, _ = w.Write(data)
	}))
	defer server.Close()
	bucket := s3TestReadBucket(t, server)
	for _, offset := range []int64{0, 4} {
		body, err := bucket.NewRangeReader(t.Context(), "key", offset)
		require.NoError(t, err)
		got, err := io.ReadAll(body)
		require.NoError(t, err)
		require.NoError(t, body.Close())
		assert.Equal(t, compressed.Bytes()[offset:], got)
	}
}

func TestS3ReadBucketCancellationAndRetries(t *testing.T) {
	requests := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requests++
		checkS3Signature(t, req)
		assert.Equal(t, "bytes=3-", req.Header.Get("Range"))
		if requests == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			return
		}
		w.Header().Set("Content-Range", "bytes 3-5/6")
		w.WriteHeader(http.StatusPartialContent)
		fmt.Fprint(w, "def")
	}))
	defer server.Close()
	bucket := s3TestReadBucket(t, server)
	body, err := bucket.NewRangeReader(t.Context(), "key", 3)
	require.NoError(t, err)
	got, err := io.ReadAll(body)
	require.NoError(t, err)
	require.NoError(t, body.Close())
	assert.Equal(t, "def", string(got))
	assert.Equal(t, 2, requests)
	_, err = bucket.NewRangeReader(t.Context(), "key", -1)
	require.ErrorContains(t, err, "non-negative")
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	_, err = bucket.NewRangeReader(ctx, "key", 3)
	require.ErrorIs(t, err, context.Canceled)
	_, err = bucket.ListPage(ctx, "", "")
	require.ErrorIs(t, err, context.Canceled)
	assert.Equal(t, 2, requests)
}

func TestS3ReadBucketCloudKeyMapping(t *testing.T) {
	for _, tc := range []struct{ key, escaped string }{
		{"plain/雪 +%?#", "plain/雪 +%?#"},
		{"../a/b../c", "..__0x2f__a/b..__0x2f__c"},
		{"..", ".."}, {".../", "...__0x2f__"},
		{"\x00\n\r\x1f\x7f", "__0x0____0xa____0xd____0x1f__\x7f"},
	} {
		assert.Equal(t, tc.escaped, s3CloudEscapeKey(tc.key))
		assert.Equal(t, tc.key, s3CloudUnescapeKey(tc.escaped))
	}
	// Match gocloud's historical behavior for names resembling its escape syntax,
	// including literal encoded characters and malformed sequences.
	for _, tc := range []struct{ key, decoded string }{
		{"__0x41__", "A"}, {"__0x2f__", "/"}, {"__0x20__", " "},
		{"__0x__", "__0x__"}, {"__0xgg__", "__0xgg__"}, {"__0x1_", "__0x1_"},
		{"\xbd__0xgg__", "\xbd__0xgg__"},
	} {
		assert.Equal(t, tc.decoded, s3CloudUnescapeKey(tc.key))
	}
}
