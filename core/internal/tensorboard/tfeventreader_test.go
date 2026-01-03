package tensorboard_test

import (
	"context"
	"encoding/binary"
	"os"
	"path/filepath"
	"slices"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/tensorboard/tbproto"
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

func corruptHeaderCRC(eventBytes []byte) []byte {
	corruptedBytes := slices.Clone(eventBytes)

	for i := range 4 {
		corruptedBytes[8+i] = 0
	}

	return corruptedBytes
}

func corruptEventCRC(eventBytes []byte) []byte {
	corruptedBytes := slices.Clone(eventBytes)

	for i := range 4 {
		corruptedBytes[len(corruptedBytes)-i-1] = 0
	}

	return corruptedBytes
}

var event1 = &tbproto.TFEvent{Step: 1}
var event2 = &tbproto.TFEvent{Step: 2}
var event3 = &tbproto.TFEvent{Step: 3}

func absoluteTmpdir(t *testing.T) paths.AbsolutePath {
	p, err := paths.Absolute(t.TempDir())
	require.NoError(t, err)
	return *p
}

type tfEventReaderTestContext struct {
	Dir    string // path for tfevents files
	Now    time.Time
	Reader *tensorboard.TFEventReader
}

type testStep interface {
	Do(t *testing.T, ctx *tfEventReaderTestContext)
}

// write returns a test step that writes a sequence of encoded events
// to a file, creating the file or replacing its contents.
func write(path string, events ...[]byte) testStep {
	return &testStepWrite{Path: path, Events: events}
}

// advanceTime returns a test step that moves the fake clock forward.
func advanceTime(duration time.Duration) testStep {
	return &testStepAdvanceTime{Duration: duration}
}

// nextEventNil returns a test step that makes a call to NextEvent
// and asserts that it returns (nil, nil).
func nextEventNil() testStep {
	return &testStepNextEventNil{}
}

// nextEventErr returns a test step that makes a call to NextEvent
// and asserts that it returns an error containing the given message.
func nextEventErr(message string) testStep {
	return &testStepNextEventErr{ErrContains: message}
}

// nextEventResult returns a test step that makes a call to NextEvent
// and asserts that it returns a specific event object.
func nextEventResult(event *tbproto.TFEvent) testStep {
	return &testStepNextEventResult{Event: event}
}

type testStepWrite struct {
	Path   string
	Events [][]byte
}

func (s *testStepWrite) Do(t *testing.T, ctx *tfEventReaderTestContext) {
	require.NoError(t, os.WriteFile(
		filepath.Join(string(ctx.Dir), s.Path),
		slices.Concat(s.Events...),
		os.ModePerm,
	))
}

type testStepAdvanceTime struct {
	Duration time.Duration
}

func (s *testStepAdvanceTime) Do(t *testing.T, ctx *tfEventReaderTestContext) {
	ctx.Now = ctx.Now.Add(s.Duration)
}

type testStepNextEventNil struct{}

func (s *testStepNextEventNil) Do(t *testing.T, ctx *tfEventReaderTestContext) {
	result, err := ctx.Reader.NextEvent(
		context.Background(),
		func(path *tensorboard.LocalOrCloudPath) {},
	)

	assert.Nil(t, result)
	assert.NoError(t, err)
}

type testStepNextEventErr struct {
	ErrContains string
}

func (s *testStepNextEventErr) Do(t *testing.T, ctx *tfEventReaderTestContext) {
	result, err := ctx.Reader.NextEvent(
		context.Background(),
		func(path *tensorboard.LocalOrCloudPath) {},
	)

	assert.Nil(t, result)
	assert.ErrorContains(t, err, s.ErrContains)
}

type testStepNextEventResult struct {
	Event *tbproto.TFEvent
}

func (s *testStepNextEventResult) Do(t *testing.T, ctx *tfEventReaderTestContext) {
	result, err := ctx.Reader.NextEvent(
		context.Background(),
		func(path *tensorboard.LocalOrCloudPath) {},
	)

	assert.NoError(t, err)
	assert.True(t, proto.Equal(s.Event, result))
}

// runTest executes a test defined by a sequence of test steps above.
func runTest(
	t *testing.T,
	logger *observability.CoreLogger,
	testSteps ...testStep,
) {
	ctx := &tfEventReaderTestContext{}

	tmpdir := absoluteTmpdir(t)
	ctx.Dir = string(tmpdir)

	tmpdirAsPath, err := tensorboard.ParseTBPath(ctx.Dir)
	require.NoError(t, err)

	ctx.Reader = tensorboard.NewTFEventReader(
		tmpdirAsPath,
		tensorboard.TFEventsFileFilter{},
		logger,
		func() time.Time { return ctx.Now },
	)
	defer ctx.Reader.Close()

	for _, step := range testSteps {
		step.Do(t, ctx)
	}
}

func TestReadsSequenceOfFiles(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)

	runTest(t, logger,
		write("tfevents.1.host", encodeEvent(event1), encodeEvent(event2)),
		write("tfevents.2.host"),
		write("tfevents.3.host", encodeEvent(event3)),
		nextEventResult(event1),
		nextEventResult(event2),
		nextEventResult(event3),
	)
}

func TestRetriesChecksumErrors(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)

	runTest(t, logger,
		write("tfevents.1.host",
			// Starting with a valid event helps test bufferStartOffset logic.
			encodeEvent(event1),
			corruptHeaderCRC(encodeEvent(event2))),
		write("tfevents.2.host",
			// The second file tests that we don't skip the current file
			// after a checksum error.
			encodeEvent(event3)),

		nextEventResult(event1),
		nextEventNil(), // corrupt header => rewinds

		write("tfevents.1.host",
			encodeEvent(event1),
			corruptEventCRC(encodeEvent(event2))),

		nextEventNil(), // corrupt payload => rewinds

		write("tfevents.1.host", encodeEvent(event1), encodeEvent(event2)),

		nextEventResult(event2),
		nextEventResult(event3),
	)

	assert.Contains(t, logs.String(), "unexpected header checksum")
	assert.Contains(t, logs.String(), "unexpected payload checksum")
}

func TestGivesUpOnChecksumErrorAfterTimeout(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)

	runTest(t, logger,
		write("tfevents.1.host", corruptHeaderCRC(encodeEvent(event1))),

		// Rewinds on a checksum error while within the timeout.
		nextEventNil(),
		nextEventNil(),
		advanceTime(5*time.Second),
		nextEventNil(),

		write("tfevents.1.host",
			encodeEvent(event1),
			corruptEventCRC(encodeEvent(event2))),
		nextEventResult(event1),

		// Test that the checksum error timer got reset after a success.
		advanceTime(time.Hour),
		nextEventNil(),
		advanceTime(45*time.Second),
		nextEventErr("unexpected payload checksum"),
	)
}
