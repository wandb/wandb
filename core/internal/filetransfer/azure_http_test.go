//go:build cloud_http

package filetransfer

import (
	"bytes"
	"context"
	"crypto/md5"
	"encoding/base64"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
)

type azureTestTransport func(*http.Request) (*http.Response, error)

func (f azureTestTransport) Do(request *http.Request) (*http.Response, error) { return f(request) }
func azureTestOptions(f azureTestTransport) *azcore.ClientOptions {
	return &azcore.ClientOptions{
		Transport: f,
		Retry:     policy.RetryOptions{RetryDelay: time.Nanosecond, MaxRetryDelay: time.Nanosecond},
	}
}

func azureTestResponse(
	request *http.Request,
	status int,
	headers http.Header,
	content string,
) *http.Response {
	if headers == nil {
		headers = http.Header{}
	}
	length := int64(len(content))
	if v := headers.Get("Content-Length"); v != "" {
		length, _ = strconv.ParseInt(v, 10, 64)
	}
	return &http.Response{
		StatusCode:    status,
		Header:        headers,
		Request:       request,
		ContentLength: length,
		Body:          io.NopCloser(strings.NewReader(content)),
	}
}

func TestAzureHTTPSASUploadOffsetAndHeaders(t *testing.T) {
	var requests int
	var uploaded []byte
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/object?sig=a%2Bb%3D",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			assert.Equal(t, http.MethodPut, req.Method)
			assert.Equal(t, "a+b=", req.URL.Query().Get("sig"))
			assert.Empty(t, req.Header.Get("Authorization"))
			assert.Equal(t, "BlockBlob", req.Header.Get("x-ms-blob-type"))
			assert.Equal(t, "text/plain", req.Header.Get("Content-Type"))
			assert.Equal(t, "value", req.Header.Get("x-ms-meta-key"))
			assert.Equal(t, int64(4), req.ContentLength)
			data, readErr := io.ReadAll(req.Body)
			require.NoError(t, readErr)
			uploaded = data
			checksum := md5.Sum(uploaded)
			assert.Equal(
				t,
				base64.StdEncoding.EncodeToString(checksum[:]),
				req.Header.Get("Content-MD5"),
			)
			return azureTestResponse(
				req,
				http.StatusCreated,
				http.Header{"Etag": {`"new"`}},
				"",
			), nil
		}),
	)
	require.NoError(t, err)
	path := filepath.Join(t.TempDir(), "source")
	require.NoError(t, os.WriteFile(path, []byte("0123456789"), 0o600))
	checksum := md5.Sum([]byte("2345"))
	var done, total int
	task := &DefaultUploadTask{Path: path, Offset: 2, Size: 4, Headers: http.Header{
		"Content-Type": {
			"text/plain",
		},
		"Content-Md5":   {base64.StdEncoding.EncodeToString(checksum[:])},
		"X-Ms-Meta-Key": {"value"},
	}, ProgressCallback: func(d, n int) { done, total = d, n }}
	ft := NewAzureFileTransfer(
		&AzureClientOverrides{BlockBlobClient: client},
		observabilitytest.NewTestLogger(t),
		NewFileTransferStats(),
	)
	require.NoError(t, ft.Upload(task))
	defer task.Response.Body.Close()
	assert.Equal(t, 1, requests)
	assert.Equal(t, []byte("2345"), uploaded)
	assert.Equal(t, 4, done)
	assert.Equal(t, 4, total)
	assert.Equal(t, `"new"`, task.Response.Header.Get("ETag"))
}

