package wboperation_test

import (
	"context"
	"errors"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/wboperation"
)

func TestOperationsToProto(t *testing.T) {
	ops := wboperation.NewOperations()

	_ = ops.New("op 1")
	op2 := ops.New("op 2")
	_ = ops.New("op 3")
	op2.Finish()

	proto := ops.ToProto()
	assert.EqualValues(t, 2, proto.TotalOperations)
	assert.Equal(t, "op 1", proto.Operations[0].Desc)
	assert.Equal(t, "op 3", proto.Operations[1].Desc)
}

func TestContext_NoOperation(t *testing.T) {
	assert.Nil(t, wboperation.Get(context.Background()))
}

func TestContext_WithOperation(t *testing.T) {
	ops := wboperation.NewOperations()

	op := ops.New("op")
	ctx := op.Context(context.Background())

	assert.Equal(t, op, wboperation.Get(ctx))
}

func TestFinishOldest(t *testing.T) {
	ops := wboperation.NewOperations()

	op1 := ops.New("first")
	_ = ops.New("second")
	op1.Finish()
	_ = ops.New("third")

	proto := ops.ToProto()
	assert.Len(t, proto.Operations, 2)
	assert.EqualValues(t, proto.TotalOperations, 2)
	assert.Equal(t, "second", proto.Operations[0].Desc)
	assert.Equal(t, "third", proto.Operations[1].Desc)
}

func TestFinishOldestSubtask(t *testing.T) {
	ops := wboperation.NewOperations()
	root := ops.New("root")

	op1 := root.Subtask("first")
	_ = root.Subtask("second")
	op1.Finish()
	_ = root.Subtask("third")

	proto := ops.ToProto()
	assert.Len(t, proto.Operations[0].Subtasks, 2)
	assert.EqualValues(t, proto.TotalOperations, 1) // just the root
	assert.Equal(t, "second", proto.Operations[0].Subtasks[0].Desc)
	assert.Equal(t, "third", proto.Operations[0].Subtasks[1].Desc)
}

func TestFinishNewest(t *testing.T) {
	ops := wboperation.NewOperations()

	_ = ops.New("first")
	ops.New("second").Finish()
	_ = ops.New("third")

	proto := ops.ToProto()
	assert.Len(t, proto.Operations, 2)
	assert.EqualValues(t, proto.TotalOperations, 2)
	assert.Equal(t, "first", proto.Operations[0].Desc)
	assert.Equal(t, "third", proto.Operations[1].Desc)
}

func TestFinishNewestSubtask(t *testing.T) {
	ops := wboperation.NewOperations()
	root := ops.New("root")

	_ = root.Subtask("first")
	root.Subtask("second").Finish()
	_ = root.Subtask("third")

	proto := ops.ToProto()
	assert.Len(t, proto.Operations[0].Subtasks, 2)
	assert.EqualValues(t, proto.TotalOperations, 1) // just the root
	assert.Equal(t, "first", proto.Operations[0].Subtasks[0].Desc)
	assert.Equal(t, "third", proto.Operations[0].Subtasks[1].Desc)
}

func TestHTTPError_NoMessage(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	op.MarkRetryingHTTPError(429, "429 Too Many Requests", "")

	proto := ops.ToProto()
	assert.Equal(t,
		"retrying HTTP 429 Too Many Requests",
		proto.Operations[0].ErrorStatus)
}

func TestHTTPError_WithMessage(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	op.MarkRetryingHTTPError(409, "409 Conflict", "run has been deleted")

	proto := ops.ToProto()
	assert.Equal(t,
		"retrying HTTP 409: run has been deleted",
		proto.Operations[0].ErrorStatus)
}

func TestGoError(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	op.MarkRetryingError(errors.New("test: example"))

	proto := ops.ToProto()
	assert.Equal(t, "retrying: test: example", proto.Operations[0].ErrorStatus)
}

func TestClearError(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	op.MarkRetryingHTTPError(429, "429 Too Many Requests", "")
	op.ClearError()

	proto := ops.ToProto()
	assert.Empty(t, proto.Operations[0].ErrorStatus)
}

func TestSubtask(t *testing.T) {
	ops := wboperation.NewOperations()

	op := ops.New("parent")
	_ = op.Subtask("child 1")
	subtask2 := op.Subtask("child 2")
	_ = op.Subtask("child 3")
	subtask2.Finish()

	proto := ops.ToProto()
	assert.Len(t, proto.Operations[0].Subtasks, 2)
	assert.Equal(t, "child 1", proto.Operations[0].Subtasks[0].Desc)
	assert.Equal(t, "child 3", proto.Operations[0].Subtasks[1].Desc)
}

func TestProgress_OnlyOneAllowed(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	progress1, err1 := op.NewProgress()
	progress2, err2 := op.NewProgress()

	assert.NotNil(t, progress1)
	assert.NoError(t, err1)
	assert.Nil(t, progress2)
	assert.ErrorContains(t, err2, "already has a progress instance")
}

func TestProgress_Bytes(t *testing.T) {
	ops := wboperation.NewOperations()
	opB := ops.New("bytes")
	opKB := ops.New("kilobytes")
	opMB := ops.New("megabytes")
	opGB := ops.New("gigabytes")

	progress, _ := opB.NewProgress()
	progress.SetBytesOfTotal(20, 47)
	progress, _ = opKB.NewProgress()
	progress.SetBytesOfTotal(1024, 4000)
	progress, _ = opMB.NewProgress()
	progress.SetBytesOfTotal(3333, 12<<20+345<<10)
	progress, _ = opGB.NewProgress()
	progress.SetBytesOfTotal(37<<20, 91<<30+123<<20)

	proto := ops.ToProto()
	assert.Equal(t, "20B/47B", proto.Operations[0].Progress)
	assert.Equal(t, "1.0KB/3.9KB", proto.Operations[1].Progress)
	assert.Equal(t, "3.3KB/12.3MB", proto.Operations[2].Progress)
	assert.Equal(t, "37.0MB/91.12GB", proto.Operations[3].Progress)
}

func TestProgress_ArbitraryUnits(t *testing.T) {
	ops := wboperation.NewOperations()
	op := ops.New("test operation")

	progress, _ := op.NewProgress()
	progress.SetUnitsOfTotal(37, 99, "bottles of beer")

	proto := ops.ToProto()
	assert.Equal(t, "37/99 bottles of beer", proto.Operations[0].Progress)
}
