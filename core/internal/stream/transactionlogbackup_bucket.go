package stream

import (
	"context"
	"errors"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
	"unicode"
	"unicode/utf8"

	"gocloud.dev/blob"
	_ "gocloud.dev/blob/azureblob"
	_ "gocloud.dev/blob/gcsblob"
	_ "gocloud.dev/blob/s3blob"
	"gocloud.dev/gcerrors"
)

// uploadTransactionLogBackup succeeds only after the object is committed.
func uploadTransactionLogBackup(
	ctx context.Context,
	destination, runID, executionID string,
	source *os.File,
	size int64,
) (err error) {
	bucketURL, err := transactionLogBackupBucketURL(destination)
	if err != nil {
		return err
	}

	key, err := transactionLogBackupKey(runID, executionID)
	if err != nil {
		return err
	}

	bucket, err := blob.OpenBucket(ctx, bucketURL.String())
	if err != nil {
		// Provider errors can contain credential-bearing request URLs.
		return fmt.Errorf("open backup bucket: %s", gcerrors.Code(err))
	}

	defer func() {
		if closeErr := bucket.Close(); closeErr != nil && err == nil {
			err = fmt.Errorf("close backup bucket: %s", gcerrors.Code(closeErr))
		}
	}()

	return uploadTransactionLogBackupToBucket(ctx, bucket, key, source, size)
}

// transactionLogBackupBucketURL translates the validated path to Go Cloud's
// prefix parameter without cleaning object keys or passing other URL options.
func transactionLogBackupBucketURL(destination string) (*url.URL, error) {
	// Don't echo the destination in errors; it may contain secrets.
	invalid := errors.New("invalid transaction log backup destination; use an s3, gs, or azblob bucket URL")

	// Reject invalid UTF-8, control characters, and URL fragments.
	if !utf8.ValidString(destination) || strings.IndexFunc(destination, unicode.IsControl) >= 0 || strings.Contains(destination, "#") {
		return nil, invalid
	}

	// Accept only bucket URLs, not credentials, ports, or other schemes.
	u, err := url.Parse(destination)
	if err != nil || (u.Scheme != "s3" && u.Scheme != "gs" && u.Scheme != "azblob") ||
		!strings.HasPrefix(destination, u.Scheme+"://") || u.Opaque != "" || u.User != nil ||
		u.Host == "" || strings.IndexFunc(u.Host, func(r rune) bool {
		return !(r >= 'a' && r <= 'z' || r >= 'A' && r <= 'Z' || r >= '0' && r <= '9' || r == '.' || r == '_' || r == '-')
	}) >= 0 || !utf8.ValidString(u.Path) || strings.IndexFunc(u.Path, unicode.IsControl) >= 0 {
		return nil, invalid
	}

	// Check the decoded path so encoded dot segments can't bypass validation.
	for _, part := range strings.Split(u.Path, "/") {
		if part == "." || part == ".." {
			return nil, invalid
		}
	}

	// Reject malformed query parts before parsing the allowed Azure option.
	if u.RawQuery != "" {
		for _, part := range strings.Split(u.RawQuery, "&") {
			if part == "" || !strings.Contains(part, "=") {
				return nil, invalid
			}
		}
	}

	query, err := url.ParseQuery(u.RawQuery)
	if err != nil {
		return nil, invalid
	}

	// Don't pass arbitrary query options through to Go Cloud.
	for key, values := range query {
		if key != "storage_account" || u.Scheme != "azblob" || len(values) != 1 || values[0] == "" ||
			!utf8.ValidString(values[0]) || strings.IndexFunc(values[0], unicode.IsControl) >= 0 {
			return nil, invalid
		}
	}

	prefix := strings.TrimPrefix(u.Path, "/")
	if prefix != "" && !strings.HasSuffix(prefix, "/") {
		prefix += "/"
	}
	if prefix != "" {
		query.Set("prefix", prefix)
	}

	u.Path, u.RawPath = "", ""
	u.RawQuery = query.Encode()
	return u, nil
}

// transactionLogBackupKey builds the object key where the transaction log will be stored.
// IDs with unsafe characters ('.', '..', etc.) will return an error.
func transactionLogBackupKey(runID, executionID string) (string, error) {
	for _, component := range []string{runID, executionID} {
		if component == "" || component == "." || component == ".." ||
			!utf8.ValidString(component) || strings.ContainsAny(component, "/\\") {
			return "", errors.New("invalid transaction log backup identity")
		}

		for _, r := range component {
			if unicode.IsControl(r) {
				return "", errors.New("invalid transaction log backup identity")
			}
		}
	}
	return runID + "/" + executionID + "/run.wandb", nil
}

// uploadTransactionLogBackupToBucket keeps the real blob.Bucket test seam local
// to this implementation; production destinations are restricted above.
func uploadTransactionLogBackupToBucket(
	ctx context.Context,
	bucket *blob.Bucket,
	key string,
	source *os.File,
	size int64,
) error {
	if err := ctx.Err(); err != nil {
		return err
	}

	if size < 0 {
		return errors.New("invalid transaction log backup size")
	}

	writeCtx, cancel := context.WithCancel(ctx)
	defer cancel()
	// shortcut: default S3 parts limit streams to about 78 GiB; size parts when larger logs are needed.
	writer, err := bucket.NewWriter(writeCtx, key, &blob.WriterOptions{
		ContentType: "application/octet-stream",
	})
	if err != nil {
		// Provider errors can contain credential-bearing request URLs.
		return fmt.Errorf("open backup object: %s", gcerrors.Code(err))
	}

	// Close the source before the object's committing Close.
	abort := func(err error) error {
		cancel()
		_ = writer.Close()
		return fmt.Errorf("write backup log: %s", gcerrors.Code(err))
	}

	// Hide ReadFrom: Go Cloud may report bytes read even when writing fails.
	// CopyN ignores the error if that count equals the requested size.
	destination := struct{ io.Writer }{writer}
	reader := transactionLogBackupContextReader{ctx: writeCtx, reader: source}
	if _, err := io.CopyN(destination, reader, size); err != nil {
		cancel()
		_ = source.Close()
		return abort(err)
	}

	if err := source.Close(); err != nil {
		return abort(err)
	}
	if err := writeCtx.Err(); err != nil {
		return abort(err)
	}

	if err := writer.Close(); err != nil {
		return fmt.Errorf("commit backup object: %s", gcerrors.Code(err))
	}

	return nil
}