func TestAzureHTTPStagedUploadRetriesAndCommitsInOrder(t *testing.T) {
	content := bytes.Repeat([]byte("abcdefg"), azureUploadBlockSize/7+1)
	content = append(append([]byte{}, content...), content...)
	checksum := md5.Sum(content)
	var mu sync.Mutex
	blocks := map[string][]byte{}
	attempts := map[string]int{}
	var committed []string
	var failures int
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/object?sig=signature",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			data, err := io.ReadAll(req.Body)
			if err != nil {
				return nil, err
			}
			mu.Lock()
			defer mu.Unlock()
			assert.Equal(t, "signature", req.URL.Query().Get("sig"))
			assert.Equal(t, int64(len(data)), req.ContentLength)
			switch req.URL.Query().Get("comp") {
			case "block":
				id := req.URL.Query().Get("blockid")
				decoded, err := base64.StdEncoding.DecodeString(id)
				assert.NoError(t, err)
				assert.Len(t, decoded, 20)
				assert.LessOrEqual(t, len(data), azureUploadBlockSize)
				assert.Empty(t, req.Header.Get("Content-MD5"))
				assert.Empty(t, req.Header.Get("x-ms-blob-content-md5"))
				attempts[id]++
				if failures == 0 {
					failures++
					return azureTestResponse(req, http.StatusServiceUnavailable, nil, "retry"), nil
				}
				blocks[id] = data
			case "blocklist":
				var list struct {
					IDs []string `xml:"Latest"`
				}
				assert.NoError(t, xml.Unmarshal(data, &list))
				committed = list.IDs
				assert.Equal(
					t,
					base64.StdEncoding.EncodeToString(checksum[:]),
					req.Header.Get("x-ms-blob-content-md5"),
				)
				assert.Equal(t, "application/test", req.Header.Get("x-ms-blob-content-type"))
				assert.Equal(t, "application/xml", req.Header.Get("Content-Type"))
				assert.Empty(t, req.Header.Get("Content-MD5"))
			default:
				t.Errorf("unexpected request: %s", req.URL)
			}
			return azureTestResponse(
				req,
				http.StatusCreated,
				http.Header{"Etag": {`"committed"`}},
				"",
			), nil
		}),
	)
	require.NoError(t, err)
	response, err := client.UploadStream(
		context.Background(),
		bytes.NewReader(content),
		http.Header{
			"Content-Type": {"application/test"},
			"Content-Md5":  {base64.StdEncoding.EncodeToString(checksum[:])},
		},
	)
	require.NoError(t, err)
	defer response.Body.Close()
	require.Len(t, committed, 3)
	var assembled []byte
	var retried int
	for _, id := range committed {
		assembled = append(assembled, blocks[id]...)
		if attempts[id] > 1 {
			retried++
		}
	}
	assert.Equal(t, content, assembled)
	assert.Equal(t, 1, retried)
}

func TestAzureHTTPEmptyAndCancelledUpload(t *testing.T) {
	requests := 0
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/object",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			assert.Zero(t, req.ContentLength)
			assert.True(t, req.Body == nil || req.Body == http.NoBody)
			return azureTestResponse(req, http.StatusCreated, nil, ""), nil
		}),
	)
	require.NoError(t, err)
	response, err := client.UploadStream(context.Background(), strings.NewReader(""), nil)
	require.NoError(t, err)
	response.Body.Close()
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	_, err = client.UploadStream(ctx, strings.NewReader(""), nil)
	require.ErrorIs(t, err, context.Canceled)
	assert.Equal(t, 1, requests)
}

type azureErrorReader struct{ io.Reader }

func (r azureErrorReader) Read(p []byte) (int, error) {
	n, err := r.Reader.Read(p)
	if err == io.EOF {
		err = errors.New("source failed")
	}
	return n, err
}
func TestAzureHTTPDoesNotCommitIncompleteSource(t *testing.T) {
	var mu sync.Mutex
	var committed bool
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/object",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			mu.Lock()
			defer mu.Unlock()
			if req.URL.Query().Get("comp") == "blocklist" {
				committed = true
			}
			return azureTestResponse(req, http.StatusCreated, nil, ""), nil
		}),
	)
	require.NoError(t, err)
	_, err = client.UploadStream(
		context.Background(),
		azureErrorReader{bytes.NewReader(make([]byte, azureUploadBlockSize))},
		nil,
	)
	require.ErrorContains(t, err, "source failed")
	mu.Lock()
	defer mu.Unlock()
	assert.False(t, committed)
}

