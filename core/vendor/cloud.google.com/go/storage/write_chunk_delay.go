// Copyright 2026 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package storage

import (
	"sync"
	"time"
)

const (
	// writeChunkEWMAAlpha weights the newest chunk latency sample when
	// updating the baseline. 0.2 gives the baseline a memory of roughly the
	// last five chunks: long enough to ignore a single outlier, short enough
	// to follow a sustained change in link or backend speed within a few
	// chunks.
	writeChunkEWMAAlpha = 0.2

	// writeChunkTriggerMultiple is how far above the baseline a chunk must
	// land before the stream is considered slow. 2x is clearly outside normal
	// jitter for a healthy stream while still well below the cost of
	// re-attaching a new BidiWriteObject stream to the upload session.
	writeChunkTriggerMultiple = 2.0

	// baseWriteChunkMinDelay and perMiBWriteChunkMinDelay define the floor of
	// the rotation threshold: 50ms of fixed round-trip plus 10ms per MiB of
	// chunk, i.e. roughly what a healthy chunk takes on a ~1 Gbps link. The
	// floor keeps a very fast first chunk from producing a threshold that
	// ordinary jitter would trip.
	baseWriteChunkMinDelay   = 50 * time.Millisecond
	perMiBWriteChunkMinDelay = 10 * time.Millisecond
)

// writeChunkDelay tracks per-chunk upload latency for a gRPC resumable upload
// and decides when a BidiWriteObject stream has become slow enough to rotate.
//
// The threshold is writeChunkTriggerMultiple times an EWMA baseline of
// observed chunk latencies, clamped to [minDelay, maxDelay]. The first sample
// only seeds the baseline; it never triggers a rotation, because the first
// chunk on a fresh connection is routinely slower than steady state.
//
// resetWarmUp, recordLatency, and exceeds are safe to call on a nil receiver,
// which disables rotation.
type writeChunkDelay struct {
	mu       sync.Mutex
	minDelay time.Duration
	maxDelay time.Duration
	baseline time.Duration
	value    time.Duration
	warmedUp bool
}

// newWriteChunkDelay returns a writeChunkDelay for the given chunk size and
// Writer.ChunkTransferTimeout, or nil when chunkTransferTimeout <= 0.
//
// The threshold floor is baseWriteChunkMinDelay + perMiBWriteChunkMinDelay
// per MiB of chunk, capped at half the timeout so rotation always gets a
// chance to fire before the stall watchdog does. The ceiling is the timeout
// itself.
func newWriteChunkDelay(chunkSize int, chunkTransferTimeout time.Duration) *writeChunkDelay {
	if chunkTransferTimeout <= 0 {
		return nil
	}
	chunkMiB := float64(chunkSize) / float64(1024*1024)
	minDelay := baseWriteChunkMinDelay + time.Duration(chunkMiB*float64(perMiBWriteChunkMinDelay))
	if halfTimeout := chunkTransferTimeout / 2; minDelay > halfTimeout {
		minDelay = halfTimeout
	}
	// Only reachable for sub-millisecond timeouts; keep the invariant
	// 0 < minDelay < maxDelay so the clamp below is well defined.
	if minDelay <= 0 {
		minDelay = time.Millisecond
	}
	maxDelay := chunkTransferTimeout
	if maxDelay <= minDelay {
		maxDelay = minDelay + time.Millisecond
	}
	return &writeChunkDelay{
		minDelay: minDelay,
		maxDelay: maxDelay,
		value:    minDelay,
	}
}

// threshold returns the rotation threshold for the current baseline. Caller
// must hold d.mu.
func (d *writeChunkDelay) threshold() time.Duration {
	v := time.Duration(writeChunkTriggerMultiple * float64(d.baseline))
	return min(max(v, d.minDelay), d.maxDelay)
}

// resetWarmUp marks the current stream as warming up so the next sample
// updates the baseline without triggering rotation in exceeds or recordLatency.
// Safe to call on a nil receiver.
func (d *writeChunkDelay) resetWarmUp() {
	if d == nil {
		return
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	d.warmedUp = false
}

// recordLatency folds a completed chunk's latency into the baseline and
// reports whether that latency exceeded the threshold in effect before the
// update. The first sample after construction or resetWarmUp updates the
// baseline and never reports exceeded.
func (d *writeChunkDelay) recordLatency(latency time.Duration) bool {
	if d == nil {
		return false
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	exceeded := d.warmedUp && latency > d.value
	if d.baseline == 0 {
		d.baseline = latency
	} else {
		d.baseline = time.Duration(writeChunkEWMAAlpha*float64(latency) + (1-writeChunkEWMAAlpha)*float64(d.baseline))
	}
	d.value = d.threshold()
	d.warmedUp = true
	return exceeded
}

// exceeds reports whether latency is strictly greater than the current
// threshold. It is false until a sample has been recorded since construction
// or the last resetWarmUp.
func (d *writeChunkDelay) exceeds(latency time.Duration) bool {
	if d == nil {
		return false
	}
	d.mu.Lock()
	defer d.mu.Unlock()
	return d.warmedUp && latency > d.value
}
