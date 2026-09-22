//go:build cloud_http

package filetransfer

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/binary"
	"encoding/xml"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/Azure/azure-sdk-for-go/sdk/azcore"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/policy"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/runtime"
	"github.com/Azure/azure-sdk-for-go/sdk/azcore/streaming"
	"golang.org/x/sync/errgroup"
)

const (
	// Pin a REST version whose XML listing and block APIs we implement.
	azureStorageAPIVersion   = "2023-11-03"
	azureStorageScope        = "https://storage.azure.com/.default"
	azureUploadBlockSize     = 1 * 1024 * 1024
	azureDownloadBlockSize   = 4 * 1024 * 1024
	azureTransferConcurrency = 4
	azureMaxBlocks           = 50000
)

// azureHTTP owns only transport and authentication. azcore retains the credential
// cache, refresh, CAE challenges, replayable request retries, and Retry-After behavior.
type azureHTTP struct{ pipeline runtime.Pipeline }
type azureAccountHTTPClient struct {
	http     *azureHTTP
	endpoint *url.URL
}
type azureBlobHTTPClient struct {
	http     *azureHTTP
	endpoint *url.URL
}

func newAzureHTTP(
	endpoint string,
	credential azcore.TokenCredential,
	options *azcore.ClientOptions,
) (*azureHTTP, *url.URL, error) {
	u, err := url.Parse(endpoint)
	if err != nil {
		return nil, nil, err
	}
	if (u.Scheme != "https" && u.Scheme != "http") || u.Host == "" || u.User != nil {
		return nil, nil, fmt.Errorf("invalid Azure storage endpoint")
	}
	var perRetry []policy.Policy
	if credential != nil {
		// Store a challenged audience for future requests without racing concurrent transfers.
		var mu sync.RWMutex
		scope := azureStorageScope
		bearer := runtime.NewBearerTokenPolicy(
			credential,
			[]string{scope},
			&policy.BearerTokenOptions{
				AuthorizationHandler: policy.AuthorizationHandler{
					OnRequest: func(_ *policy.Request, authorize func(policy.TokenRequestOptions) error) error {
						mu.RLock()
						current := scope
						mu.RUnlock()
						return authorize(policy.TokenRequestOptions{Scopes: []string{current}})
					},
					OnChallenge: func(_ *policy.Request, response *http.Response, authorize func(policy.TokenRequestOptions) error) error {
						resource := azureChallengeResource(response.Header.Get("WWW-Authenticate"))
						if resource == "" {
							return fmt.Errorf("azure authentication challenge has no resource_id")
						}
						if !strings.HasSuffix(resource, "/.default") {
							resource = strings.TrimRight(resource, "/") + "/.default"
						}
						mu.Lock()
						scope = resource
						mu.Unlock()
						return authorize(policy.TokenRequestOptions{Scopes: []string{resource}})
					},
				},
			},
		)
		perRetry = append(perRetry, bearer)
	}
	return &azureHTTP{
		pipeline: runtime.NewPipeline(
			"wandb-core",
			"v0.0.0",
			runtime.PipelineOptions{PerRetry: perRetry},
			options,
		),
	}, u, nil
}

// Azure storage uses space- or comma-separated bearer parameters, optionally quoted.
func azureChallengeResource(challenge string) string {
	if !strings.HasPrefix(strings.ToLower(challenge), "bearer ") {
		return ""
	}
	for _, field := range strings.FieldsFunc(challenge[len("Bearer "):], func(r rune) bool { return r == ' ' || r == ',' }) {
		key, value, ok := strings.Cut(field, "=")
		if ok && strings.EqualFold(key, "resource_id") {
			value = strings.Trim(value, "\"")
			u, err := url.Parse(value)
			if err == nil && u.Scheme == "https" && u.Host != "" && u.User == nil &&
				u.RawQuery == "" &&
				u.Fragment == "" {
				return value
			}
		}
	}
	return ""
}

func newAzureAccountHTTPClient(
	endpoint string,
	credential azcore.TokenCredential,
	options *azcore.ClientOptions,
) (*azureAccountHTTPClient, error) {
	h, u, err := newAzureHTTP(endpoint, credential, options)
	if err != nil {
		return nil, err
	}
	return &azureAccountHTTPClient{http: h, endpoint: u}, nil
}

func newAzureBlobHTTPClient(
	endpoint string,
	credential azcore.TokenCredential,
	options *azcore.ClientOptions,
) (*azureBlobHTTPClient, error) {
	h, u, err := newAzureHTTP(endpoint, credential, options)
	if err != nil {
		return nil, err
	}
	return &azureBlobHTTPClient{http: h, endpoint: u}, nil
}

