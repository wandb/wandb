//go:build cloud_http

package filetransfer

import (
	"bytes"
	"compress/gzip"
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"errors"
	"io"
	"net/http"
	"strconv"
	"strings"
	"testing"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestAzureReadConfiguration(t *testing.T) {
	tests := []struct {
		name string
		env  map[string]string
		want azureReadConfiguration
		err  string
	}{
		{name: "account required", err: "account is required"},
		{
			name: "default identity",
			env:  map[string]string{"AZURE_STORAGE_ACCOUNT": "account"},
			want: azureReadConfiguration{
				endpoint: "https://account.blob.core.windows.net",
				account:  "account",
			},
		},
		{
			name: "sovereign storage domain",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT": "account",
				"AZURE_STORAGE_DOMAIN":  "blob.core.usgovcloudapi.net",
			},
			want: azureReadConfiguration{
				endpoint: "https://account.blob.core.usgovcloudapi.net",
				account:  "account",
			},
		},
		{
			name: "shared key precedes SAS and connection",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":           "account",
				"AZURE_STORAGE_KEY":               "a2V5",
				"AZURE_STORAGE_SAS_TOKEN":         "sig=a%2Bb%3D",
				"AZURE_STORAGE_CONNECTION_STRING": "AccountName=other;AccountKey=b3RoZXI=",
			},
			want: azureReadConfiguration{
				endpoint: "https://account.blob.core.windows.net?sig=a%2Bb%3D",
				account:  "account",
				key:      "a2V5",
				auth:     azureReadSharedKey,
			},
		},
		{
			name: "SAS precedes connection",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT": "account", "AZURE_STORAGE_SAS_TOKEN": "sig=a%2Bb%3D",
				"AZURE_STORAGE_CONNECTION_STRING": "AccountName=other;AccountKey=b3RoZXI="},
			want: azureReadConfiguration{
				endpoint: "https://account.blob.core.windows.net?sig=a%2Bb%3D",
				account:  "account",
				auth:     azureReadSAS,
			},
		},
		{
			name: "local emulator",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":   "devstore",
				"AZURE_STORAGE_DOMAIN":    "127.0.0.1:10000",
				"AZURE_STORAGE_PROTOCOL":  "http",
				"AZURE_STORAGE_SAS_TOKEN": "sig=test",
			},
			want: azureReadConfiguration{
				endpoint: "http://127.0.0.1:10000/devstore?sig=test",
				account:  "devstore",
				auth:     azureReadSAS,
			},
		},
		{
			name: "explicit local emulator",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":           "devstore",
				"AZURE_STORAGE_DOMAIN":            "azurite:10000",
				"AZURE_STORAGE_PROTOCOL":          "http",
				"AZURE_STORAGE_IS_LOCAL_EMULATOR": "true",
			},
			want: azureReadConfiguration{
				endpoint: "http://azurite:10000/devstore",
				account:  "devstore",
			},
		},
		{name: "CDN", env: map[string]string{
			"AZURE_STORAGE_ACCOUNT": "account",
			"AZURE_STORAGE_DOMAIN":  "cdn.example.com",
			"AZURE_STORAGE_IS_CDN":  "true",
		},
			want: azureReadConfiguration{endpoint: "https://cdn.example.com", account: "account"}},
		{
			name: "connection endpoint overrides env domain",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":           "envaccount",
				"AZURE_STORAGE_DOMAIN":            "ignored.example.com",
				"AZURE_STORAGE_CONNECTION_STRING": "DefaultEndpointsProtocol=https;AccountName=connected;AccountKey=a2V5;BlobEndpoint=http://localhost:10000/connected;",
			},
			want: azureReadConfiguration{
				endpoint: "http://localhost:10000/connected",
				account:  "connected",
				key:      "a2V5",
				auth:     azureReadSharedKey,
			},
		},
		{
			name: "connection suffix and account fallback",
			env: map[string]string{
				"AZURE_STORAGE_CONNECTION_STRING": "AccountName=connected;AccountKey=a2V5;EndpointSuffix=core.chinacloudapi.cn",
			},
			want: azureReadConfiguration{
				endpoint: "https://connected.blob.core.chinacloudapi.cn",
				account:  "connected",
				key:      "a2V5",
				auth:     azureReadSharedKey,
			},
		},
		{
			name: "connection alias SAS",
			env: map[string]string{
				"AZURE_STORAGEBLOB_CONNECTIONSTRING": "AccountName=connected;SharedAccessSignature=sv=1&sig=a%2Bb%3D",
			},
			want: azureReadConfiguration{
				endpoint: "https://connected.blob.core.windows.net?sv=1&sig=a%2Bb%3D",
				auth:     azureReadSAS,
			},
		},
		{
			name: "connection SAS with explicit endpoint",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":           "account",
				"AZURE_STORAGE_CONNECTION_STRING": "BlobEndpoint=https://cdn.example.com;SharedAccessSignature=sv=1&sig=test",
			},
			want: azureReadConfiguration{
				endpoint: "https://cdn.example.com?sv=1&sig=test",
				auth:     azureReadSAS,
			},
		},
		{
			name: "invalid protocol",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":  "account",
				"AZURE_STORAGE_PROTOCOL": "ftp",
			},
			err: "protocol",
		},
		{
			name: "malformed connection",
			env: map[string]string{
				"AZURE_STORAGE_ACCOUNT":           "account",
				"AZURE_STORAGE_CONNECTION_STRING": "broken",
			},
			err: "malformed",
		},
		{
			name: "connection credentials required",
			env:  map[string]string{"AZURE_STORAGE_CONNECTION_STRING": "AccountName=account"},
			err:  "requires AccountKey or SharedAccessSignature",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			got, err := azureReadConfigFromEnv(func(key string) string { return test.env[key] })
			if test.err != "" {
				require.ErrorContains(t, err, test.err)
				return
			}
			require.NoError(t, err)
			assert.Equal(t, test.want, got)
		})
	}
}

