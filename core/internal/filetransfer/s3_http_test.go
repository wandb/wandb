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
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

var s3TestCredentials = aws.Credentials{
	AccessKeyID:     "test-access-key",
	SecretAccessKey: "test-secret-key",
	SessionToken:    "test-session-token",
}

func s3TestConfig(endpoint string, client *http.Client) *aws.Config {
	return &aws.Config{
		Region:       "us-west-2",
		BaseEndpoint: aws.String(endpoint),
		HTTPClient:   client,
		Credentials: aws.CredentialsProviderFunc(
			func(context.Context) (aws.Credentials, error) { return s3TestCredentials, nil },
		),
	}
}

// Verify the request's signature independently from the outgoing request. Re-sign
// exactly the headers declared in SignedHeaders, using the timestamp on the wire.
func checkS3Signature(t *testing.T, req *http.Request) {
	t.Helper()
	actual := req.Header.Get("Authorization")
	require.Contains(t, actual, "Credential=test-access-key/")
	require.Equal(t, "test-session-token", req.Header.Get("X-Amz-Security-Token"))
	parts := strings.SplitN(actual, "SignedHeaders=", 2)
	require.Len(t, parts, 2)
	signedHeaders := strings.Split(strings.SplitN(parts[1], ",", 2)[0], ";")
	clone := req.Clone(req.Context())
	clone.URL.Scheme = "http"
	clone.URL.Host = req.Host
	clone.RequestURI = ""
	clone.Header = make(http.Header)
	for _, header := range signedHeaders {
		if header != "host" {
			clone.Header[http.CanonicalHeaderKey(header)] = req.Header.Values(header)
		}
	}
	stamp, err := time.Parse("20060102T150405Z", req.Header.Get("X-Amz-Date"))
	require.NoError(t, err)
	signer := v4.NewSigner(func(o *v4.SignerOptions) { o.DisableURIPathEscaping = true })
	require.NoError(
		t,
		signer.SignHTTP(
			req.Context(),
			s3TestCredentials,
			clone,
			req.Header.Get("X-Amz-Content-Sha256"),
			"s3",
			"us-west-2",
			stamp,
		),
	)
	require.Equal(t, actual, clone.Header.Get("Authorization"))
}

func TestS3HTTPWireOperations(t *testing.T) {
	key := "folder/a +%?#/雪//../object"
	encodedKey := s3EscapePath("/bucket/" + key)
	var requests int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		requests++
		checkS3Signature(t, req)
		q := req.URL.Query()
		switch {
		case q.Has("attributes"):
			assert.Equal(t, encodedKey, req.URL.EscapedPath())
			assert.Equal(t, "version+/=", q.Get("versionId"))
			assert.Equal(t, "ETag", req.Header.Get("X-Amz-Object-Attributes"))
			fmt.Fprint(
				w,
				`<GetObjectAttributesOutput xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><ETag>&quot;digest&quot;</ETag></GetObjectAttributesOutput>`,
			)
		case q.Has("list-type"):
			assert.Equal(t, "2", q.Get("list-type"))
			assert.Equal(t, "folder/a +", q.Get("prefix"))
			assert.Equal(t, "token+/=", q.Get("continuation-token"))
			assert.Equal(t, "url", q.Get("encoding-type"))
			fmt.Fprint(
				w,
				`<ListBucketResult><EncodingType>url</EncodingType><Contents><Key>folder/a%20%2B%25</Key></Contents><IsTruncated>true</IsTruncated><NextContinuationToken>next+/=</NextContinuationToken></ListBucketResult>`,
			)
		case q.Has("versions"):
			assert.Equal(t, "key +", q.Get("key-marker"))
			assert.Equal(t, "v+/=", q.Get("version-id-marker"))
			fmt.Fprint(
				w,
				`<ListVersionsResult><EncodingType>url</EncodingType><Version><Key>folder/a%20%2B</Key><VersionId>v2+/=</VersionId><ETag>&quot;old&quot;</ETag></Version><IsTruncated>true</IsTruncated><NextKeyMarker>folder/a%20%2B</NextKeyMarker><NextVersionIdMarker>next-version</NextVersionIdMarker></ListVersionsResult>`,
			)
		default:
			assert.Equal(t, encodedKey, req.URL.EscapedPath())
			assert.Equal(t, "version+/=", q.Get("versionId"))
			fmt.Fprint(w, "object bytes")
		}
	}))
	defer server.Close()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	object := S3Object{Bucket: "bucket", Key: key, VersionID: "version+/="}
	body, err := client.GetObject(t.Context(), object)
	require.NoError(t, err)
	content, err := io.ReadAll(body)
	require.NoError(t, err)
	require.NoError(t, body.Close())
	assert.Equal(t, "object bytes", string(content))
	etag, err := client.GetObjectETag(t.Context(), object)
	require.NoError(t, err)
	assert.Equal(t, `"digest"`, etag)
	page, err := client.ListObjects(t.Context(), "bucket", "folder/a +", "token+/=")
	require.NoError(t, err)
	assert.Equal(
		t,
		S3ObjectPage{Keys: []string{"folder/a +%"}, Truncated: true, NextToken: "next+/="},
		page,
	)
	versions, err := client.ListVersions(t.Context(), "bucket", "folder/", "key +", "v+/=")
	require.NoError(t, err)
	assert.Equal(
		t,
		S3VersionPage{
			Versions: []S3ObjectVersion{
				{Key: "folder/a +", VersionID: "v2+/=", ETag: `"old"`},
			},
			Truncated:           true,
			NextKeyMarker:       "folder/a +",
			NextVersionIDMarker: "next-version",
		},
		versions,
	)
	assert.Equal(t, 4, requests)
}

