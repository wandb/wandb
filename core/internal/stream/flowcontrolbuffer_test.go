package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type noopWork struct {
	runwork.SimpleScheduleMixin
	runwork.AlwaysAcceptMixin
	runwork.NoopProcessMixin

	Value string
}

func (w *noopWork) ToRecord() *spb.Record { return nil }
func (w *noopWork) DebugInfo() string     { return "noopWork" }

func newUnsavedWork(value string) runwork.MaybeSavedWork {
	return runwork.MaybeSavedWork{
		Work:    &noopWork{Value: value},
		IsSaved: false,
	}
}

func newSavedWork(value string, num int64, offset int64) runwork.MaybeSavedWork {
	return runwork.MaybeSavedWork{
		Work:         &noopWork{Value: value},
		IsSaved:      true,
		SavedOffset:  offset,
		RecordNumber: num,
	}
}

func TestUnsavedWork_HeldInMemory(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 10,
		Limit:        10,
	})

	buf.Add(newUnsavedWork("item 1"))

	item := buf.Get().(*stream.FlowControlBufferWork)
	assert.Equal(t, "item 1", item.Work.(*noopWork).Value)
}

func TestSavedWork_HeldInMemoryThenOffloaded(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 2,
		Limit:        10,
	})

	buf.Add(newSavedWork("saved 1", 1, 10))
	buf.Add(newSavedWork("saved 2", 2, 20))
	buf.Add(newSavedWork("saved 3", 3, 30))
	buf.Add(newSavedWork("saved 4", 4, 40))

	item1 := buf.Get().(*stream.FlowControlBufferWork)
	item2 := buf.Get().(*stream.FlowControlBufferWork)
	item3 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	assert.Equal(t, "saved 1", item1.Work.(*noopWork).Value)
	assert.Equal(t, "saved 2", item2.Work.(*noopWork).Value)
	assert.EqualValues(t, 3, item3.InitialNumber)
	assert.EqualValues(t, 30, item3.InitialOffset)
	assert.EqualValues(t, 2, item3.Count)
}

func TestNonConsecutiveSavedWork_DifferentChunks(t *testing.T) {
	buf := stream.NewFlowControlBuffer(stream.FlowControlParams{
		InMemorySize: 0,
		Limit:        10,
	})

	buf.Add(newSavedWork("saved 1", 1, 10))
	buf.Add(newSavedWork("saved 5", 5, 50))

	item1 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	item2 := buf.Get().(*stream.FlowControlBufferSavedChunk)
	assert.EqualValues(t, 1, item1.Count)
	assert.EqualValues(t, 1, item1.InitialNumber)
	assert.EqualValues(t, 1, item2.Count)
	assert.EqualValues(t, 5, item2.InitialNumber)
}