// Append decoded path components without path.Clean: repeated slashes and dot
// components are legal in object names. url.URL performs the escaping once.
func azureObjectURL(endpoint *url.URL, components ...string) *url.URL {
	u := *endpoint
	u.Path = strings.TrimSuffix(u.Path, "/") + "/" + strings.Join(components, "/")
	u.RawPath = ""
	return &u
}

func (c *azureAccountHTTPClient) NewBlobClient(container, name string) AzureBlobClient {
	return &azureBlobHTTPClient{http: c.http, endpoint: azureObjectURL(c.endpoint, container, name)}
}

func (c *azureAccountHTTPClient) DownloadFile(
	ctx context.Context,
	container, name string,
	file *os.File,
) (int64, error) {
	return c.NewBlobClient(container, name).DownloadFile(ctx, file)
}

func (c *azureBlobHTTPClient) WithVersionID(version string) (AzureBlobClient, error) {
	u := *c.endpoint
	query := u.Query()
	if version == "" {
		query.Del("versionid")
	} else {
		query.Set("versionid", version)
	}
	u.RawQuery = query.Encode()
	return &azureBlobHTTPClient{http: c.http, endpoint: &u}, nil
}

func (c *azureHTTP) do(
	ctx context.Context,
	method string,
	endpoint *url.URL,
	headers http.Header,
	body []byte,
) (*http.Response, error) {
	req, err := runtime.NewRequest(ctx, method, endpoint.String())
	if err != nil {
		return nil, err
	}
	if body != nil {
		if err := req.SetBody(streaming.NopCloser(bytes.NewReader(body)), ""); err != nil {
			return nil, err
		}
	}
	for key, values := range headers {
		req.Raw().Header[key] = append([]string(nil), values...)
	}
	req.Raw().Header.Set("x-ms-version", azureStorageAPIVersion)
	req.Raw().Header.Set("x-ms-date", time.Now().UTC().Format(http.TimeFormat))
	// In particular GET responses must stream; azcore otherwise buffers the body.
	runtime.SkipBodyDownload(req)
	response, err := c.pipeline.Do(req)
	if err != nil {
		if response != nil && response.Body != nil {
			response.Body.Close()
		}
		return nil, err
	}
	if response.StatusCode < 200 || response.StatusCode >= 300 {
		defer response.Body.Close()
		detail, _ := io.ReadAll(io.LimitReader(response.Body, 4096))
		return nil, &azureHTTPError{
			method: method, status: response.StatusCode,
			header: response.Header.Clone(), detail: strings.TrimSpace(string(detail)),
		}
	}
	return response, nil
}

// Retain the status and headers after closing error responses so range readers
// can distinguish the end of an object from a rejected or malformed request.
type azureHTTPError struct {
	method string
	status int
	header http.Header
	detail string
}

func (e *azureHTTPError) Error() string {
	return fmt.Sprintf(
		"azure %s: status %d (%s): %s",
		e.method,
		e.status,
		e.header.Get("x-ms-error-code"),
		e.detail,
	)
}

func (c *azureAccountHTTPClient) ListBlobs(
	ctx context.Context,
	container, prefix, marker string,
	versions bool,
) (AzureBlobPage, error) {
	u := azureObjectURL(c.endpoint, container)
	query := u.Query()
	query.Set("restype", "container")
	query.Set("comp", "list")
	query.Set("prefix", prefix)
	query.Set("maxresults", "5000")
	if marker != "" {
		query.Set("marker", marker)
	}
	if versions {
		query.Set("include", "versions")
	}
	u.RawQuery = query.Encode()
	response, err := c.http.do(
		ctx,
		http.MethodGet,
		u,
		http.Header{"Accept": {"application/xml"}},
		nil,
	)
	if err != nil {
		return AzureBlobPage{}, err
	}
	defer response.Body.Close()
	var page struct {
		XMLName xml.Name `xml:"EnumerationResults"`
		AzureBlobPage
	}
	if err := xml.NewDecoder(response.Body).Decode(&page); err != nil {
		return AzureBlobPage{}, fmt.Errorf("decode Azure blob listing: %w", err)
	}
	return page.AzureBlobPage, nil
}

