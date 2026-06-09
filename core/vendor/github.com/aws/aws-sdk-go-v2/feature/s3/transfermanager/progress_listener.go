package transfermanager

import (
	"context"
	"sync/atomic"
)

// ObjectProgressListeners holds various "transfer progress" hooks that a caller can
// supply to receive progress updates for potentially long-running transfer
// manager operations.
//
// Progress listeners are invoked synchronously within the outer transfer
// operation. Callers SHOULD NOT perform long-lived operations in these hooks,
// such as submitting the progress snapshot to some other network agent.
type ObjectProgressListeners struct {
	ObjectTransferStart    []ObjectTransferStartListener
	ObjectBytesTransferred []ObjectBytesTransferredListener
	ObjectTransferComplete []ObjectTransferCompleteListener
	ObjectTransferFailed   []ObjectTransferFailedListener
}

// Register registers the input with all progress listener hooks that it implements.
//
// If the input does not implement a specific listener, it is a no-op for one
// instance. Callers should generally use compile-time type assertions to
// verify that their implementations satisfy the desired listener interfaces.
func (p *ObjectProgressListeners) Register(v any) {
	if l, ok := v.(ObjectTransferStartListener); ok {
		p.ObjectTransferStart = append(p.ObjectTransferStart, l)
	}
	if l, ok := v.(ObjectBytesTransferredListener); ok {
		p.ObjectBytesTransferred = append(p.ObjectBytesTransferred, l)
	}
	if l, ok := v.(ObjectTransferCompleteListener); ok {
		p.ObjectTransferComplete = append(p.ObjectTransferComplete, l)
	}
	if l, ok := v.(ObjectTransferFailedListener); ok {
		p.ObjectTransferFailed = append(p.ObjectTransferFailed, l)
	}
}

// Copy creates a clone where all hook lists are deep-copied.
func (p *ObjectProgressListeners) Copy() ObjectProgressListeners {
	objectTransferStart := make([]ObjectTransferStartListener, len(p.ObjectTransferStart))
	objectBytesTransferred := make([]ObjectBytesTransferredListener, len(p.ObjectBytesTransferred))
	objectTransferComplete := make([]ObjectTransferCompleteListener, len(p.ObjectTransferComplete))
	objectTransferFailed := make([]ObjectTransferFailedListener, len(p.ObjectTransferFailed))
	copy(objectTransferStart, p.ObjectTransferStart)
	copy(objectBytesTransferred, p.ObjectBytesTransferred)
	copy(objectTransferComplete, p.ObjectTransferComplete)
	copy(objectTransferFailed, p.ObjectTransferFailed)
	return ObjectProgressListeners{
		ObjectTransferStart:    objectTransferStart,
		ObjectBytesTransferred: objectBytesTransferred,
		ObjectTransferComplete: objectTransferComplete,
		ObjectTransferFailed:   objectTransferFailed,
	}
}

// ObjectTransferStartListener is invoked when a single-object transfer begins.
type ObjectTransferStartListener interface {
	OnObjectTransferStart(context.Context, *ObjectTransferStartEvent)
}

// ObjectTransferStartEvent is the event payload for object transfer start.
type ObjectTransferStartEvent struct {
	Input      any
	TotalBytes int64
}

// ObjectBytesTransferredListener is invoked on progress in a single-object
// transfer.
//
// This hook is ALWAYS invoked at least once for an operation, even if the
// operation only does one intermediate transfer (e.g. an object read that does
// not actually need multiple range/part requests).
type ObjectBytesTransferredListener interface {
	OnObjectBytesTransferred(context.Context, *ObjectBytesTransferredEvent)
}

// ObjectBytesTransferredEvent is the event payload for object bytes
// transferred.
type ObjectBytesTransferredEvent struct {
	Input            any
	BytesTransferred int64
	TotalBytes       int64
}

// ObjectTransferCompleteListener is invoked when a single-object transfer
// completes without error.
type ObjectTransferCompleteListener interface {
	OnObjectTransferComplete(context.Context, *ObjectTransferCompleteEvent)
}

// ObjectTransferCompleteEvent is the event payload for object transfer
// complete.
type ObjectTransferCompleteEvent struct {
	Input            any
	Output           any
	BytesTransferred int64
	TotalBytes       int64
}

// ObjectTransferFailedListener is invoked when a single-object transfer fails.
//
// This hook is only invoked for overall operation failure.
type ObjectTransferFailedListener interface {
	OnObjectTransferFailed(context.Context, *ObjectTransferFailedEvent)
}

// ObjectTransferFailedEvent is the event payload for object transfer failure.
type ObjectTransferFailedEvent struct {
	Input            any
	Error            error
	BytesTransferred int64
	TotalBytes       int64
}

func (p *ObjectProgressListeners) emitObjectTransferStart(ctx context.Context, event *ObjectTransferStartEvent) {
	for _, l := range p.ObjectTransferStart {
		l.OnObjectTransferStart(ctx, event)
	}
}

