//go:build cloud_http

package filetransfer

import (
	"bytes"
	"context"
	"encoding/xml"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	awsretry "github.com/aws/aws-sdk-go-v2/aws/retry"
	v4 "github.com/aws/aws-sdk-go-v2/aws/signer/v4"
	"github.com/aws/aws-sdk-go-v2/config"
)

// s3HTTPClient deliberately keeps credential discovery and SigV4 in the AWS SDK,
// while implementing only the four storage reads needed by reference artifacts.
// Special S3 ARN and Express endpoints are not supported by this prototype.
type s3HTTPClient struct {
	http              cloudHTTPClient
	endpoint          *url.URL
	region            string
	signingName       string
	fips              bool
	dualStack         bool
	immutableHost     bool
	validateChecksums bool
}

func newS3HTTPClient(ctx context.Context, cfg *aws.Config) (*s3HTTPClient, error) {
	c := &s3HTTPClient{
		region:            cfg.Region,
		signingName:       "s3",
		validateChecksums: cfg.ResponseChecksumValidation != aws.ResponseChecksumValidationWhenRequired,
	}
	if err := c.configureRegion(ctx, cfg.ConfigSources); err != nil {
		return nil, err
	}
	endpoint, err := s3ConfiguredEndpoint(ctx, cfg)
	if err != nil {
		return nil, err
	}
	endpoint, err = c.resolveLegacyEndpoint(cfg, endpoint)
	if err != nil {
		return nil, err
	}
	if err := c.configureEndpoint(endpoint); err != nil {
		return nil, err
	}
	c.configureTransport(cfg)
	return c, nil
}

func (c *s3HTTPClient) configureRegion(ctx context.Context, sources []any) error {
	if c.region == "" {
		return fmt.Errorf("S3 region is not configured")
	}
	regionFIPS := strings.HasPrefix(c.region, "fips-") || strings.HasSuffix(c.region, "-fips")
	if regionFIPS {
		c.region = strings.TrimSuffix(strings.TrimPrefix(c.region, "fips-"), "-fips")
	}
	if !s3HostLabel(c.region) {
		return fmt.Errorf("invalid S3 region %q", c.region)
	}
	fips, err := s3FIPSFromConfig(ctx, sources)
	if err != nil {
		return err
	}
	c.fips = fips || regionFIPS
	c.dualStack, err = s3DualStackFromConfig(ctx, sources)
	return err
}

func s3FIPSFromConfig(ctx context.Context, sources []any) (bool, error) {
	for _, source := range sources {
		if p, ok := source.(interface {
			GetUseFIPSEndpoint(context.Context) (aws.FIPSEndpointState, bool, error)
		}); ok {
			value, found, err := p.GetUseFIPSEndpoint(ctx)
			if err != nil {
				return false, err
			}
			if found {
				return value == aws.FIPSEndpointStateEnabled, nil
			}
		}
	}
	return false, nil
}

func s3DualStackFromConfig(ctx context.Context, sources []any) (bool, error) {
	for _, source := range sources {
		if p, ok := source.(interface {
			GetUseDualStackEndpoint(context.Context) (aws.DualStackEndpointState, bool, error)
		}); ok {
			value, found, err := p.GetUseDualStackEndpoint(ctx)
			if err != nil {
				return false, err
			}
			if found {
				return value == aws.DualStackEndpointStateEnabled, nil
			}
		}
	}
	return false, nil
}

func s3ConfiguredEndpoint(ctx context.Context, cfg *aws.Config) (string, error) {
	ignore, _, err := config.GetIgnoreConfiguredEndpoints(ctx, cfg.ConfigSources)
	if err != nil {
		return "", err
	}
	if ignore {
		return "", nil
	}
	endpoint := aws.ToString(cfg.BaseEndpoint)
	// A global environment endpoint takes precedence over profile service endpoints.
	_, globalEnv := os.LookupEnv("AWS_ENDPOINT_URL")
	_, serviceEnv := os.LookupEnv("AWS_ENDPOINT_URL_S3")
	if globalEnv && !serviceEnv {
		return endpoint, nil
	}
	for _, source := range cfg.ConfigSources {
		if p, ok := source.(interface {
			GetServiceBaseEndpoint(context.Context, string) (string, bool, error)
		}); ok {
			value, found, err := p.GetServiceBaseEndpoint(ctx, "S3")
			if err != nil {
				return "", err
			}
			if found {
				return value, nil
			}
		}
	}
	return endpoint, nil
}

