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

	// The doubly-linked list of operations, sorted in ascending order
	// by startTime.
	//
	// Finish() removes an operation from the list, and using a doubly-linked
	// list makes that as cheap as possible.
	oldestOperation, newestOperation *WandbOperation

	// totalOperations is the size of the doubly-linked list of operations.
	totalOperations int
}

func NewOperations() *WandbOperations {
	return &WandbOperations{}
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

	if ops.newestOperation != nil {
		ops.newestOperation.next = op
		op.prev = ops.newestOperation
		ops.newestOperation = op
	} else {
		ops.oldestOperation = op
		ops.newestOperation = op
	}

	ops.totalOperations++
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
		TotalOperations: int64(ops.totalOperations),
	}

	op := ops.oldestOperation
	for i := 0; op != nil && i < maxOperationsToReturn; i++ {
		stats.Operations = append(stats.Operations, op.ToProto())
		op = op.next
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
	root   *WandbOperations // set of operations this belongs to
	parent *WandbOperation  // the parent operation if this is a subtask

	// Operations form a doubly-linked list sorted by start time.
	//
	// See docs in the WandbOperations struct.
	prev, next *WandbOperation

	// This operation's doubly-linked list of subtasks.
	//
	// The root mutex must be locked when using these fields.
	oldestChild, newestChild *WandbOperation

	// mu is locked for modifying this operation's state.
	//
	// It's not locked for modifying Prev, Next, oldestChild or newestChild.
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

	subtask := op.oldestChild
	for i := 0; subtask != nil && i < maxOperationsToReturn; i++ {
		proto.Subtasks = append(proto.Subtasks, subtask.ToProto())
		subtask = subtask.next
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
		parent:    op,
		desc:      desc,
		startTime: time.Now(),
	}

	if op.newestChild != nil {
		op.newestChild.next = subtask
		subtask.prev = op.newestChild
		op.newestChild = subtask
	} else {
		op.oldestChild = subtask
		op.newestChild = subtask
	}

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

	// Update our linked list siblings.
	if op.prev != nil {
		op.prev.next = op.next
	}
	if op.next != nil {
		op.next.prev = op.prev
	}

	// Update the linked list's parent.
	var oldestSibling, newestSibling **WandbOperation
	if op.parent != nil {
		oldestSibling = &op.parent.oldestChild
		newestSibling = &op.parent.newestChild
	} else {
		oldestSibling = &op.root.oldestOperation
		newestSibling = &op.root.newestOperation
		op.root.totalOperations--
	}

	if op == *oldestSibling {
		*oldestSibling = op.next
	}
	if op == *newestSibling {
		*newestSibling = op.prev
	}
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
		"%s / %s",
		bytesToShortString(doneBytes),
		bytesToShortString(totalBytes),
	)
}

func bytesToShortString(bytes int) string {
	switch {
	case bytes < (1 << 10):
		return fmt.Sprintf("%dB", bytes)
	case bytes < (1 << 20):
		return fmt.Sprintf("%.1fKB", float64(bytes)/(1<<10))
	case bytes < (1 << 30):
		return fmt.Sprintf("%.1fMB", float64(bytes)/(1<<20))
	default:
		return fmt.Sprintf("%.2fGB", float64(bytes)/(1<<30))
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