// UnmarshalXML decodes names escaped by Azure when they contain characters
// that cannot appear in XML. Unmarked names may contain literal percent signs
// and must remain unchanged.
func (item *AzureBlobItem) UnmarshalXML(decoder *xml.Decoder, start xml.StartElement) error {
	var value struct {
		Name struct {
			Encoded bool   `xml:"Encoded,attr"`
			Content string `xml:",chardata"`
		} `xml:"Name"`
		VersionID string `xml:"VersionId"`
	}
	if err := decoder.DecodeElement(&value, &start); err != nil {
		return err
	}
	name := value.Name.Content
	if value.Name.Encoded {
		var err error
		name, err = url.QueryUnescape(name)
		if err != nil {
			return fmt.Errorf("decode Azure blob name: %w", err)
		}
	}
	item.Name, item.VersionID = name, value.VersionID
	return nil
}

func (c *azureBlobHTTPClient) GetProperties(ctx context.Context) (AzureBlobProperties, error) {
	response, err := c.http.do(ctx, http.MethodHead, c.endpoint, nil, nil)
	if err != nil {
		return AzureBlobProperties{}, err
	}
	defer response.Body.Close()
	size, err := strconv.ParseInt(response.Header.Get("Content-Length"), 10, 64)
	if err != nil || size < 0 {
		return AzureBlobProperties{}, fmt.Errorf("invalid Azure blob Content-Length")
	}
	return AzureBlobProperties{ETag: response.Header.Get("ETag"), ContentLength: size}, nil
}

func (c *azureBlobHTTPClient) DownloadFile(ctx context.Context, file *os.File) (int64, error) {
	properties, err := c.GetProperties(ctx)
	if err != nil {
		return 0, err
	}
	if properties.ContentLength > 0 && properties.ETag == "" {
		return 0, fmt.Errorf("azure blob response is missing ETag")
	}
	if err := file.Truncate(properties.ContentLength); err != nil {
		return 0, err
	}
	group, ctx := errgroup.WithContext(ctx)
	group.SetLimit(azureTransferConcurrency)
	for start := int64(0); start < properties.ContentLength; start += azureDownloadBlockSize {
		end := min(start+azureDownloadBlockSize, properties.ContentLength)
		group.Go(func() error { return c.downloadRange(ctx, file, start, end, properties) })
	}
	if err := group.Wait(); err != nil {
		return 0, err
	}
	return properties.ContentLength, nil
}

func (c *azureBlobHTTPClient) downloadRange(
	ctx context.Context,
	file *os.File,
	start, end int64,
	properties AzureBlobProperties,
) error {
	for attempt := 0; start < end; attempt++ {
		headers := http.Header{}
		headers.Set("Range", fmt.Sprintf("bytes=%d-%d", start, end-1))
		headers.Set("If-Match", properties.ETag)
		response, err := c.http.do(ctx, http.MethodGet, c.endpoint, headers, nil)
		if err != nil {
			return err
		}
		if response.StatusCode != http.StatusPartialContent ||
			!azureValidContentRange(
				response.Header.Get("Content-Range"),
				start,
				end-1,
				properties.ContentLength,
			) ||
			response.ContentLength != end-start {
			response.Body.Close()
			return fmt.Errorf("azure returned an invalid range response")
		}
		if etag := response.Header.Get("ETag"); etag != "" && etag != properties.ETag {
			response.Body.Close()
			return fmt.Errorf("azure blob changed during download")
		}
		copied, copyErr := io.CopyN(io.NewOffsetWriter(file, start), response.Body, end-start)
		response.Body.Close()
		start += copied
		if copyErr == nil {
			return nil
		}
		if ctx.Err() != nil {
			return ctx.Err()
		}
		var netErr net.Error
		if attempt >= 3 ||
			(!errors.Is(copyErr, io.EOF) && !errors.Is(copyErr, io.ErrUnexpectedEOF) && !errors.As(copyErr, &netErr)) {
			return copyErr
		}
	}
	return nil
}

func azureValidContentRange(value string, start, end, size int64) bool {
	return value == fmt.Sprintf("bytes %d-%d/%d", start, end, size)
}

func azureUploadHeaders(input http.Header, commit bool) http.Header {
	headers := input.Clone()
	if headers == nil {
		headers = make(http.Header)
	}
	// These describe the final blob, not the block-list XML body.
	if commit {
		for key, azureKey := range map[string]string{
			"Content-Type": "x-ms-blob-content-type", "Content-MD5": "x-ms-blob-content-md5",
			"Content-Encoding": "x-ms-blob-content-encoding", "Content-Language": "x-ms-blob-content-language",
			"Content-Disposition": "x-ms-blob-content-disposition", "Cache-Control": "x-ms-blob-cache-control",
		} {
			if value := headers.Get(key); value != "" {
				headers.Set(azureKey, value)
			}
			headers.Del(key)
		}
		headers.Del("x-ms-blob-type")
		headers.Set("Content-Type", "application/xml")
	} else {
		headers.Set("x-ms-blob-type", "BlockBlob")
	}
	headers.Del("Content-Length")
	return headers
}

