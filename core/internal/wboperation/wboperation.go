// Package wboperation is used to track the progress and status of async tasks
// to provide feedback to the wandb user.
//
// The core abstraction is WandbOperation which represents a high level task,
// like an artifact upload. Operations can be broken into parallel subtasks,
// such as the multiple file uploads that are part of saving an artifact.
//
// A WandbOperation has an optional error status and progress indicator.
// The error status conveys the most recent problem encountered by the
// operation and the resulting operation status, like
// "retrying HTTP 500 error".
//
// Operation-aware code should accept a `*WandbOperation` parameter
// unless it already accepts a `context.Context`. If it has a `Context`,
// it should use the operation in it, if any.
//
// Nil values are allowed and are treated like no-ops. Code should never
// check whether *WandbOperation or *WandbOperations is nil.
package wboperation

import (
	"container/list"
	"context"
	"errors"
	"fmt"
	"sync"
	"time"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type contextKey int

const operationContextKey contextKey = iota
const maxOperationsToReturn = 10

// Get returns the operation in the context, or nil if there isn't one.
func Get(ctx context.Context) *WandbOperation {
	if ctx == nil {
		return nil
	}

	if value, ok := ctx.Value(operationContextKey).(*WandbOperation); ok {
		return value
	}

	return nil
}

// WandbOperations tracks the status and progress of ongoing operations
// in the wandb internal process.
//
// A nil pointer acts like a no-op, as if operation tracking is disabled.
type WandbOperations struct {
	// mu is locked when creating or removing operations or subtasks.
	mu sync.Mutex

	// operations is all operations sorted in ascending order by startTime.
	//
	// We use a doubly-linked list because operations are removed frequently
	// and in random order, and there may be a large number of them.
	operations list.List
}

func NewOperations() *WandbOperations {
	ops := &WandbOperations{}
	ops.operations.Init()
	return ops
}

// New starts a new operation with the given name.
//
// It is important to call Finish() on the operation once it is done.
//
// The description should be a present continuous verb phrase like
// "uploading artifact my-dataset". It should not start with a capital
// letter or end in punctuation.
func (ops *WandbOperations) New(desc string) *WandbOperation {
	if ops == nil {
		return nil
	}

	ops.mu.Lock()
	defer ops.mu.Unlock()

	op := &WandbOperation{
		root:      ops,
		desc:      desc,
		startTime: time.Now(),
	}

	op.subtasks.Init()
	op.sourceList = &ops.operations
	op.sourceNode = ops.operations.PushBack(op)

	return op
}

// ToProto returns a snapshot of the ongoing operations.
func (ops *WandbOperations) ToProto() *spb.OperationStats {
	if ops == nil {
		return &spb.OperationStats{}
	}

	ops.mu.Lock()
	defer ops.mu.Unlock()

	stats := &spb.OperationStats{
		TotalOperations: int64(ops.operations.Len()),
	}

	i := 0
	e := ops.operations.Front()
	for i < maxOperationsToReturn && e != nil {
		op := e.Value.(*WandbOperation)
		stats.Operations = append(stats.Operations, op.ToProto())

		i++
		e = e.Next()
	}

	return stats
}

// WandbOperation tracks the status and progress of one asynchronous task.
//
// This is typically an upload. Operations can have subtasks; see `Subtask`.
// An operation has a single status message (potentially empty) and progress
// message (potentially empty).
//
// A nil pointer acts like a no-op, as if operation tracking is disabled.
type WandbOperation struct {
	root *WandbOperations // set of operations this belongs to

	// sourceList is the list this operation is in.
	//
	// This may be the root list, or another operation's subtask list.
	sourceList *list.List

	// sourceNode is this operation's position in the sourceList.
	//
	// It is used to remove the operation from the list once it is finished.
	sourceNode *list.Element

	// subtasks is the list of this operation's subtasks sorted by startTime.
	//
	// Access is protected by the root mutex.
	subtasks list.List

	// mu is locked for modifying this operation's state.
	//
	// It's not locked for accessing `subtasks`.
	mu sync.Mutex

	isFinished  bool // whether Finish was called
	hasProgress bool // whether NewProgress was called

	desc        string    // short name for the operation
	startTime   time.Time // when the operation was created
	errorStatus string    // optional status message
	progress    string    // optional progress message (e.g. "3/5 files")
}

// ToProto returns a snapshot of the operation.
func (op *WandbOperation) ToProto() *spb.Operation {
	if op == nil {
		return &spb.Operation{}
	}

	op.mu.Lock()
	defer op.mu.Unlock()

	proto := &spb.Operation{
		Desc:           op.desc,
		RuntimeSeconds: time.Since(op.startTime).Seconds(),
		Progress:       op.progress,
		ErrorStatus:    op.errorStatus,
	}

	i := 0
	e := op.subtasks.Front()
	for i < maxOperationsToReturn && e != nil {
		subtask := e.Value.(*WandbOperation)
		proto.Subtasks = append(proto.Subtasks, subtask.ToProto())

		i++
		e = e.Next()
	}

	return proto
}

// ClearError clears the operation's error status.
//
// There should be one call to ClearError per call to a method that sets
// the operation error status.
func (op *WandbOperation) ClearError() {
	if op == nil {
		return
	}

	op.mu.Lock()
	defer op.mu.Unlock()
	op.errorStatus = ""
}

// MarkRetryingHTTPError sets the operation's error status.
//
// The `responseStatus` must be a string in the form "429 Too Many Requests",
// which is available as the Status field on an http.Response.
//
// There should be a corresponding call to `ClearError`.
func (op *WandbOperation) MarkRetryingHTTPError(responseStatus string) {
	if op == nil {
		return
	}

	op.mu.Lock()
	defer op.mu.Unlock()
	op.errorStatus = fmt.Sprintf("retrying HTTP %s", responseStatus)
}

// NewProgress creates a progress bar for the operation.
//
// Returns nil and an error if the operation already has a progress instance.
func (op *WandbOperation) NewProgress() (*WandbProgress, error) {
	if op == nil {
		return nil, nil
	}

	op.mu.Lock()
	defer op.mu.Unlock()

	if op.hasProgress {
		return nil, errors.New("operation already has a progress instance")
	}

	op.hasProgress = true
	return &WandbProgress{op}, nil
}

// Subtask declares a task representing a portion of the operation.
//
// A subtask is a high-level activity with a short description
// that's meaningful to a user. Subtasks are appropriate for operations
// with parts done in parallel.
//
// The description should be as concise as possible while making sense in
// the context of the parent operation. It should not start with a capital
// letter or end with punctuation.
//
// For example, uploading a file as part of an artifact can be a subtask,
// since the user is aware that an artifact consists of files and would be
// familiar with those files. Its description can just be the file name;
// the word "uploading" would be redundant.
//
// Making an HTTP request is not a subtask because it is an implementation
// detail, and therefore not important to a user.
func (op *WandbOperation) Subtask(desc string) *WandbOperation {
	if op == nil {
		return nil
	}

	op.root.mu.Lock()
	defer op.root.mu.Unlock()

	subtask := &WandbOperation{
		root:      op.root,
		desc:      desc,
		startTime: time.Now(),
	}

	subtask.subtasks.Init()
	subtask.sourceList = &op.subtasks
	subtask.sourceNode = op.subtasks.PushBack(subtask)

	return subtask
}

// Context returns a new context with this as its operation.
func (op *WandbOperation) Context(ctx context.Context) context.Context {
	if op == nil {
		return ctx
	}

	return context.WithValue(ctx, operationContextKey, op)
}

// Finish marks the operation as complete.
func (op *WandbOperation) Finish() {
	if op == nil {
		return
	}

	op.root.mu.Lock()
	defer op.root.mu.Unlock()

	if op.isFinished {
		return
	}

	op.isFinished = true
	op.sourceList.Remove(op.sourceNode)
}

// WandbProgress is a handle for setting the progress on an operation.
type WandbProgress struct {
	op *WandbOperation
}

func (p *WandbProgress) SetBytesOfTotal(doneBytes, totalBytes int) {
	if p == nil {
		return
	}

	p.op.mu.Lock()
	defer p.op.mu.Unlock()

	p.op.progress = fmt.Sprintf(
		"%s/%s",
		bytesToShortString(doneBytes),
		bytesToShortString(totalBytes),
	)
}

const (
	bytesPerKB = 1 << (10 * (iota + 1))
	bytesPerMB
	bytesPerGB
)

func bytesToShortString(bytes int) string {
	switch {
	case bytes < bytesPerKB:
		return fmt.Sprintf("%dB", bytes)
	case bytes < bytesPerMB:
		return fmt.Sprintf("%.1fKB", float64(bytes)/bytesPerKB)
	case bytes < bytesPerGB:
		return fmt.Sprintf("%.1fMB", float64(bytes)/bytesPerMB)
	default:
		return fmt.Sprintf("%.2fGB", float64(bytes)/bytesPerGB)
	}
}

func (p *WandbProgress) SetUnitsOfTotal(done, total int, unit string) {
	if p == nil {
		return
	}

	p.op.mu.Lock()
	defer p.op.mu.Unlock()

	p.op.progress = fmt.Sprintf("%d/%d %s", done, total, unit)
}