//nolint:staticcheck // Preserve compatibility with caller-supplied legacy AWS endpoint resolvers.
func (c *s3HTTPClient) resolveLegacyEndpoint(cfg *aws.Config, endpoint string) (string, error) {
	if cfg.EndpointResolverWithOptions == nil && cfg.EndpointResolver == nil {
		return endpoint, nil
	}
	var ep aws.Endpoint
	var err error
	if cfg.EndpointResolverWithOptions != nil {
		ep, err = cfg.EndpointResolverWithOptions.ResolveEndpoint("S3", c.region)
	} else {
		ep, err = cfg.EndpointResolver.ResolveEndpoint("S3", c.region)
	}
	if err != nil {
		return "", fmt.Errorf("resolve S3 endpoint: %w", err)
	}
	c.immutableHost = ep.HostnameImmutable
	if ep.SigningRegion != "" {
		c.region = ep.SigningRegion
	}
	if ep.SigningName != "" {
		c.signingName = ep.SigningName
	}
	return ep.URL, nil
}

func (c *s3HTTPClient) configureEndpoint(endpoint string) error {
	if endpoint == "" {
		c.endpoint = c.regionalEndpoint()
		return nil
	}
	if c.fips || c.dualStack {
		return fmt.Errorf("S3 custom endpoints cannot be combined with FIPS or dual-stack")
	}
	u, err := url.Parse(endpoint)
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil ||
		u.Fragment != "" {
		return fmt.Errorf("invalid S3 endpoint configuration")
	}
	c.endpoint = u
	return nil
}

func (c *s3HTTPClient) regionalEndpoint() *url.URL {
	service := "s3"
	if c.fips {
		service += "-fips"
	}
	if c.dualStack {
		service += ".dualstack"
	}
	host := service + "." + c.region + "." + s3PartitionDomain(c.region)
	if c.region == "aws-global" {
		c.region = "us-east-1"
		host = "s3.amazonaws.com"
		if c.fips || c.dualStack {
			host = service + ".us-east-1.amazonaws.com"
		}
	}
	return &url.URL{Scheme: "https", Host: host}
}

func (c *s3HTTPClient) configureTransport(cfg *aws.Config) {
	client := cfg.HTTPClient
	if client == nil {
		client = &http.Client{
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		}
	}
	maxAttempts := cfg.RetryMaxAttempts
	if cfg.Retryer != nil {
		maxAttempts = cfg.Retryer().MaxAttempts()
	}
	if maxAttempts <= 0 {
		maxAttempts = 3
	}
	c.http = cloudHTTPClient{
		client:        client,
		maxAttempts:   maxAttempts,
		retryResponse: s3RetryResponse,
		authorize:     c.authorizer(cfg.Credentials),
	}
}

func (c *s3HTTPClient) authorizer(provider aws.CredentialsProvider) func(*http.Request) error {
	signer := v4.NewSigner(func(o *v4.SignerOptions) { o.DisableURIPathEscaping = true })
	return func(req *http.Request) error {
		if provider == nil {
			return fmt.Errorf("S3 credentials provider is not configured")
		}
		credentials, err := provider.Retrieve(req.Context())
		if err != nil {
			return fmt.Errorf("retrieve S3 credentials: %w", err)
		}
		// Every operation is a GET with an empty body. Signing its actual hash also
		// supports HTTP endpoints used by S3-compatible storage.
		const emptySHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
		req.Header.Set("X-Amz-Content-Sha256", emptySHA256)
		return signer.SignHTTP(
			req.Context(),
			credentials,
			req,
			emptySHA256,
			c.signingName,
			c.region,
			time.Now(),
		)
	}
}

func s3PartitionDomain(region string) string {
	switch {
	case strings.HasPrefix(region, "cn-"):
		return "amazonaws.com.cn"
	case strings.HasPrefix(region, "us-iso-"):
		return "c2s.ic.gov"
	case strings.HasPrefix(region, "us-isob-"):
		return "sc2s.sgov.gov"
	case strings.HasPrefix(region, "eu-isoe-"):
		return "cloud.adc-e.uk"
	case strings.HasPrefix(region, "us-isof-"):
		return "csp.hci.ic.gov"
	case strings.HasPrefix(region, "eusc-"):
		return "amazonaws.eu"
	default:
		return "amazonaws.com"
	}
}

func s3HostLabel(value string) bool {
	if value == "" || value[0] == '-' || value[len(value)-1] == '-' {
		return false
	}
	for _, ch := range value {
		switch {
		case ch >= 'a' && ch <= 'z', ch >= '0' && ch <= '9', ch == '-':
		default:
			return false
		}
	}
	return true
}