func TestAzureHTTPXMLListingAndEscapedNames(t *testing.T) {
	var requests int
	client, err := newAzureAccountHTTPClient(
		"https://account.blob.core.windows.net",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			assert.Equal(t, "application/xml", req.Header.Get("Accept"))
			assert.Equal(t, "versions", req.URL.Query().Get("include"))
			assert.Equal(t, "dir/% ?", req.URL.Query().Get("prefix"))
			assert.Equal(t, "container", req.URL.Query().Get("restype"))
			assert.Equal(t, "list", req.URL.Query().Get("comp"))
			if requests == 1 {
				return azureTestResponse(
					req,
					200,
					nil,
					`<EnumerationResults><Blobs><Blob><Name>dir/% ?/a</Name><VersionId>v+1</VersionId></Blob></Blobs><NextMarker>next&amp;marker</NextMarker></EnumerationResults>`,
				), nil
			}
			assert.Equal(t, "next&marker", req.URL.Query().Get("marker"))
			return azureTestResponse(
				req,
				200,
				nil,
				`<EnumerationResults><Blobs></Blobs><NextMarker/></EnumerationResults>`,
			), nil
		}),
	)
	require.NoError(t, err)
	first, err := client.ListBlobs(context.Background(), "container", "dir/% ?", "", true)
	require.NoError(t, err)
	assert.Equal(t, []AzureBlobItem{{Name: "dir/% ?/a", VersionID: "v+1"}}, first.Items)
	second, err := client.ListBlobs(
		context.Background(),
		"container",
		"dir/% ?",
		first.NextMarker,
		true,
	)
	require.NoError(t, err)
	assert.Empty(t, second.NextMarker)
	blob := client.NewBlobClient("container", "dir//./% ?/#ü").(*azureBlobHTTPClient)
	assert.Equal(t, "/container/dir//./%25%20%3F/%23%C3%BC", blob.endpoint.EscapedPath())
	versioned, err := blob.WithVersionID("v+1/=")
	require.NoError(t, err)
	assert.Equal(t, "v+1/=", versioned.(*azureBlobHTTPClient).endpoint.Query().Get("versionid"))
	assert.Empty(t, blob.endpoint.Query().Get("versionid"))
}

func TestAzureHTTPDownloadResumesWithETagAndVersion(t *testing.T) {
	var ranges []string
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/object?versionid=old",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			assert.Equal(t, "old", req.URL.Query().Get("versionid"))
			if req.Method == http.MethodHead {
				return azureTestResponse(
					req,
					200,
					http.Header{"Content-Length": {"6"}, "Etag": {`"original"`}},
					"",
				), nil
			}
			assert.Equal(t, `"original"`, req.Header.Get("If-Match"))
			ranges = append(ranges, req.Header.Get("Range"))
			if len(ranges) == 1 {
				return azureTestResponse(
					req,
					206,
					http.Header{
						"Content-Range":  {"bytes 0-5/6"},
						"Content-Length": {"6"},
						"Etag":           {`"original"`},
					},
					"abc",
				), nil
			}
			return azureTestResponse(
				req,
				206,
				http.Header{
					"Content-Range":  {"bytes 3-5/6"},
					"Content-Length": {"3"},
					"Etag":           {`"original"`},
				},
				"def",
			), nil
		}),
	)
	require.NoError(t, err)
	file, err := os.CreateTemp(t.TempDir(), "download")
	require.NoError(t, err)
	defer file.Close()
	size, err := client.DownloadFile(context.Background(), file)
	require.NoError(t, err)
	assert.Equal(t, int64(6), size)
	data, err := os.ReadFile(file.Name())
	require.NoError(t, err)
	assert.Equal(t, "abcdef", string(data))
	assert.Equal(t, []string{"bytes=0-5", "bytes=3-5"}, ranges)
}

func TestAzureHTTPDownloadRejectsChangedOrInvalidRange(t *testing.T) {
	for _, test := range []struct {
		name               string
		status             int
		contentRange, etag string
	}{
		{"ignored range", 200, "", `"original"`},
		{"wrong offset", 206, "bytes 1-6/6", `"original"`},
		{"changed etag", 206, "bytes 0-5/6", `"changed"`},
		{"precondition failed", 412, "", `"changed"`},
	} {
		t.Run(test.name, func(t *testing.T) {
			client, err := newAzureBlobHTTPClient(
				"https://account.blob.core.windows.net/c/blob",
				nil,
				azureTestOptions(func(req *http.Request) (*http.Response, error) {
					if req.Method == http.MethodHead {
						return azureTestResponse(
							req,
							200,
							http.Header{"Content-Length": {"6"}, "Etag": {`"original"`}},
							"",
						), nil
					}
					return azureTestResponse(
						req,
						test.status,
						http.Header{
							"Content-Length": {"6"},
							"Content-Range":  {test.contentRange},
							"Etag":           {test.etag},
						},
						"abcdef",
					), nil
				}),
			)
			require.NoError(t, err)
			file, err := os.CreateTemp(t.TempDir(), "download")
			require.NoError(t, err)
			defer file.Close()
			_, err = client.DownloadFile(context.Background(), file)
			require.Error(t, err)
		})
	}
}