func TestS3HTTPRetriesAndErrors(t *testing.T) {
	attempts := 0
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
		attempts++
		checkS3Signature(t, req)
		if attempts == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
			fmt.Fprint(w, "retry")
			return
		}
		fmt.Fprint(w, "ok")
	}))
	defer server.Close()
	cfg := s3TestConfig(server.URL, server.Client())
	credentialsCalls := 0
	cfg.Credentials = aws.CredentialsProviderFunc(
		func(context.Context) (aws.Credentials, error) { credentialsCalls++; return s3TestCredentials, nil },
	)
	client, err := newS3HTTPClient(t.Context(), cfg)
	require.NoError(t, err)
	client.http.retryDelay = func(int, *http.Response) time.Duration { return 0 }
	body, err := client.GetObject(t.Context(), S3Object{Bucket: "bucket", Key: "key"})
	require.NoError(t, err)
	body.Close()
	assert.Equal(t, 2, attempts)
	assert.Equal(t, 2, credentialsCalls)
	ctx, cancel := context.WithCancel(t.Context())
	cancel()
	_, err = client.GetObject(ctx, S3Object{Bucket: "bucket", Key: "key"})
	require.ErrorIs(t, err, context.Canceled)
}

func TestS3HTTPHTTPErrorsAndMalformedXML(t *testing.T) {
	for _, tc := range []struct {
		name, body string
		status     int
	}{
		{"forbidden", `<Error><Code>AccessDenied</Code></Error>`, 403},
		{"missing etag", `<GetObjectAttributesOutput/>`, 200},
		{"malformed", `<GetObjectAttributesOutput><ETag>`, 200},
	} {
		t.Run(tc.name, func(t *testing.T) {
			server := httptest.NewServer(
				http.HandlerFunc(
					func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(tc.status); fmt.Fprint(w, tc.body) },
				),
			)
			defer server.Close()
			client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
			require.NoError(t, err)
			_, err = client.GetObjectETag(t.Context(), S3Object{Bucket: "bucket", Key: "key"})
			require.Error(t, err)
		})
	}
}