func TestAzureReadSharedKeySigning(t *testing.T) {
	request, err := runtime.NewRequest(
		context.Background(),
		http.MethodGet,
		"https://account.blob.core.windows.net/c/a%20b?restype=container&comp=list&prefix=a%2Bb&tag=z&tag=a",
	)
	require.NoError(t, err)
	request.Raw().Header.Set("x-ms-date", "Fri, 11 Sep 2026 12:00:00 GMT")
	request.Raw().Header.Set("x-ms-version", azureStorageAPIVersion)
	request.Raw().Header.Set("Range", "bytes=5-")
	request.Raw().Header.Set("Content-Length", "0")
	want := "GET\n\n\n\n\n\n\n\n\n\n\nbytes=5-\n" +
		"x-ms-date:Fri, 11 Sep 2026 12:00:00 GMT\nx-ms-version:2023-11-03\n" +
		"/account/c/a%20b\ncomp:list\nprefix:a+b\nrestype:container\ntag:a,z"
	actual, err := azureSharedKeyStringToSign(request.Raw(), "account")
	require.NoError(t, err)
	assert.Equal(t, want, actual)

	key := []byte("a test storage account key")
	signer, err := newAzureSharedKeyPolicy("account", base64.StdEncoding.EncodeToString(key))
	require.NoError(t, err)
	hash := hmac.New(sha256.New, key)
	_, err = hash.Write([]byte(want))
	require.NoError(t, err)
	wantAuthorization := "SharedKey account:" + base64.StdEncoding.EncodeToString(hash.Sum(nil))
	attempts := 0
	options := azureTestOptions(func(req *http.Request) (*http.Response, error) {
		assert.Equal(t, wantAuthorization, req.Header.Get("Authorization"))
		attempts++
		status := http.StatusOK
		if attempts == 1 {
			status = http.StatusServiceUnavailable
		}
		return azureTestResponse(req, status, nil, ""), nil
	})
	options.PerRetryPolicies = []policy.Policy{signer}
	pipeline := runtime.NewPipeline("wandb-core", "v0.0.0", runtime.PipelineOptions{}, options)
	response, err := pipeline.Do(request)
	require.NoError(t, err)
	response.Body.Close()
	assert.Equal(t, 2, attempts)
	_, err = newAzureSharedKeyPolicy("account", "not-base64!")
	require.ErrorContains(t, err, "account key")
}

func TestAzureReadListPaginationAndEscapedKeys(t *testing.T) {
	requests := 0
	client, err := newAzureAccountHTTPClient(
		"https://account.blob.core.windows.net?sig=a%2Bb%3D",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			assert.Equal(t, "/c", req.URL.Path)
			assert.Equal(t, "a+b=", req.URL.Query().Get("sig"))
			assert.Equal(t, "container", req.URL.Query().Get("restype"))
			assert.Equal(t, "list", req.URL.Query().Get("comp"))
			assert.Equal(t, "run__0x25__/", req.URL.Query().Get("prefix"))
			assert.Equal(t, "application/xml", req.Header.Get("Accept"))
			assert.Empty(t, req.Header.Get("Authorization"))
			assert.Empty(t, req.URL.Query().Get("include"))
			if requests == 1 {
				assert.Empty(t, req.URL.Query().Get("marker"))
				return azureTestResponse(req, http.StatusOK, nil, `<EnumerationResults><Blobs>
<Blob><Name>run__0x25__/events.1</Name></Blob>
<Blob><Name Encoded="true">run__0x25__%2Fevents.%E9%9B%AA</Name></Blob>
</Blobs><NextMarker>a+b/=</NextMarker></EnumerationResults>`), nil
			}
			assert.Equal(t, "a+b/=", req.URL.Query().Get("marker"))
			return azureTestResponse(
				req,
				http.StatusOK,
				nil,
				`<EnumerationResults><Blobs><Blob><Name>run__0x25__/events.z</Name></Blob></Blobs></EnumerationResults>`,
			), nil
		}),
	)
	require.NoError(t, err)
	bucket := &azureReadBucket{client: client, bucket: "c"}
	page, err := bucket.ListPage(context.Background(), "run%/", "")
	require.NoError(t, err)
	assert.Equal(t, []string{"run%/events.1", "run%/events.雪"}, page.Keys)
	assert.Equal(t, "a+b/=", page.NextToken)
	page, err = bucket.ListPage(context.Background(), "run%/", page.NextToken)
	require.NoError(t, err)
	assert.Equal(t, []string{"run%/events.z"}, page.Keys)
	assert.Empty(t, page.NextToken)
}