func (p *ObjectProgressListeners) emitObjectBytesTransferred(ctx context.Context, event *ObjectBytesTransferredEvent) {
	for _, l := range p.ObjectBytesTransferred {
		l.OnObjectBytesTransferred(ctx, event)
	}
}

func (p *ObjectProgressListeners) emitObjectTransferComplete(ctx context.Context, event *ObjectTransferCompleteEvent) {
	for _, l := range p.ObjectTransferComplete {
		l.OnObjectTransferComplete(ctx, event)
	}
}

func (p *ObjectProgressListeners) emitObjectTransferFailed(ctx context.Context, event *ObjectTransferFailedEvent) {
	for _, l := range p.ObjectTransferFailed {
		l.OnObjectTransferFailed(ctx, event)
	}
}

// reusable single-object progress event emitter
// used for implementations of:
//   - GetObject
//   - PutObject
//   - DownloadObject
type singleObjectProgressEmitter struct {
	Listeners ObjectProgressListeners

	input            any
	totalBytes       int64
	bytesTransferred atomic.Int64
}

func (e *singleObjectProgressEmitter) Start(ctx context.Context, in any, total int64) {
	e.input = in
	e.totalBytes = total
	e.Listeners.emitObjectTransferStart(ctx, &ObjectTransferStartEvent{
		Input:      in,
		TotalBytes: total,
	})
}

func (e *singleObjectProgressEmitter) BytesTransferred(ctx context.Context, transferred int64) {
	bytesTransferred := e.bytesTransferred.Add(transferred)
	e.Listeners.emitObjectBytesTransferred(ctx, &ObjectBytesTransferredEvent{
		Input:            e.input,
		TotalBytes:       e.totalBytes,
		BytesTransferred: bytesTransferred,
	})
}

func (e *singleObjectProgressEmitter) Complete(ctx context.Context, out any) {
	e.Listeners.emitObjectTransferComplete(ctx, &ObjectTransferCompleteEvent{
		Input:            e.input,
		TotalBytes:       e.totalBytes,
		BytesTransferred: e.bytesTransferred.Load(),
		Output:           out,
	})
}

func (e *singleObjectProgressEmitter) Failed(ctx context.Context, err error) {
	e.Listeners.emitObjectTransferFailed(ctx, &ObjectTransferFailedEvent{
		Input:            e.input,
		TotalBytes:       e.totalBytes,
		BytesTransferred: e.bytesTransferred.Load(),
		Error:            err,
	})
}

// DirectoryProgressListeners holds various "directory transfer progress" hooks that a caller can
// supply to receive progress updates for potentially long-running transfer
// manager operations.
//
// Directory Progress listeners are invoked synchronously within the outer directory transfer
// operation. Callers SHOULD NOT perform long-lived operations in these hooks,
// such as submitting the progress snapshot to some other network agent.
type DirectoryProgressListeners struct {
	ObjectsTransferStart    []ObjectsTransferStartListener
	ObjectsTransferred      []ObjectsTransferredListener
	ObjectsTransferComplete []ObjectsTransferCompleteListener
	ObjectsTransferFailed   []ObjectsTransferFailedListener
}

// Register registers the input with all progress listener hooks that it implements.
//
// If the input does not implement a specific listener, it is a no-op for one
// instance. Callers should generally use compile-time type assertions to
// verify that their implementations satisfy the desired listener interfaces.
func (p *DirectoryProgressListeners) Register(v any) {
	if l, ok := v.(ObjectsTransferStartListener); ok {
		p.ObjectsTransferStart = append(p.ObjectsTransferStart, l)
	}
	if l, ok := v.(ObjectsTransferredListener); ok {
		p.ObjectsTransferred = append(p.ObjectsTransferred, l)
	}
	if l, ok := v.(ObjectsTransferCompleteListener); ok {
		p.ObjectsTransferComplete = append(p.ObjectsTransferComplete, l)
	}
	if l, ok := v.(ObjectsTransferFailedListener); ok {
		p.ObjectsTransferFailed = append(p.ObjectsTransferFailed, l)
	}
}

// Copy creates a clone where all hook lists are deep-copied.
func (p *DirectoryProgressListeners) Copy() DirectoryProgressListeners {
	objectsTransferStart := make([]ObjectsTransferStartListener, len(p.ObjectsTransferStart))
	objectsTransferred := make([]ObjectsTransferredListener, len(p.ObjectsTransferred))
	objectsTransferComplete := make([]ObjectsTransferCompleteListener, len(p.ObjectsTransferComplete))
	objectsTransferFailed := make([]ObjectsTransferFailedListener, len(p.ObjectsTransferFailed))
	copy(objectsTransferStart, p.ObjectsTransferStart)
	copy(objectsTransferred, p.ObjectsTransferred)
	copy(objectsTransferComplete, p.ObjectsTransferComplete)
	copy(objectsTransferFailed, p.ObjectsTransferFailed)
	return DirectoryProgressListeners{
		ObjectsTransferStart:    objectsTransferStart,
		ObjectsTransferred:      objectsTransferred,
		ObjectsTransferComplete: objectsTransferComplete,
		ObjectsTransferFailed:   objectsTransferFailed,
	}
}

