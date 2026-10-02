//go:build linux || (darwin && cgo)

package kittyshm

import (
	"fmt"
	"os"
	"sync"
	"time"

	"golang.org/x/sys/unix"
)

// Bound unconsumed objects across models. An unavailable/full shared-memory
// store returns an error so picture can fall back to direct transmission.
const maxPendingBytes = 64 << 20

var pending struct {
	sync.Mutex
	bytes int
}

// Supported reports local OS support, not the remote terminal's capabilities.
func Supported() bool { return true }

// Create fills an exclusive, owner-only POSIX shared-memory object. The mapping
// and descriptor are closed before returning; the name stays valid for readers.
func Create(size int, fill func([]byte) error) (*Object, error) {
	if size <= 0 || size > maxPendingBytes || fill == nil {
		return nil, fmt.Errorf("invalid shared-memory buffer size or fill")
	}
	pending.Lock()
	if size > maxPendingBytes-pending.bytes {
		pending.Unlock()
		return nil, fmt.Errorf("shared-memory pending-byte limit reached")
	}
	pending.bytes += size
	pending.Unlock()
	var releaseOnce sync.Once
	release := func() { releaseOnce.Do(func() { pending.Lock(); pending.bytes -= size; pending.Unlock() }) }
	name := newName()
	f, err := openSHM(name, true)
	if err != nil {
		release()
		return nil, err
	}
	success := false
	defer func() {
		_ = f.Close()
		if !success {
			_ = unlinkSHM(name)
			release()
		}
	}()
	if err := f.Truncate(int64(size)); err != nil {
		return nil, err
	}
	if err := reserveBacking(f, size); err != nil {
		return nil, err
	}
	mem, err := unix.Mmap(int(f.Fd()), 0, size, unix.PROT_READ|unix.PROT_WRITE, unix.MAP_SHARED)
	if err != nil {
		return nil, err
	}
	defer func() {
		if mem != nil {
			_ = unix.Munmap(mem)
		}
	}()
	if err := fill(mem); err != nil {
		return nil, err
	}
	if err := unix.Munmap(mem); err != nil {
		return nil, err
	}
	mem = nil
	if err := f.Close(); err != nil {
		return nil, err
	}
	obj := &Object{Name: name, Size: size}
	obj.unlink = func() error {
		err := unlinkSHM(name)
		if err == nil || os.IsNotExist(err) {
			release()
			return nil
		}
		return err
	}
	var retireOnce sync.Once
	obj.retire = func() { retireOnce.Do(func() { retireNative(obj, 10*time.Millisecond, 5*time.Second) }) }
	success = true
	return obj, nil
}

// A submitted frame belongs to the terminal until it unlinks the object. Keep
// retired frames alive while the tty drains; reap abandoned transmissions after
// a grace period. Unlink still permits immediate cancellation/model cleanup.
func retireNative(obj *Object, interval, timeout time.Duration) {
	consumed := func() bool {
		if obj.Done() {
			return true
		}
		f, err := openSHM(obj.Name, false)
		if os.IsNotExist(err) {
			_ = obj.Unlink()
			return true
		}
		if err == nil {
			_ = f.Close()
		}
		return false
	}
	if consumed() {
		return
	}
	go func() {
		ticker := time.NewTicker(interval)
		defer ticker.Stop()
		timer := time.NewTimer(timeout)
		defer timer.Stop()
		for {
			select {
			case <-ticker.C:
				if consumed() {
					return
				}
			case <-timer.C:
				_ = obj.Unlink()
				return
			}
		}
	}()
}