func TestS3HTTPEndpoints(t *testing.T) {
	tests := []struct {
		name, region, endpoint, bucket, want string
		fips, dual                           bool
	}{
		{
			name:   "regional",
			region: "us-west-2",
			bucket: "my-bucket",
			want:   "https://my-bucket.s3.us-west-2.amazonaws.com/key",
		},
		{
			name:   "east regional",
			region: "us-east-1",
			bucket: "my-bucket",
			want:   "https://my-bucket.s3.us-east-1.amazonaws.com/key",
		},
		{
			name:   "global",
			region: "aws-global",
			bucket: "my-bucket",
			want:   "https://my-bucket.s3.amazonaws.com/key",
		},
		{
			name:   "china",
			region: "cn-north-1",
			bucket: "my-bucket",
			want:   "https://my-bucket.s3.cn-north-1.amazonaws.com.cn/key",
		},
		{
			name:   "fips dualstack",
			region: "us-gov-west-1",
			bucket: "my-bucket",
			fips:   true,
			dual:   true,
			want:   "https://my-bucket.s3-fips.dualstack.us-gov-west-1.amazonaws.com/key",
		},
		{
			name:   "dotted https",
			region: "us-west-2",
			bucket: "my.bucket",
			want:   "https://s3.us-west-2.amazonaws.com/my.bucket/key",
		},
		{
			name:   "uppercase path",
			region: "us-west-2",
			bucket: "MyBucket",
			want:   "https://s3.us-west-2.amazonaws.com/MyBucket/key",
		},
		{
			name:     "custom ip path",
			region:   "us-west-2",
			endpoint: "http://127.0.0.1:9000/base",
			bucket:   "bucket",
			want:     "http://127.0.0.1:9000/base/bucket/key",
		},
		{
			name:     "custom virtual",
			region:   "us-west-2",
			endpoint: "https://objects.example.test/base",
			bucket:   "bucket",
			want:     "https://bucket.objects.example.test/base/key",
		},
		{
			name:     "dotted http",
			region:   "us-west-2",
			endpoint: "http://objects.example.test",
			bucket:   "my.bucket",
			want:     "http://my.bucket.objects.example.test/key",
		},
	}
	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			cfg := s3TestConfig(tc.endpoint, nil)
			cfg.Region = tc.region
			cfg.ConfigSources = []any{
				config.LoadOptions{
					UseFIPSEndpoint:      aws.FIPSEndpointStateDisabled,
					UseDualStackEndpoint: aws.DualStackEndpointStateDisabled,
				},
			}
			options := config.LoadOptions{}
			if tc.fips {
				options.UseFIPSEndpoint = aws.FIPSEndpointStateEnabled
			}
			if tc.dual {
				options.UseDualStackEndpoint = aws.DualStackEndpointStateEnabled
			}
			cfg.ConfigSources = []any{options}
			client, err := newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			u, err := client.objectURL(S3Object{Bucket: tc.bucket, Key: "key"}, nil)
			require.NoError(t, err)
			assert.Equal(t, tc.want, u.String())
		})
	}
}

func TestS3HTTPConfiguration(t *testing.T) {
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")
	t.Setenv("AWS_PROFILE", "")
	t.Setenv("AWS_DEFAULT_PROFILE", "")
	t.Setenv("AWS_REGION", "us-west-2")
	t.Setenv("AWS_ACCESS_KEY_ID", "test-access-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
	t.Setenv("AWS_CONFIG_FILE", filepath.Join(t.TempDir(), "config"))
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", filepath.Join(t.TempDir(), "credentials"))
	t.Setenv("AWS_ENDPOINT_URL", "http://127.0.0.1:9001")
	t.Setenv("AWS_ENDPOINT_URL_S3", "http://127.0.0.1:9002")
	cfg, err := config.LoadDefaultConfig(t.Context())
	require.NoError(t, err)
	client, err := newS3HTTPClient(t.Context(), &cfg)
	require.NoError(t, err)
	assert.Equal(t, "127.0.0.1:9002", client.endpoint.Host)
	t.Setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "true")
	cfg, err = config.LoadDefaultConfig(t.Context())
	require.NoError(t, err)
	client, err = newS3HTTPClient(t.Context(), &cfg)
	require.NoError(t, err)
	assert.Equal(t, "s3.us-west-2.amazonaws.com", client.endpoint.Host)
}

func TestS3HTTPUnsupportedBucketsFailBeforeNetwork(t *testing.T) {
	calls := 0
	server := httptest.NewServer(
		http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { calls++ }),
	)
	defer server.Close()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	for _, bucket := range []string{"arn:aws:s3:us-west-2:123:accesspoint/name", "bucket--usw2-az1--x-s3", "accesspoint.mrap", "name--ol-s3"} {
		_, err := client.GetObject(t.Context(), S3Object{Bucket: bucket, Key: "key"})
		require.ErrorContains(t, err, "does not support")
	}
	assert.Zero(t, calls)
}