// ObjectsTransferStartListener is invoked when a directory transfer begins.
type ObjectsTransferStartListener interface {
	OnObjectsTransferStart(context.Context, *ObjectsTransferStartEvent)
}

// ObjectsTransferStartEvent is the event payload for directory transfer start.
type ObjectsTransferStartEvent struct {
	Input any
}

// ObjectsTransferredListener is invoked on progress in a directory
// transfer.
//
// This hook is ALWAYS invoked exactly once for a single object transfer
type ObjectsTransferredListener interface {
	OnObjectsTransferred(context.Context, *ObjectsTransferredEvent)
}

// ObjectsTransferredEvent is the event payload for object bytes/counts
// transferred.
type ObjectsTransferredEvent struct {
	Input              any
	BytesTransferred   int64
	ObjectsTransferred int64
}

// ObjectsTransferCompleteListener is invoked when a directory transfer
// completes without error.
type ObjectsTransferCompleteListener interface {
	OnObjectsTransferComplete(context.Context, *ObjectsTransferCompleteEvent)
}

// ObjectsTransferCompleteEvent is the event payload for objects transfer
// complete.
type ObjectsTransferCompleteEvent struct {
	Input              any
	Output             any
	BytesTransferred   int64
	ObjectsTransferred int64
}

// ObjectsTransferFailedListener is invoked when a directory transfer fails.
//
// This hook is only invoked for overall operation failure.
type ObjectsTransferFailedListener interface {
	OnObjectsTransferFailed(context.Context, *ObjectsTransferFailedEvent)
}

// ObjectsTransferFailedEvent is the event payload for objects transfer failure.
type ObjectsTransferFailedEvent struct {
	Input              any
	Error              error
	BytesTransferred   int64
	ObjectsTransferred int64
}

func (p *DirectoryProgressListeners) emitObjectsTransferStart(ctx context.Context, event *ObjectsTransferStartEvent) {
	for _, l := range p.ObjectsTransferStart {
		l.OnObjectsTransferStart(ctx, event)
	}
}

func (p *DirectoryProgressListeners) emitObjectsTransferred(ctx context.Context, event *ObjectsTransferredEvent) {
	for _, l := range p.ObjectsTransferred {
		l.OnObjectsTransferred(ctx, event)
	}
}

func (p *DirectoryProgressListeners) emitObjectsTransferComplete(ctx context.Context, event *ObjectsTransferCompleteEvent) {
	for _, l := range p.ObjectsTransferComplete {
		l.OnObjectsTransferComplete(ctx, event)
	}
}

func (p *DirectoryProgressListeners) emitObjectsTransferFailed(ctx context.Context, event *ObjectsTransferFailedEvent) {
	for _, l := range p.ObjectsTransferFailed {
		l.OnObjectsTransferFailed(ctx, event)
	}
}

// reusable directory progress event emitter
// used for implementations of:
//   - DirectoryUpload
//   - DirectoryDownload
type directoryObjectsProgressEmitter struct {
	Listeners DirectoryProgressListeners

	input              any
	bytesTransferred   atomic.Int64
	objectsTransferred atomic.Int64
}

func (e *directoryObjectsProgressEmitter) Start(ctx context.Context, in any) {
	e.input = in
	e.Listeners.emitObjectsTransferStart(ctx, &ObjectsTransferStartEvent{
		Input: in,
	})
}

func (e *directoryObjectsProgressEmitter) ObjectsTransferred(ctx context.Context, transferred int64) {
	bytesTransferred := e.bytesTransferred.Add(transferred)
	objectsTransferred := e.objectsTransferred.Add(1)
	e.Listeners.emitObjectsTransferred(ctx, &ObjectsTransferredEvent{
		Input:              e.input,
		BytesTransferred:   bytesTransferred,
		ObjectsTransferred: objectsTransferred,
	})
}

func (e *directoryObjectsProgressEmitter) Complete(ctx context.Context, out any) {
	e.Listeners.emitObjectsTransferComplete(ctx, &ObjectsTransferCompleteEvent{
		Input:              e.input,
		BytesTransferred:   e.bytesTransferred.Load(),
		ObjectsTransferred: e.objectsTransferred.Load(),
		Output:             out,
	})
}

func (e *directoryObjectsProgressEmitter) Failed(ctx context.Context, in any, err error) {
	e.Listeners.emitObjectsTransferFailed(ctx, &ObjectsTransferFailedEvent{
		Input:              in,
		BytesTransferred:   e.bytesTransferred.Load(),
		ObjectsTransferred: e.objectsTransferred.Load(),
		Error:              err,
	})
}
