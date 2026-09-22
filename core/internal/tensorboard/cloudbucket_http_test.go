//go:build cloud_http

package tensorboard

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"io"
	"slices"
	"strings"
	"testing"
	"time"

	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
)

// snapshotBucket models HTTP response bodies: once opened, a reader cannot see
// a later object version, and EOF remains EOF until a new request is made.
type snapshotBucket struct {
	objects map[string][]byte
	offsets []int64
	closed  int
	page    func(context.Context, string, string) (filetransfer.CloudObjectPage, error)
}

func (b *snapshotBucket) ListPage(
	ctx context.Context,
	prefix, token string,
) (filetransfer.CloudObjectPage, error) {
	if b.page != nil {
		return b.page(ctx, prefix, token)
	}
	keys := make([]string, 0, len(b.objects))
	for key := range b.objects {
		if strings.HasPrefix(key, prefix) {
			keys = append(keys, key)
		}
	}
	slices.Sort(keys)
	return filetransfer.CloudObjectPage{Keys: keys}, nil
}

func (b *snapshotBucket) NewRangeReader(
	_ context.Context,
	key string,
	offset int64,
) (io.ReadCloser, error) {
	b.offsets = append(b.offsets, offset)
	data, ok := b.objects[key]
	if !ok {
		return nil, errors.New("object not found")
	}
	if offset > int64(len(data)) {
		return nil, io.EOF
	}
	return &snapshotReader{Reader: bytes.NewReader(slices.Clone(data[offset:])), bucket: b}, nil
}

type snapshotReader struct {
	Reader io.Reader // Deliberately no Seek: HTTP bodies must be reopened.
	bucket *snapshotBucket
}

func (r *snapshotReader) Read(p []byte) (int, error) { return r.Reader.Read(p) }
func (r *snapshotReader) Close() error {
	r.bucket.closed++
	return nil
}

func cloudEventBytes(step int64) []byte {
	payload, err := proto.Marshal(&tbproto.TFEvent{Step: step})
	if err != nil {
		panic(err)
	}
	data := binary.LittleEndian.AppendUint64(nil, uint64(len(payload)))
	data = binary.LittleEndian.AppendUint32(data, MaskedCRC32C(data))
	data = append(data, payload...)
	return binary.LittleEndian.AppendUint32(data, MaskedCRC32C(payload))
}

func newSnapshotEventReader(t *testing.T, bucket *snapshotBucket) *TFEventReader {
	t.Helper()
	path := &LocalOrCloudPath{CloudPath: &CloudPath{
		Scheme: "gs", BucketName: "test-bucket", Path: "run",
	}}
	reader := NewTFEventReader(
		path,
		TFEventsFileFilter{},
		observabilitytest.NewTestLogger(t),
		time.Now,
	)
	reader.tfeventsBucket = &cloudEventBucket{bucket: bucket, prefix: "run/"}
	t.Cleanup(reader.Close)
	return reader
}

func requireNextCloudStep(t *testing.T, reader *TFEventReader, step int64) {
	t.Helper()
	event, err := reader.NextEvent(context.Background(), func(*LocalOrCloudPath) {})
	require.NoError(t, err)
	require.NotNil(t, event)
	require.Equal(t, step, event.Step)
}

func requireNoCloudEvent(t *testing.T, reader *TFEventReader) {
	t.Helper()
	event, err := reader.NextEvent(context.Background(), func(*LocalOrCloudPath) {})
	require.NoError(t, err)
	require.Nil(t, event)
}

func TestCloudEventReaderGrowingObjectAndRotation(t *testing.T) {
	first, second := cloudEventBytes(1), cloudEventBytes(2)
	const name = "run/events.out.tfevents.1.host"
	bucket := &snapshotBucket{objects: map[string][]byte{name: first}}
	reader := newSnapshotEventReader(t, bucket)
	requireNextCloudStep(t, reader, 1)
	requireNoCloudEvent(t, reader) // Reaches EOF and releases the snapshot.
	require.Equal(t, 1, bucket.closed)

	// A partial append must be held until the complete record is available.
	bucket.objects[name] = slices.Concat(first, second[:10])
	requireNoCloudEvent(t, reader)
	bucket.objects[name] = slices.Concat(first, second)
	requireNextCloudStep(t, reader, 2)
	require.Equal(t, []int64{0, int64(len(first)), int64(len(first) + 10)}, bucket.offsets)

	// Rotation continues into the lexicographically next event file.
	bucket.objects["run/events.out.tfevents.2.host"] = cloudEventBytes(3)
	requireNextCloudStep(t, reader, 3)
	reader.Close()
	require.Equal(t, len(bucket.offsets), bucket.closed)
}

func TestCloudEventReaderReopensAfterChecksumMismatch(t *testing.T) {
	const name = "run/events.out.tfevents.1.host"
	good := cloudEventBytes(7)
	bad := slices.Clone(good)
	bad[8] ^= 0xff
	bucket := &snapshotBucket{objects: map[string][]byte{name: bad}}
	reader := newSnapshotEventReader(t, bucket)
	requireNoCloudEvent(t, reader)
	require.Equal(t, 1, bucket.closed)
	bucket.objects[name] = good
	requireNextCloudStep(t, reader, 7)
	require.Equal(t, []int64{0, 0}, bucket.offsets)
}

func TestCloudEventListingPagesAndPrefix(t *testing.T) {
	tokens := []string{}
	bucket := &snapshotBucket{page: func(
		_ context.Context, prefix, token string,
	) (filetransfer.CloudObjectPage, error) {
		require.Equal(t, "run/", prefix)
		tokens = append(tokens, token)
		switch token {
		case "":
			return filetransfer.CloudObjectPage{
				Keys:      []string{"run/checkpoint"},
				NextToken: "a",
			}, nil
		case "a":
			return filetransfer.CloudObjectPage{NextToken: "b"}, nil
		default:
			return filetransfer.CloudObjectPage{
				Keys: []string{"run/events.out.tfevents.9.host"},
			}, nil
		}
	}}
	name, err := nextTFEventsFile(context.Background(),
		&cloudEventBucket{bucket: bucket, prefix: "run/"}, "", TFEventsFileFilter{})
	require.NoError(t, err)
	require.Equal(t, "events.out.tfevents.9.host", name)
	require.Equal(t, []string{"", "a", "b"}, tokens)
}

func TestCloudEventListingRejectsInvalidPages(t *testing.T) {
	for _, test := range []struct {
		name string
		page filetransfer.CloudObjectPage
		err  string
	}{
		{"outside prefix", filetransfer.CloudObjectPage{Keys: []string{"outside/event"}}, "outside requested prefix"},
		{"repeated token", filetransfer.CloudObjectPage{NextToken: "same"}, "repeated its page token"},
	} {
		t.Run(test.name, func(t *testing.T) {
			bucket := &snapshotBucket{
				page: func(context.Context, string, string) (filetransfer.CloudObjectPage, error) {
					return test.page, nil
				},
			}
			_, err := (&cloudEventBucket{bucket: bucket, prefix: "run/"}).List().
				Next(context.Background())
			require.ErrorContains(t, err, test.err)
		})
	}
}

func TestCloudEventListingCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	bucket := &snapshotBucket{
		page: func(context.Context, string, string) (filetransfer.CloudObjectPage, error) {
			cancel()
			return filetransfer.CloudObjectPage{NextToken: "next"}, nil
		},
	}
	_, err := (&cloudEventBucket{bucket: bucket}).List().Next(ctx)
	require.ErrorIs(t, err, context.Canceled)
}
