package stream

import (
	"context"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gocloud.dev/blob"
	"gocloud.dev/blob/driver"
	"gocloud.dev/blob/fileblob"
	"gocloud.dev/gcerrors"

	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func bucketBackupSource(t *testing.T) (*os.File, int64, []*spb.Record) {
	t.Helper()
	directory := t.TempDir()
	records := []*spb.Record{
		{Num: 1},
		{Num: 2, RecordType: &spb.Record_History{History: &spb.HistoryRecord{
			Item: []*spb.HistoryItem{{Key: "large", ValueJson: `"` + strings.Repeat("x", 40000) + `"`}},
		}}},
	}
	writer, path := transactionlogtest.NewWriter(t, &transactionlogtest.WriterOptions{
		ParentDir: directory, FileName: "run.wandb", Records: records,
	})
	require.NoError(t, writer.Close())
	source, err := os.Open(path)
	require.NoError(t, err)
	t.Cleanup(func() { _ = source.Close() })
	info, err := source.Stat()
	require.NoError(t, err)
	return source, info.Size(), records
}

func TestTransactionLogBucketContents(t *testing.T) {
	source, size, expectedRecords := bucketBackupSource(t)
	root := t.TempDir()
	base, err := fileblob.OpenBucket(root, nil)
	require.NoError(t, err)
	bucket := blob.PrefixedBucket(base, "training// +%/")
	defer bucket.Close()

	key := "run-id/execution-id/run.wandb"

	require.NoError(t, uploadTransactionLogBackupToBucket(context.Background(), bucket, key, source, size))

	rawBucket, err := fileblob.OpenBucket(root, nil)
	require.NoError(t, err)
	defer rawBucket.Close()
	objectKey := "training// +%/" + key
	attrs, err := rawBucket.Attributes(context.Background(), objectKey)
	require.NoError(t, err)
	assert.Equal(t, "application/octet-stream", attrs.ContentType)
	raw, err := rawBucket.ReadAll(context.Background(), objectKey)
	require.NoError(t, err)
	require.NoError(t, os.Remove(source.Name()))
	readBackupRecords(t, raw, expectedRecords...)
}

func TestTransactionLogBucketRejectsNegativeSize(t *testing.T) {
	source, _, _ := bucketBackupSource(t)
	bucket, err := fileblob.OpenBucket(t.TempDir(), nil)
	require.NoError(t, err)
	defer bucket.Close()

	err = uploadTransactionLogBackupToBucket(context.Background(), bucket, "run.wandb", source, -1)

	require.Error(t, err)
	exists, err := bucket.Exists(context.Background(), "run.wandb")
	require.NoError(t, err)
	assert.False(t, exists)
}

func TestTransactionLogBucketStreamsCapturedPrefix(t *testing.T) {
	writer, original := newSnapshotWriter(t)
	input, stop := startSnapshotWriter(t, writer)
	first := &spb.Record{Uuid: "captured"}
	writeBackupRecord(t, input, writer, first)
	source, err := os.Open(original.Name())
	require.NoError(t, err)
	defer source.Close()
	require.NoError(t, writer.Flush())
	size, err := writer.Size()
	require.NoError(t, err)
	prefix, err := os.ReadFile(original.Name())
	require.NoError(t, err)
	writeBackupRecord(t, input, writer, &spb.Record{Uuid: "later"})
	stop()

	bucket, err := fileblob.OpenBucket(t.TempDir(), nil)
	require.NoError(t, err)
	defer bucket.Close()
	key := "run/execution/run.wandb"

	require.NoError(t, uploadTransactionLogBackupToBucket(context.Background(), bucket, key, source, size))

	raw, err := bucket.ReadAll(context.Background(), key)
	require.NoError(t, err)
	assert.Equal(t, prefix, raw)
	readBackupRecords(t, raw, first)
}

func TestTransactionLogBucketUploadsAfterWriteFailure(t *testing.T) {
	writer, source := newSnapshotWriter(t)
	input, _ := startSnapshotWriter(t, writer)
	input <- runwork.NoRequest(runwork.WorkFromRecord(&spb.Record{Uuid: "\xff"}))
	require.False(t, (<-writer.Chan()).IsSaved)
	record := &spb.Record{Uuid: "saved"}
	writeBackupRecord(t, input, writer, record)
	require.NoError(t, writer.Flush())
	size, err := writer.Size()
	require.NoError(t, err)
	initial, err := os.ReadFile(source.Name())
	require.NoError(t, err)

	bucket, err := fileblob.OpenBucket(t.TempDir(), nil)
	require.NoError(t, err)
	defer bucket.Close()
	key := "run/execution/run.wandb"

	require.NoError(t, uploadTransactionLogBackupToBucket(context.Background(), bucket, key, source, size))

	raw, err := bucket.ReadAll(context.Background(), key)
	require.NoError(t, err)
	assert.Equal(t, initial, raw)
	readBackupRecords(t, raw, record)
}

func TestTransactionLogBucketURL(t *testing.T) {
	for _, tc := range []struct {
		destination, scheme, host, prefix, account string
	}{
		{"s3://bucket", "s3", "bucket", "", ""},
		{"gs://bucket/a//%2E%2Eextra/%252F+plus", "gs", "bucket", "a//..extra/%2F+plus/", ""},
		{"azblob://container/a%2Fb?storage_account=myaccount", "azblob", "container", "a/b/", "myaccount"},
	} {
		t.Run(tc.destination, func(t *testing.T) {
			u, err := transactionLogBackupBucketURL(tc.destination)

			require.NoError(t, err)
			assert.Equal(t, tc.scheme, u.Scheme)
			assert.Equal(t, tc.host, u.Host)
			assert.Empty(t, u.Path)
			assert.Equal(t, tc.prefix, u.Query().Get("prefix"))
			assert.Equal(t, tc.account, u.Query().Get("storage_account"))
		})
	}
}

func TestTransactionLogBackupKey(t *testing.T) {
	for _, identity := range []string{"", ".", "..", "a/b", `a\b`, "a\x00b", "a\nb", string([]byte{0xff})} {
		_, err := transactionLogBackupKey(identity, "execution")

		require.Error(t, err)

		_, err = transactionLogBackupKey("run", identity)

		require.Error(t, err)
	}
	key, err := transactionLogBackupKey("a%b +c", "execution")

	require.NoError(t, err)
	assert.Equal(t, "a%b +c/execution/run.wandb", key)
}

// Only fault injection uses a driver; successful uploads exercise fileblob above.
type backupFaultBucket struct {
	driver.Bucket
	failWrite, failCommit bool
	cancel                context.CancelFunc
	truncate              string
	closed, canceledClose bool
}

func (b *backupFaultBucket) ErrorCode(error) gcerrors.ErrorCode { return gcerrors.Unknown }
func (b *backupFaultBucket) ErrorAs(error, any) bool            { return false }
func (b *backupFaultBucket) As(any) bool                        { return false }
func (b *backupFaultBucket) Close() error                       { return nil }
func (b *backupFaultBucket) NewTypedWriter(ctx context.Context, _ string, _ string, _ *driver.WriterOptions) (driver.Writer, error) {
	if b.truncate != "" {
		if err := os.Truncate(b.truncate, 0); err != nil {
			return nil, err
		}
	}
	return &backupFaultWriter{ctx: ctx, bucket: b}, nil
}

type backupFaultWriter struct {
	ctx    context.Context
	bucket *backupFaultBucket
}

func (w *backupFaultWriter) Write(p []byte) (int, error) {
	if w.bucket.failWrite {
		return 0, fmt.Errorf("PUT https://bucket.invalid/object?sig=top-secret: %w", io.ErrClosedPipe)
	}
	if w.bucket.cancel != nil {
		w.bucket.cancel()
		w.bucket.cancel = nil
	}
	return len(p), nil
}

func (w *backupFaultWriter) Close() error {
	w.bucket.closed = true
	w.bucket.canceledClose = w.ctx.Err() != nil
	if w.ctx.Err() != nil {
		return w.ctx.Err()
	}
	if w.bucket.failCommit {
		return io.ErrClosedPipe
	}
	return nil
}

func TestTransactionLogBucketFailureDoesNotCommit(t *testing.T) {
	for _, failure := range []string{"write", "source", "closed-source", "cancel", "commit"} {
		t.Run(failure, func(t *testing.T) {
			source, size, _ := bucketBackupSource(t)
			ctx, cancel := context.WithCancel(context.Background())
			defer cancel()
			fault := &backupFaultBucket{}
			switch failure {
			case "write":
				fault.failWrite = true
			case "source":
				fault.truncate = source.Name()
			case "closed-source":
				require.NoError(t, source.Close())
			case "cancel":
				fault.cancel = cancel
			case "commit":
				fault.failCommit = true
			}
			bucket := blob.NewBucket(fault)
			defer bucket.Close()

			err := uploadTransactionLogBackupToBucket(ctx, bucket, "run/execution/run.wandb", source, size)

			require.Error(t, err)
			assert.NotContains(t, err.Error(), "top-secret")
			assert.True(t, fault.closed)
			assert.Equal(t, failure != "commit", fault.canceledClose)
		})
	}
}

func TestTransactionLogBucketFileCommitFailure(t *testing.T) {
	source, size, _ := bucketBackupSource(t)
	root := t.TempDir()
	target := filepath.Join(root, "run", "execution", "run.wandb")
	require.NoError(t, os.MkdirAll(target, 0700))
	bucket, err := fileblob.OpenBucket(root, nil)
	require.NoError(t, err)
	defer bucket.Close()

	err = uploadTransactionLogBackupToBucket(context.Background(), bucket, "run/execution/run.wandb", source, size)

	require.Error(t, err)
	info, err := os.Stat(target)
	require.NoError(t, err)
	assert.True(t, info.IsDir())
}

func TestTransactionLogBucketRejectsInvalidDestination(t *testing.T) {
	for _, destination := range []string{
		"file://bucket", "s3:bucket", "s3:///path",
		"s3://user:secret@bucket/path", "s3://bucket:123/path", "s3://bucket/a#secret",
		"s3://bucket/a\nsecret", "s3://bucket/a%", "s3://bucket/a%00", "s3://bucket/%FF",
		"s3://bucket/a%2F..%2Fb", "s3://bucket/?prefix=secret", "gs://bucket/?storage_account=a",
		"azblob://bucket/?storage_account=", "azblob://bucket/?storage_account=a&storage_account=b",
		"azblob://bucket/?storage_account=a&key=secret", "azblob://bucket/?storage_account=secret%00",
		"azblob://bucket/?storage_account=%FF", "azblob://bucket/?storage_account=a&",
		"azblob://bucket/?storage_account=a;b",
	} {
		t.Run(destination, func(t *testing.T) {
			_, err := transactionLogBackupBucketURL(destination)

			if err == nil {
				t.Fatal("expected invalid destination")
			}
			if strings.Contains(err.Error(), "secret") {
				t.Fatal("validation exposed a secret")
			}
		})
	}
}
