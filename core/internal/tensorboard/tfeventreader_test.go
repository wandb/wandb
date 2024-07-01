package tensorboard_test

import (
	"encoding/binary"
	"os"
	"path/filepath"
	"slices"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/paths"
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

var event1 = &tbproto.TFEvent{Step: 1}
var event2 = &tbproto.TFEvent{Step: 2}
var event3 = &tbproto.TFEvent{Step: 3}

func absoluteTmpdir(t *testing.T) paths.AbsolutePath {
	p, err := paths.Absolute(t.TempDir())
	require.NoError(t, err)
	return *p
}

func TestReadsSequenceOfFiles(t *testing.T) {
	tmpdir := absoluteTmpdir(t)
	require.NoError(t, os.WriteFile(
		filepath.Join(string(tmpdir), "tfevents.1.hostname"),
		slices.Concat(encodeEvent(event1), encodeEvent(event2)),
		os.ModePerm,
	))
	require.NoError(t, os.WriteFile(
		filepath.Join(string(tmpdir), "tfevents.2.hostname"),
		[]byte{},
		os.ModePerm,
	))
	require.NoError(t, os.WriteFile(
		filepath.Join(string(tmpdir), "tfevents.3.hostname"),
		encodeEvent(event3),
		os.ModePerm,
	))
	reader := tensorboard.NewTFEventReader(
		tmpdir,
		tensorboard.TFEventsFileFilter{},
		observability.NewNoOpLogger(),
	)

	result1, err1 := reader.NextEvent(func(path paths.AbsolutePath) {})
	result2, err2 := reader.NextEvent(func(path paths.AbsolutePath) {})
	result3, err3 := reader.NextEvent(func(path paths.AbsolutePath) {})
	result4, err4 := reader.NextEvent(func(path paths.AbsolutePath) {})

	assert.True(t, proto.Equal(event1, result1))
	assert.True(t, proto.Equal(event2, result2))
	assert.True(t, proto.Equal(event3, result3))
	assert.Nil(t, result4)

	assert.NoError(t, err1)
	assert.NoError(t, err2)
	assert.NoError(t, err3)
	assert.NoError(t, err4)
}