func s3VirtualBucket(bucket string, allowDots bool) bool {
	if len(bucket) < 3 || len(bucket) > 63 || net.ParseIP(bucket) != nil {
		return false
	}
	if !allowDots && strings.Contains(bucket, ".") {
		return false
	}
	for _, label := range strings.Split(bucket, ".") {
		if !s3HostLabel(label) {
			return false
		}
	}
	return true
}

func (c *s3HTTPClient) objectURL(object S3Object, query url.Values) (*url.URL, error) {
	if object.Bucket == "" {
		return nil, fmt.Errorf("S3 bucket is empty")
	}
	if strings.ContainsAny(object.Bucket, ":/\\") || strings.HasSuffix(object.Bucket, "--x-s3") ||
		strings.HasSuffix(object.Bucket, ".mrap") ||
		strings.HasSuffix(object.Bucket, "--ol-s3") {
		return nil, fmt.Errorf(
			"S3 HTTP artifact client does not support ARN, Object Lambda, multi-region access point, or Express directory buckets",
		)
	}
	u := *c.endpoint
	prefix := strings.TrimSuffix(u.Path, "/")
	if !c.immutableHost && net.ParseIP(u.Hostname()) == nil &&
		s3VirtualBucket(object.Bucket, u.Scheme == "http") {
		u.Host = object.Bucket + "." + u.Host
	} else {
		prefix += "/" + object.Bucket
	}
	u.Path = prefix + "/" + object.Key
	// Do not clean keys: repeated slashes, dot segments, and literal percent signs
	// are object-name bytes. Escape once, and tell the signer not to escape again.
	u.RawPath = s3EscapePath(u.Path)
	q := u.Query()
	for key, values := range query {
		q[key] = values
	}
	if object.VersionID != "" {
		q.Set("versionId", object.VersionID)
	}
	u.RawQuery = q.Encode()
	return &u, nil
}

func s3EscapePath(path string) string {
	const hex = "0123456789ABCDEF"
	var b strings.Builder
	for i := 0; i < len(path); i++ {
		ch := path[i]
		if ch >= 'A' && ch <= 'Z' || ch >= 'a' && ch <= 'z' || ch >= '0' && ch <= '9' ||
			strings.ContainsRune("-._~/", rune(ch)) {
			b.WriteByte(ch)
		} else {
			b.WriteByte('%')
			b.WriteByte(hex[ch>>4])
			b.WriteByte(hex[ch&15])
		}
	}
	return b.String()
}

// getResponse leaves status handling to the caller, including range EOF (416).
func (c *s3HTTPClient) getResponse(
	ctx context.Context,
	object S3Object,
	query url.Values,
	headers http.Header,
) (*http.Response, error) {
	u, err := c.objectURL(object, query)
	if err != nil {
		return nil, err
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, u.String(), http.NoBody)
	if err != nil {
		return nil, err
	}
	if headers != nil {
		req.Header = headers.Clone()
	}
	return c.http.Do(req)
}

func (c *s3HTTPClient) get(
	ctx context.Context,
	object S3Object,
	query url.Values,
	headers http.Header,
) (*http.Response, error) {
	resp, err := c.getResponse(ctx, object, query, headers)
	if err != nil {
		return nil, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, cloudResponseError(resp)
	}
	return resp, nil
}

func (c *s3HTTPClient) GetObject(ctx context.Context, object S3Object) (io.ReadCloser, error) {
	headers := http.Header{"Accept-Encoding": {"identity"}}
	if c.validateChecksums {
		headers.Set("X-Amz-Checksum-Mode", "ENABLED")
	}
	resp, err := c.get(ctx, object, nil, headers)
	if err != nil {
		return nil, err
	}
	if c.validateChecksums {
		body, err := s3CheckedBody(resp)
		if err != nil {
			resp.Body.Close()
			return nil, err
		}
		return body, nil
	}
	return resp.Body, nil
}

func (c *s3HTTPClient) GetObjectETag(ctx context.Context, object S3Object) (string, error) {
	resp, err := c.get(
		ctx,
		object,
		url.Values{"attributes": {""}},
		http.Header{"X-Amz-Object-Attributes": {"ETag"}},
	)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	var result struct {
		ETag string `xml:"ETag"`
	}
	if err := xml.NewDecoder(resp.Body).Decode(&result); err != nil {
		return "", fmt.Errorf("decode S3 object attributes: %w", err)
	}
	if result.ETag == "" {
		return "", fmt.Errorf("S3 object attributes response has no ETag")
	}
	return result.ETag, nil
}