func TestS3HTTPVersionPaginationAndExactKey(t *testing.T) {
	var mu sync.Mutex
	var versionPages int
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		switch {
		case q.Has("attributes"):
			fmt.Fprint(
				w,
				`<GetObjectAttributesOutput><ETag>current</ETag></GetObjectAttributesOutput>`,
			)
		case q.Has("versions"):
			mu.Lock()
			versionPages++
			mu.Unlock()
			if q.Get("version-id-marker") == "" {
				fmt.Fprint(
					w,
					`<ListVersionsResult><Version><Key>key-other</Key><ETag>target</ETag><VersionId>wrong</VersionId></Version><IsTruncated>true</IsTruncated><NextKeyMarker>key</NextKeyMarker><NextVersionIdMarker>marker+/=</NextVersionIdMarker></ListVersionsResult>`,
				)
			} else {
				assert.Equal(t, "key", q.Get("key-marker"))
				assert.Equal(t, "marker+/=", q.Get("version-id-marker"))
				fmt.Fprint(
					w,
					`<ListVersionsResult><Version><Key>key</Key><ETag>target</ETag><VersionId>correct</VersionId></Version></ListVersionsResult>`,
				)
			}
		default:
			assert.Equal(t, "correct", q.Get("versionId"))
			fmt.Fprint(w, "old-version-content")
		}
	}))
	defer server.Close()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	ft := NewS3FileTransfer(client, observabilitytest.NewTestLogger(t), NewFileTransferStats())
	path := filepath.Join(t.TempDir(), "object")
	err = ft.Download(
		&ReferenceArtifactDownloadTask{
			PathOrPrefix: path,
			Reference:    "s3://bucket/key",
			Digest:       "target",
		},
	)
	require.NoError(t, err)
	content, err := os.ReadFile(path)
	require.NoError(t, err)
	assert.Equal(t, "old-version-content", string(content))
	assert.Equal(t, 2, versionPages)
}

func TestS3HTTPPrefixPagination(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query()
		if q.Has("list-type") {
			if q.Get("continuation-token") == "" {
				fmt.Fprint(
					w,
					`<ListBucketResult><Contents><Key>prefix/a</Key></Contents><IsTruncated>true</IsTruncated><NextContinuationToken>next</NextContinuationToken></ListBucketResult>`,
				)
			} else {
				assert.Equal(t, "next", q.Get("continuation-token"))
				fmt.Fprint(
					w,
					`<ListBucketResult><Contents><Key>prefix/b</Key></Contents></ListBucketResult>`,
				)
			}
		} else {
			fmt.Fprint(w, r.URL.Path)
		}
	}))
	defer server.Close()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	ft := NewS3FileTransfer(client, observabilitytest.NewTestLogger(t), NewFileTransferStats())
	dir := t.TempDir()
	err = ft.Download(
		&ReferenceArtifactDownloadTask{
			PathOrPrefix: dir,
			Reference:    "s3://bucket/prefix/",
			Digest:       "s3://bucket/prefix/",
		},
	)
	require.NoError(t, err)
	for _, key := range []string{"a", "b"} {
		data, err := os.ReadFile(filepath.Join(dir, key))
		require.NoError(t, err)
		assert.Equal(t, "/bucket/prefix/"+key, string(data))
	}
}

// Compile-time coverage: arbitrary opaque version IDs are query parameters,
// while listing names use percent decoding that preserves literal plus signs.
func TestS3DecodeNames(t *testing.T) {
	got, err := s3DecodeName("a+b%20c", "url")
	require.NoError(t, err)
	assert.Equal(t, "a+b c", got)
	_, err = s3DecodeName("%zz", "url")
	require.Error(t, err)
}

type s3TestDoer func(*http.Request) (*http.Response, error)

func (f s3TestDoer) Do(req *http.Request) (*http.Response, error) { return f(req) }

type s3TrackedBody struct {
	io.Reader
	closed bool
}

func (b *s3TrackedBody) Close() error { b.closed = true; return nil }