func TestAzureReadRangesObserveGrowingBlob(t *testing.T) {
	content := "first"
	requests := 0
	client, err := newAzureAccountHTTPClient("https://account.blob.core.windows.net?sig=fake", nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			assert.Equal(t, "/c/run__0x25__/events", req.URL.Path)
			assert.Equal(t, "identity", req.Header.Get("Accept-Encoding"))
			assert.Empty(t, req.Header.Get("If-Match"))
			if req.Method == http.MethodHead {
				return azureTestResponse(
					req,
					http.StatusOK,
					http.Header{"Content-Length": {strconv.Itoa(len(content))}},
					"",
				), nil
			}
			assert.Equal(t, http.MethodGet, req.Method)
			if req.Header.Get("Range") == "" {
				return azureTestResponse(req, http.StatusOK, nil, content), nil
			}
			assert.Equal(t, "bytes=5-", req.Header.Get("Range"))
			if len(content) == 5 {
				return azureTestResponse(req, http.StatusRequestedRangeNotSatisfiable,
					http.Header{"Content-Range": {"bytes */5"}}, ""), nil
			}
			return azureTestResponse(req, http.StatusPartialContent,
				http.Header{"Content-Range": {"bytes 5-9/10"}}, content[5:]), nil
		}))
	require.NoError(t, err)
	bucket := &azureReadBucket{client: client, bucket: "c"}
	for _, test := range []struct {
		offset int64
		want   string
	}{{0, "first"}, {5, ""}, {5, "later"}} {
		reader, err := bucket.NewRangeReader(context.Background(), "run%/events", test.offset)
		require.NoError(t, err)
		data, err := io.ReadAll(reader)
		require.NoError(t, err)
		require.NoError(t, reader.Close())
		assert.Equal(t, test.want, string(data))
		if test.offset == 5 {
			content = "firstlater"
		}
	}
	assert.Equal(t, 4, requests)
}

func TestAzureReadRangeValidation(t *testing.T) {
	tests := []struct {
		name    string
		offset  int64
		status  int
		header  http.Header
		body    string
		err     string
		readErr error
	}{
		{name: "negative offset", offset: -1, err: "non-negative"},
		{name: "ignored range", offset: 2, status: 200, body: "abcdef", err: "ignored"},
		{
			name:   "unrequested partial",
			status: 206,
			header: http.Header{"Content-Range": {"bytes 0-2/3"}},
			body:   "abc",
			err:    "partial",
		},
		{
			name:   "wrong start",
			offset: 2,
			status: 206,
			header: http.Header{"Content-Range": {"bytes 0-2/3"}},
			body:   "abc",
			err:    "Content-Range",
		},
		{
			name:   "incomplete range",
			offset: 2,
			status: 206,
			header: http.Header{"Content-Range": {"bytes 2-4/8"}},
			body:   "abc",
			err:    "Content-Range",
		},
		{
			name:   "length mismatch",
			offset: 2,
			status: 206,
			header: http.Header{"Content-Range": {"bytes 2-4/5"}},
			body:   "ab",
			err:    "Content-Length",
		},
		{
			name:    "truncated body",
			offset:  2,
			status:  206,
			header:  http.Header{"Content-Range": {"bytes 2-4/5"}, "Content-Length": {"3"}},
			body:    "ab",
			readErr: io.ErrUnexpectedEOF,
		},
		{name: "EOF without length", offset: 2, status: 416, err: "status 416"},
		{
			name:   "EOF before end",
			offset: 2,
			status: 416,
			header: http.Header{"Content-Range": {"bytes */3"}},
			err:    "status 416",
		},
		{
			name:   "EOF after end",
			offset: 4,
			status: 416,
			header: http.Header{"Content-Range": {"bytes */3"}},
		},
		{name: "missing object", offset: 2, status: 404, err: "status 404"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			client, err := newAzureAccountHTTPClient("https://account.blob.core.windows.net", nil,
				azureTestOptions(func(req *http.Request) (*http.Response, error) {
					if req.Method == http.MethodHead {
						return azureTestResponse(
							req,
							http.StatusOK,
							http.Header{"Content-Length": {"100"}},
							"",
						), nil
					}
					return azureTestResponse(req, test.status, test.header, test.body), nil
				}))
			require.NoError(t, err)
			bucket := &azureReadBucket{client: client, bucket: "c"}
			reader, err := bucket.NewRangeReader(context.Background(), "events", test.offset)
			if test.err != "" {
				require.ErrorContains(t, err, test.err)
				return
			}
			require.NoError(t, err)
			_, err = io.ReadAll(reader)
			assert.True(
				t,
				errors.Is(err, test.readErr),
				"read error = %v, want %v",
				err,
				test.readErr,
			)
			require.NoError(t, reader.Close())
		})
	}
}

