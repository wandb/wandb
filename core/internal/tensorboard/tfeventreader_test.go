package tensorboard_test

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
	"github.com/wandb/wandb/core/pkg/observability"
	"google.golang.org/protobuf/proto"
)

func encodeEvent(event *tbproto.TFEvent) []byte {
	eventBytes, _ := proto.Marshal(event)

	data := make([]byte, 0)
	data = binary.LittleEndian.AppendUint64(data, uint64(len(eventBytes)))
	data = binary.LittleEndian.AppendUint32(data, tensorboard.MaskedCRC32C(data))
	data = append(data, eventBytes...)
	data = binary.LittleEndian.AppendUint32(data, tensorboard.MaskedCRC32C(eventBytes))

	return data
}

var event1Bytes = encodeEvent(&tbproto.TFEvent{Step: 1})
var event2Bytes = encodeEvent(&tbproto.TFEvent{Step: 2})

func TestReadsSequenceOfFiles(t *testing.T) {
	tmpdir := t.TempDir()
	require.NoError(t, os.WriteFile(
		filepath.Join(tmpdir, "tfevents.1.hostname"),
		event1Bytes,
		os.ModePerm,
	))
	require.NoError(t, os.WriteFile(
		filepath.Join(tmpdir, "tfevents.2.hostname"),
		event2Bytes,
		os.ModePerm,
	))
	reader := tensorboard.NewTFEventReader(
		tmpdir,
		tensorboard.TFEventsFileFilter{},
		observability.NewNoOpLogger(),
	)

	event1, err1 := reader.NextEvent(func(path string) {})
	event2, err2 := reader.NextEvent(func(path string) {})
	event3, err3 := reader.NextEvent(func(path string) {})

	assert.NotNil(t, event1)
	assert.NotNil(t, event2)
	assert.Nil(t, event3)

	assert.NoError(t, err1)
	assert.NoError(t, err2)
	assert.NoError(t, err3)
}