func (c *azureBlobHTTPClient) UploadStream(
	ctx context.Context,
	body io.Reader,
	headers http.Header,
) (*http.Response, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if md5 := headers.Get("Content-MD5"); md5 != "" {
		if _, err := base64.StdEncoding.DecodeString(md5); err != nil {
			return nil, fmt.Errorf("invalid Azure content MD5: %w", err)
		}
	}
	// Buffer at most four blocks, and replay each from memory on HTTP retries.
	first := make([]byte, azureUploadBlockSize)
	n, err := io.ReadFull(body, first)
	if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
		return nil, err
	}
	if n < len(first) {
		return c.http.do(
			ctx,
			http.MethodPut,
			c.endpoint,
			azureUploadHeaders(headers, false),
			first[:n],
		)
	}
	return c.uploadBlocks(ctx, body, first, headers)
}

// uploadBlocks stages a bounded number of buffers at a time. The first buffer
// was already filled by UploadStream, and body begins at the next block.
func (c *azureBlobHTTPClient) uploadBlocks(
	ctx context.Context,
	body io.Reader,
	first []byte,
	headers http.Header,
) (*http.Response, error) {
	var nonce [16]byte
	if _, err := rand.Read(nonce[:]); err != nil {
		return nil, err
	}
	ids := make([]string, 0)
	buffers := make(chan []byte, azureTransferConcurrency)
	for range azureTransferConcurrency - 1 {
		buffers <- make([]byte, azureUploadBlockSize)
	}
	group, groupCtx := errgroup.WithContext(ctx)
	stage := func(buffer []byte) {
		idBytes := make([]byte, 20)
		copy(idBytes, nonce[:])
		binary.BigEndian.PutUint32(idBytes[16:], uint32(len(ids)))
		id := base64.StdEncoding.EncodeToString(idBytes)
		ids = append(ids, id)
		group.Go(func() error {
			defer func() { buffers <- buffer[:cap(buffer)] }()
			return c.stageBlock(groupCtx, id, buffer, headers)
		})
	}
	stage(first)
	var readErr error
	for {
		var buffer []byte
		select {
		case buffer = <-buffers:
		case <-groupCtx.Done():
			readErr = groupCtx.Err()
		}
		if readErr != nil {
			break
		}
		n, err := io.ReadFull(body, buffer)
		if err != nil && err != io.EOF && err != io.ErrUnexpectedEOF {
			readErr = err
			break
		}
		if n == 0 {
			break
		}
		if len(ids) == azureMaxBlocks {
			readErr = fmt.Errorf("azure upload exceeds %d blocks", azureMaxBlocks)
			break
		}
		stage(buffer[:n])
		if n < azureUploadBlockSize {
			break
		}
	}
	if err := group.Wait(); err != nil {
		return nil, err
	}
	if readErr != nil {
		return nil, readErr
	}
	return c.commitBlocks(ctx, ids, headers)
}

// stageBlock excludes headers describing the final object from each block.
func (c *azureBlobHTTPClient) stageBlock(
	ctx context.Context,
	id string,
	buffer []byte,
	headers http.Header,
) error {
	u := *c.endpoint
	query := u.Query()
	query.Set("comp", "block")
	query.Set("blockid", id)
	u.RawQuery = query.Encode()
	// Preserve access conditions and encryption settings, but do not apply the
	// full-object content checksum to an individual block.
	blockHeaders := headers.Clone()
	for _, key := range []string{"Content-MD5", "Content-Length", "x-ms-blob-type", "Content-Type", "Content-Encoding", "Content-Language", "Content-Disposition", "Cache-Control"} {
		blockHeaders.Del(key)
	}
	response, err := c.http.do(ctx, http.MethodPut, &u, blockHeaders, buffer)
	if response != nil {
		response.Body.Close()
	}
	return err
}

func (c *azureBlobHTTPClient) commitBlocks(
	ctx context.Context,
	ids []string,
	headers http.Header,
) (*http.Response, error) {
	payload, err := xml.Marshal(struct {
		XMLName xml.Name `xml:"BlockList"`
		Latest  []string `xml:"Latest"`
	}{Latest: ids})
	if err != nil {
		return nil, err
	}
	u := *c.endpoint
	query := u.Query()
	query.Set("comp", "blocklist")
	u.RawQuery = query.Encode()
	return c.http.do(ctx, http.MethodPut, &u, azureUploadHeaders(headers, true), payload)
}