func TestAzureReadGzipLogicalOffsetsAndGrowth(t *testing.T) {
	// The logical offset exceeds the entire compressed object size. It must
	// never be compared with HEAD's stored Content-Length or sent as Range.
	content := strings.Repeat("event data\n", 100)
	stored := azureTestGzip(t, content)
	client, err := newAzureAccountHTTPClient("https://account.blob.core.windows.net", nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			assert.Empty(t, req.Header.Get("Range"))
			headers := http.Header{
				"Content-Encoding": {"gzip"},
				"Content-Length":   {strconv.Itoa(len(stored))},
			}
			if req.Method == http.MethodHead {
				return azureTestResponse(req, http.StatusOK, headers, ""), nil
			}
			return azureTestResponse(req, http.StatusOK, headers, stored), nil
		}))
	require.NoError(t, err)
	bucket := &azureReadBucket{client: client, bucket: "c"}
	read := func(offset int64, want string) {
		t.Helper()
		reader, err := bucket.NewRangeReader(context.Background(), "events", offset)
		require.NoError(t, err)
		data, err := io.ReadAll(reader)
		require.NoError(t, err)
		require.NoError(t, reader.Close())
		assert.Equal(t, want, string(data))
	}
	read(0, content)
	read(1000, content[1000:])
	read(int64(len(content)), "")
	read(int64(len(content)+50), "")
	stored = azureTestGzip(t, content+"a later event\n")
	read(int64(len(content)), "a later event\n")
}

func TestAzureReadGzipRejectsTruncatedStream(t *testing.T) {
	stored := azureTestGzip(t, "an event")
	client, err := newAzureAccountHTTPClient("https://account.blob.core.windows.net", nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			return azureTestResponse(
				req,
				http.StatusOK,
				http.Header{"Content-Encoding": {"gzip"}},
				stored[:len(stored)-4],
			), nil
		}))
	require.NoError(t, err)
	bucket := &azureReadBucket{client: client, bucket: "c"}
	reader, err := bucket.NewRangeReader(context.Background(), "events", 0)
	require.NoError(t, err)
	_, err = io.ReadAll(reader)
	require.ErrorIs(t, err, io.ErrUnexpectedEOF)
	require.NoError(t, reader.Close())
}

func azureTestGzip(t *testing.T, content string) string {
	t.Helper()
	var encoded bytes.Buffer
	writer := gzip.NewWriter(&encoded)
	_, err := writer.Write([]byte(content))
	require.NoError(t, err)
	require.NoError(t, writer.Close())
	return encoded.String()
}

func TestAzureReadKeyMapping(t *testing.T) {
	for _, test := range []struct {
		key, escaped string
		prefix       bool
	}{
		{"run%/events?#", "run__0x25__/events__0x3f____0x23__", false},
		{"a\\b\x00\"", "a__0x5c__b__0x0____0x22__", false},
		{"a/../b", "a/..__0x2f__b", false},
		{"folder/", "folder__0x2f__", false},
		{"folder/", "folder/", true},
		{"雪/events", "雪/events", false},
		// Keep the existing driver's trailing-slash behavior for multibyte keys.
		{"雪/", "雪/", false},
	} {
		t.Run(test.key, func(t *testing.T) {
			assert.Equal(t, test.escaped, azureCloudEscapeKey(test.key, test.prefix))
			assert.Equal(t, test.key, azureCloudUnescapeKey(test.escaped))
		})
	}
	assert.Equal(t, "literal__0xwat__%", azureCloudUnescapeKey("literal__0xwat____0x25__"))
	assert.Equal(t, strings.Repeat("x", 5), azureCloudUnescapeKey("xxxxx"))
}