func TestS3HTTPResponseBodiesClosed(t *testing.T) {
	for _, operation := range []string{"attributes", "objects", "versions", "error", "download"} {
		t.Run(operation, func(t *testing.T) {
			body := &s3TrackedBody{Reader: strings.NewReader("malformed XML")}
			cfg := s3TestConfig("http://127.0.0.1:9000", nil)
			cfg.HTTPClient = s3TestDoer(func(*http.Request) (*http.Response, error) {
				status := 200
				if operation == "error" {
					status = 403
				}
				return &http.Response{
					StatusCode: status,
					Header:     make(http.Header),
					Body:       body,
				}, nil
			})
			client, err := newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			object := S3Object{Bucket: "bucket", Key: "key"}
			switch operation {
			case "attributes":
				_, err = client.GetObjectETag(t.Context(), object)
			case "objects":
				_, err = client.ListObjects(t.Context(), "bucket", "", "")
			case "versions":
				_, err = client.ListVersions(t.Context(), "bucket", "", "", "")
			case "error":
				_, err = client.GetObject(t.Context(), object)
			case "download":
				ft := NewS3FileTransfer(
					client,
					observabilitytest.NewTestLogger(t),
					NewFileTransferStats(),
				)
				err = ft.downloadFile(object, filepath.Join(t.TempDir(), "out"))
			}
			if operation == "download" {
				require.NoError(t, err)
			} else {
				require.Error(t, err)
			}
			assert.True(t, body.closed)
		})
	}
}

func TestS3HTTPRejectsStalledPagination(t *testing.T) {
	for _, versions := range []bool{false, true} {
		t.Run(fmt.Sprint(versions), func(t *testing.T) {
			cfg := s3TestConfig("http://127.0.0.1:9000", nil)
			cfg.HTTPClient = s3TestDoer(func(*http.Request) (*http.Response, error) {
				xmlBody := `<ListBucketResult><IsTruncated>true</IsTruncated></ListBucketResult>`
				if versions {
					xmlBody = `<ListVersionsResult><IsTruncated>true</IsTruncated></ListVersionsResult>`
				}
				return &http.Response{
					StatusCode: 200,
					Header:     make(http.Header),
					Body:       io.NopCloser(strings.NewReader(xmlBody)),
				}, nil
			})
			client, err := newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			ft := NewS3FileTransfer(
				client,
				observabilitytest.NewTestLogger(t),
				NewFileTransferStats(),
			)
			if versions {
				_, err = ft.getCorrectObjectVersion(
					S3Object{Bucket: "bucket", Key: "key"},
					"digest",
				)
			} else {
				_, err = ft.listObjectsWithPrefix("bucket", "")
			}
			require.ErrorContains(t, err, "truncated page")
		})
	}
}

func TestS3HTTPProfileServiceEndpoint(t *testing.T) {
	t.Setenv("AWS_EC2_METADATA_DISABLED", "true")
	t.Setenv("AWS_REGION", "")
	t.Setenv("AWS_DEFAULT_REGION", "")
	t.Setenv("AWS_PROFILE", "")
	t.Setenv("AWS_DEFAULT_PROFILE", "")
	t.Setenv("AWS_ENDPOINT_URL", "")
	t.Setenv("AWS_ENDPOINT_URL_S3", "")
	t.Setenv("AWS_IGNORE_CONFIGURED_ENDPOINT_URLS", "false")
	t.Setenv("AWS_ACCESS_KEY_ID", "test-access-key")
	t.Setenv("AWS_SECRET_ACCESS_KEY", "test-secret-key")
	dir := t.TempDir()
	configPath := filepath.Join(dir, "config")
	require.NoError(
		t,
		os.WriteFile(
			configPath,
			[]byte(
				"[default]\nregion = eu-west-1\nservices = test-services\nendpoint_url = http://127.0.0.1:9000\n[services test-services]\ns3 =\n  endpoint_url = http://127.0.0.1:9003\n",
			),
			0o600,
		),
	)
	t.Setenv("AWS_CONFIG_FILE", configPath)
	t.Setenv("AWS_SHARED_CREDENTIALS_FILE", filepath.Join(dir, "credentials"))
	cfg, err := config.LoadDefaultConfig(t.Context())
	require.NoError(t, err)
	client, err := newS3HTTPClient(t.Context(), &cfg)
	require.NoError(t, err)
	assert.Equal(t, "127.0.0.1:9003", client.endpoint.Host)
	assert.Equal(t, "eu-west-1", client.region)
}