type azureTestCredential struct {
	mu       sync.Mutex
	requests []policy.TokenRequestOptions
}

func (c *azureTestCredential) GetToken(
	ctx context.Context,
	options policy.TokenRequestOptions,
) (azcore.AccessToken, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.requests = append(c.requests, options)
	return azcore.AccessToken{
		Token:     fmt.Sprintf("token-%d", len(c.requests)),
		ExpiresOn: time.Now().Add(time.Hour),
	}, nil
}
func TestAzureHTTPRetainsTokenCacheAndStorageChallenge(t *testing.T) {
	credential := &azureTestCredential{}
	var requests int
	client, err := newAzureBlobHTTPClient(
		"https://account.blob.core.windows.net/c/blob",
		credential,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			requests++
			expected := "Bearer token-1"
			if requests > 1 {
				expected = "Bearer token-2"
			}
			assert.Equal(t, expected, req.Header.Get("Authorization"))
			if requests == 1 {
				return azureTestResponse(
					req,
					401,
					http.Header{
						"Www-Authenticate": {
							`Bearer authorization_uri="https://login.microsoftonline.com/tenant/oauth2/authorize", resource_id="https://account.blob.core.windows.net"`,
						},
					},
					"",
				), nil
			}
			return azureTestResponse(
				req,
				200,
				http.Header{"Content-Length": {"0"}, "Etag": {`"etag"`}},
				"",
			), nil
		}),
	)
	require.NoError(t, err)
	_, err = client.GetProperties(context.Background())
	require.NoError(t, err)
	_, err = client.GetProperties(context.Background())
	require.NoError(t, err)
	require.Len(t, credential.requests, 2)
	assert.Equal(t, []string{azureStorageScope}, credential.requests[0].Scopes)
	assert.Equal(
		t,
		[]string{"https://account.blob.core.windows.net/.default"},
		credential.requests[1].Scopes,
	)
	assert.Equal(t, 3, requests)
}

func TestAzureHTTPXMLListingEncodedNames(t *testing.T) {
	var paths []string
	client, err := newAzureAccountHTTPClient(
		"https://account.blob.core.windows.net",
		nil,
		azureTestOptions(func(req *http.Request) (*http.Response, error) {
			if req.URL.Query().Get("comp") == "list" {
				return azureTestResponse(
					req,
					200,
					nil,
					`<EnumerationResults><Blobs><Blob><Name Encoded="true">prefix/a%01b</Name><VersionId>encoded-version</VersionId></Blob><Blob><Name>prefix/literal%01b+plus</Name><VersionId>literal-version</VersionId></Blob></Blobs></EnumerationResults>`,
				), nil
			}
			paths = append(paths, req.URL.EscapedPath())
			return azureTestResponse(
				req,
				200,
				http.Header{"Content-Length": {"0"}, "Etag": {`"etag"`}},
				"",
			), nil
		}),
	)
	require.NoError(t, err)
	page, err := client.ListBlobs(context.Background(), "container", "prefix/", "", true)
	require.NoError(t, err)
	require.Equal(t, []AzureBlobItem{
		{Name: "prefix/a\x01b", VersionID: "encoded-version"},
		{Name: "prefix/literal%01b+plus", VersionID: "literal-version"},
	}, page.Items)
	for _, item := range page.Items {
		_, err := client.NewBlobClient("container", item.Name).GetProperties(context.Background())
		require.NoError(t, err)
	}
	assert.Equal(
		t,
		[]string{"/container/prefix/a%01b", "/container/prefix/literal%2501b+plus"},
		paths,
	)

	var item AzureBlobItem
	require.ErrorContains(
		t,
		xml.Unmarshal([]byte(`<Blob><Name Encoded="true">invalid%zz</Name></Blob>`), &item),
		"decode Azure blob name",
	)
}
