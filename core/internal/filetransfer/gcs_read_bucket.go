//go:build cloud_http

package filetransfer

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/url"
	"slices"
	"strconv"
	"strings"

	"github.com/wandb/wandb/core/internal/observability"
)

// gcsReadBucket shares the artifact HTTP/auth transport while preserving the
// Go CDK key escaping used by TensorBoard's previous GCS bucket adapter.
type gcsReadBucket struct {
	transfer *GCSFileTransfer
	bucket   string
}

func newGCSReadBucket(
	ctx context.Context,
	bucket string,
	logger *observability.CoreLogger,
) (CloudReadBucket, error) {
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	if bucket == "" {
		return nil, errors.New("GCS bucket is empty")
	}
	if logger == nil {
		logger = observability.NewNoOpLogger()
	}
	ft := NewGCSFileTransfer(nil, logger, nil)
	// The Go CDK bare gs:// opener requested this scope. Artifact reads retain
	// their existing scope set independently.
	ft.authScopes = []string{"https://www.googleapis.com/auth/cloud-platform"}
	ft.SetupClient()
	if ft.client == nil {
		if ft.setupErr != nil {
			return nil, fmt.Errorf("open GCS bucket: %w", ft.setupErr)
		}
		return nil, errors.New("unable to set up GCS client")
	}
	return &gcsReadBucket{transfer: ft, bucket: bucket}, nil
}

func (b *gcsReadBucket) ListPage(
	ctx context.Context,
	prefix, token string,
) (CloudObjectPage, error) {
	var response struct {
		Items         []gcsObjectAttrs `json:"items"`
		NextPageToken string           `json:"nextPageToken"`
	}
	query := url.Values{
		"prefix":     {gcsBucketEscapeKey(prefix)},
		"maxResults": {"1000"},
		"fields":     {"items(name),nextPageToken"},
	}
	if token != "" {
		query.Set("pageToken", token)
	}
	if err := b.transfer.getJSON(
		ctx,
		b.transfer.objectURL(b.bucket, "", query),
		&response,
	); err != nil {
		return CloudObjectPage{}, err
	}
	page := CloudObjectPage{
		NextToken: response.NextPageToken,
		Keys:      make([]string, 0, len(response.Items)),
	}
	for _, item := range response.Items {
		page.Keys = append(page.Keys, gcsBucketUnescapeKey(item.Name))
	}
	slices.Sort(page.Keys)
	return page, nil
}

func (b *gcsReadBucket) NewRangeReader(
	ctx context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	if offset < 0 {
		return nil, errors.New("GCS range offset must not be negative")
	}
	if key == "" {
		return nil, errors.New("GCS object key is empty")
	}
	key = gcsBucketEscapeKey(key)
	// Fetch the latest metadata on every open, rather than retaining the first
	// generation forever: TensorBoard reopens growing/replaced event objects.
	var attrs gcsObjectAttrs
	if err := b.transfer.getJSON(
		ctx,
		b.transfer.objectURL(b.bucket, key, nil),
		&attrs,
	); err != nil {
		return nil, err
	}
	if generation, err := strconv.ParseInt(attrs.Generation, 10, 64); err != nil || generation < 0 {
		return nil, fmt.Errorf("invalid GCS object generation %q", attrs.Generation)
	}
	if attrs.Size < 0 {
		return nil, errors.New("negative GCS object size")
	}
	if attrs.ContentEncoding == "gzip" {
		reader, err := b.transfer.openGCSReader(ctx, b.bucket, key, &attrs)
		if err != nil {
			return nil, err
		}
		// TensorBoard offsets count decoded bytes. Gzip does not provide arbitrary
		// decoded-byte seeking, so stream from zero and discard the decoded prefix.
		if _, err := io.CopyN(io.Discard, reader, offset); err != nil {
			_ = reader.Close()
			if errors.Is(err, io.EOF) {
				return io.NopCloser(strings.NewReader("")), nil
			}
			return nil, err
		}
		return reader, nil
	}
	if offset >= attrs.Size {
		return io.NopCloser(strings.NewReader("")), nil
	}
	// The shared reader disables whole-object CRC verification for a nonzero
	// starting offset, but still pins generation and validates returned ranges.
	return b.transfer.openGCSRangeReader(ctx, b.bucket, key, &attrs, offset)
}

var gcsBucketKeyEscaper = strings.NewReplacer("\n", "__0xa__", "\r", "__0xd__", "../", "..__0x2f__")

func gcsBucketEscapeKey(key string) string { return gcsBucketKeyEscaper.Replace(key) }

// Go CDK's HexUnescape recognizes any __0xHEX__ rune, including existing object
// names that contain such sequences literally. Preserve that read-side behavior.
func gcsBucketUnescapeKey(key string) string {
	var result strings.Builder
	for pos := 0; pos < len(key); {
		if strings.HasPrefix(key[pos:], "__0x") {
			start := pos + 4
			if end := strings.Index(key[start:], "__"); end >= 0 {
				if value, err := strconv.ParseInt(key[start:start+end], 16, 32); err == nil {
					result.WriteRune(rune(value))
					pos = start + end + 2
					continue
				}
			}
		}
		result.WriteByte(key[pos])
		pos++
	}
	return result.String()
}