func TestS3HTTPPreservesStoredGzip(t *testing.T) {
	var compressed bytes.Buffer
	writer := gzip.NewWriter(&compressed)
	_, err := writer.Write([]byte("stored gzip contents"))
	require.NoError(t, err)
	require.NoError(t, writer.Close())
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "identity", r.Header.Get("Accept-Encoding"))
		w.Header().Set("Content-Encoding", "gzip")
		_, _ = w.Write(compressed.Bytes())
	}))
	defer server.Close()
	client, err := newS3HTTPClient(t.Context(), s3TestConfig(server.URL, server.Client()))
	require.NoError(t, err)
	body, err := client.GetObject(t.Context(), S3Object{Bucket: "bucket", Key: "key"})
	require.NoError(t, err)
	defer body.Close()
	got, err := io.ReadAll(body)
	require.NoError(t, err)
	assert.Equal(t, compressed.Bytes(), got)
}

func TestS3HTTPServiceCodeRetries(t *testing.T) {
	for _, tc := range []struct {
		code         string
		status       int
		succeeds     bool
		wantAttempts int
	}{
		{"RequestTimeout", 400, true, 2},
		{"RequestTimeoutException", 400, true, 2},
		{"SlowDown", 400, true, 2},
		{"Throttling", 403, true, 2},
		{"RequestTimeout", 400, false, 3},
		{"AccessDenied", 403, false, 1},
	} {
		t.Run(fmt.Sprintf("%s-%t", tc.code, tc.succeeds), func(t *testing.T) {
			calls, authorizations := 0, 0
			var bodies []*s3TrackedBody
			cfg := s3TestConfig("http://127.0.0.1:9000", nil)
			cfg.RetryMaxAttempts = 3
			cfg.Credentials = aws.CredentialsProviderFunc(
				func(context.Context) (aws.Credentials, error) {
					authorizations++
					return s3TestCredentials, nil
				},
			)
			cfg.HTTPClient = s3TestDoer(func(req *http.Request) (*http.Response, error) {
				calls++
				checkS3Signature(t, req)
				status := tc.status
				payload := fmt.Sprintf(
					"<Error><Code>%s</Code><Message>original service message</Message></Error>",
					tc.code,
				)
				if tc.succeeds && calls > 1 {
					status, payload = 200, "ok"
				}
				body := &s3TrackedBody{Reader: strings.NewReader(payload)}
				bodies = append(bodies, body)
				return &http.Response{
					StatusCode: status,
					Header:     make(http.Header),
					Body:       body,
				}, nil
			})
			client, err := newS3HTTPClient(t.Context(), cfg)
			require.NoError(t, err)
			client.http.retryDelay = func(int, *http.Response) time.Duration { return 0 }
			body, err := client.GetObject(t.Context(), S3Object{Bucket: "bucket", Key: "key"})
			if tc.succeeds {
				require.NoError(t, err)
				content, err := io.ReadAll(body)
				require.NoError(t, err)
				require.NoError(t, body.Close())
				assert.Equal(t, "ok", string(content))
			} else {
				require.ErrorContains(t, err, tc.code)
				require.ErrorContains(t, err, "original service message")
			}
			assert.Equal(t, tc.wantAttempts, calls)
			assert.Equal(t, tc.wantAttempts, authorizations)
			for _, body := range bodies {
				assert.True(t, body.closed)
			}
		})
	}
}

type s3CountingReader struct {
	io.Reader
	bytesRead int
}

func (r *s3CountingReader) Read(p []byte) (int, error) {
	n, err := r.Reader.Read(p)
	r.bytesRead += n
	return n, err
}

func TestS3ServiceCodeRetryPreservesErrorBody(t *testing.T) {
	for _, payload := range []string{
		`<Error><Code>AccessDenied</Code><Message>original detail</Message></Error>`,
		`<Error><Code>RequestTimeout</Code>`,
		`<Error><Code>RequestTimeout</Code><Message>` + strings.Repeat("x", 8192) + `</Message></Error>`,
	} {
		reader := &s3CountingReader{Reader: strings.NewReader(payload)}
		body := &s3TrackedBody{Reader: reader}
		resp := &http.Response{StatusCode: 400, Header: make(http.Header), Body: body}
		require.False(t, s3RetryResponse(resp))
		require.LessOrEqual(t, reader.bytesRead, 4096)
		got, err := io.ReadAll(resp.Body)
		require.NoError(t, err)
		assert.Equal(t, payload, string(got))
		require.NoError(t, resp.Body.Close())
		assert.True(t, body.closed)
	}
}
