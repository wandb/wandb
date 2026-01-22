package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/runworktest"
	"github.com/wandb/wandb/core/internal/stream"
)

func newUnsavedWork(value string) runwork.MaybeSavedWork {
	return runwork.MaybeSavedWork{
		Work:    &runworktest.NoopWork{Value: value},
		IsSaved: false,
	}
}

func newSavedWork(value string, num, offset int64) runwork.MaybeSavedWork {
	return runwork.MaybeSavedWork{
		Work:         &runworktest.NoopWork{Value: value},
		IsSaved:      true,
		SavedOffset:  offset,
		RecordNumber: num,
	}
}

func TestUnsavedWork_HeldInMemory(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 10,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))

	buf.Add(newUnsavedWork("item 1"))

	item := buf.Get().(*stream.FlowControlBufferWork)
	assert.Equal(t, "item 1", item.Work.(*runworktest.NoopWork).Value)
}

func TestSavedWork_HeldInMemoryThenOffloaded(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 2,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))

	buf.Add(newSavedWork("saved 1", 1, 10))
	buf.Add(newSavedWork("saved 2", 2, 20))
	buf.Add(newSavedWork("saved 3", 3, 30))
	buf.Add(newSavedWork("saved 4", 4, 40))

	item1 := buf.Get().(*stream.FlowControlBufferWork)
	item2 := buf.Get().(*stream.FlowControlBufferWork)
	item3 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	assert.Equal(t, "saved 1", item1.Work.(*runworktest.NoopWork).Value)
	assert.Equal(t, "saved 2", item2.Work.(*runworktest.NoopWork).Value)
	assert.EqualValues(t, 3, item3.InitialNumber)
	assert.EqualValues(t, 30, item3.InitialOffset)
	assert.EqualValues(t, 2, item3.Count)
}

func TestStopOffloading_PreventsOffloading(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 0,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))

	buf.Add(newSavedWork("saved 1", 1, 10))
	buf.StopOffloading()
	buf.Add(newSavedWork("saved 2", 2, 20))

	item1 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	item2 := buf.Get().(*stream.FlowControlBufferWork)
	assert.EqualValues(t, 1, item1.Count)
	assert.Equal(t, "saved 2", item2.Work.(*runworktest.NoopWork).Value)
}

func TestNonConsecutiveSavedWork_DifferentChunks(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 0,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))

	buf.Add(newSavedWork("saved 1", 1, 10))
	buf.Add(newSavedWork("saved 5", 5, 50))

	item1 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	item2 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	assert.EqualValues(t, 1, item1.Count)
	assert.EqualValues(t, 1, item1.InitialNumber)
	assert.EqualValues(t, 1, item2.Count)
	assert.EqualValues(t, 5, item2.InitialNumber)
}

func TestBackedUp_Offloads(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 2,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))

	buf.Add(newSavedWork("saved 1", 1, 10)) // In-memory.
	buf.Add(newSavedWork("saved 2", 2, 20)) // In-memory.
	buf.Add(newSavedWork("saved 3", 3, 20)) // Offloaded.
	item1 := buf.Get()
	item2 := buf.Get()
	buf.Add(newSavedWork("saved 4", 4, 30)) // Offloaded despite space.
	item3 := buf.Get().(*stream.FlowControlBufferSavedChunk)

	assert.IsType(t, &stream.FlowControlBufferWork{}, item1)
	assert.IsType(t, &stream.FlowControlBufferWork{}, item2)
	assert.EqualValues(t, 2, item3.Count)
}

func TestBackedUp_AfterCleared_StoresInMemory(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 2,
		Limit:        10,
	}, observabilitytest.NewTestLogger(t))
	buf.Add(newSavedWork("saved 1", 1, 10)) // In-memory.
	buf.Add(newSavedWork("saved 2", 2, 20)) // In-memory.
	buf.Add(newSavedWork("saved 3", 3, 20)) // Offloaded, now we're backed up.
	buf.Get()
	buf.Get()
	buf.Get() // Next Get() will block and clear backed-up state.

	assert.Nil(t, buf.TryGet())
	buf.Add(newSavedWork("saved 4", 4, 30))

	assert.IsType(t, &stream.FlowControlBufferWork{}, buf.Get())
}