func (c *s3HTTPClient) ListObjects(
	ctx context.Context,
	bucket, prefix, token string,
) (S3ObjectPage, error) {
	q := url.Values{"list-type": {"2"}, "prefix": {prefix}, "encoding-type": {"url"}}
	if token != "" {
		q.Set("continuation-token", token)
	}
	resp, err := c.get(ctx, S3Object{Bucket: bucket}, q, nil)
	if err != nil {
		return S3ObjectPage{}, err
	}
	defer resp.Body.Close()
	var result struct {
		EncodingType string `xml:"EncodingType"`
		Contents     []struct {
			Key string `xml:"Key"`
		} `xml:"Contents"`
		IsTruncated bool   `xml:"IsTruncated"`
		NextToken   string `xml:"NextContinuationToken"`
	}
	if err := xml.NewDecoder(resp.Body).Decode(&result); err != nil {
		return S3ObjectPage{}, fmt.Errorf("decode S3 object listing: %w", err)
	}
	page := S3ObjectPage{Truncated: result.IsTruncated, NextToken: result.NextToken}
	for _, object := range result.Contents {
		key, err := s3DecodeName(object.Key, result.EncodingType)
		if err != nil {
			return S3ObjectPage{}, err
		}
		page.Keys = append(page.Keys, key)
	}
	return page, nil
}

func (c *s3HTTPClient) ListVersions(
	ctx context.Context,
	bucket, prefix, keyMarker, versionMarker string,
) (S3VersionPage, error) {
	q := url.Values{"versions": {""}, "prefix": {prefix}, "encoding-type": {"url"}}
	if keyMarker != "" {
		q.Set("key-marker", keyMarker)
	}
	if versionMarker != "" {
		q.Set("version-id-marker", versionMarker)
	}
	resp, err := c.get(ctx, S3Object{Bucket: bucket}, q, nil)
	if err != nil {
		return S3VersionPage{}, err
	}
	defer resp.Body.Close()
	var result struct {
		EncodingType string `xml:"EncodingType"`
		Versions     []struct {
			Key       string `xml:"Key"`
			VersionID string `xml:"VersionId"`
			ETag      string `xml:"ETag"`
		} `xml:"Version"`
		IsTruncated         bool   `xml:"IsTruncated"`
		NextKeyMarker       string `xml:"NextKeyMarker"`
		NextVersionIDMarker string `xml:"NextVersionIdMarker"`
	}
	if err := xml.NewDecoder(resp.Body).Decode(&result); err != nil {
		return S3VersionPage{}, fmt.Errorf("decode S3 version listing: %w", err)
	}
	nextKey, err := s3DecodeName(result.NextKeyMarker, result.EncodingType)
	if err != nil {
		return S3VersionPage{}, err
	}
	page := S3VersionPage{
		Truncated:           result.IsTruncated,
		NextKeyMarker:       nextKey,
		NextVersionIDMarker: result.NextVersionIDMarker,
	}
	for _, version := range result.Versions {
		key, err := s3DecodeName(version.Key, result.EncodingType)
		if err != nil {
			return S3VersionPage{}, err
		}
		page.Versions = append(
			page.Versions,
			S3ObjectVersion{Key: key, VersionID: version.VersionID, ETag: version.ETag},
		)
	}
	return page, nil
}

func s3DecodeName(value, encoding string) (string, error) {
	if encoding != "url" {
		return value, nil
	}
	decoded, err := url.PathUnescape(value)
	if err != nil {
		return "", fmt.Errorf("invalid URL encoding in S3 listing: %w", err)
	}
	return decoded, nil
}

// s3RetryResponse handles service error codes whose HTTP status alone does not
// indicate that retrying is appropriate, notably S3's HTTP 400 RequestTimeout.
// Reuse the retained AWS core retry policy's standard transient/throttle codes.
func s3RetryResponse(resp *http.Response) bool {
	if resp.StatusCode < 400 || resp.StatusCode >= 500 || resp.Body == nil {
		return false
	}
	original := resp.Body
	prefix, _ := io.ReadAll(io.LimitReader(original, 4096))
	resp.Body = struct {
		io.Reader
		io.Closer
	}{io.MultiReader(bytes.NewReader(prefix), original), original}
	var result struct {
		XMLName xml.Name `xml:"Error"`
		Code    string   `xml:"Code"`
	}
	if err := xml.Unmarshal(prefix, &result); err != nil {
		return false
	}
	_, transient := awsretry.DefaultRetryableErrorCodes[result.Code]
	_, throttled := awsretry.DefaultThrottleErrorCodes[result.Code]
	return transient || throttled
}
