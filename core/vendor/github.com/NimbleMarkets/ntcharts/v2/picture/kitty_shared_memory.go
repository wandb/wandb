package picture

import (
	"bytes"
	"fmt"
	"image"
	"sync"

	"github.com/NimbleMarkets/ntcharts/v2/internal/kittyshm"
	"github.com/charmbracelet/x/ansi/kitty"
)

// KittyMedium selects where a Kitty frame's bytes are transferred.
type KittyMedium int8

const (
	// KittyMediumDirect sends the configured PNG or RGBA format through the terminal.
	KittyMediumDirect KittyMedium = iota
	// KittyMediumSharedMemory sends raw RGBA through a named shared buffer.
	// Unsupported environments fall back to Direct with the configured format.
	KittyMediumSharedMemory
)

func (m KittyMedium) String() string {
	if m == KittyMediumSharedMemory {
		return "shm"
	}
	return "direct"
}

func normalizeKittyMedium(m KittyMedium) KittyMedium {
	if m != KittyMediumSharedMemory {
		return KittyMediumDirect
	}
	return m
}

// KittySharedMemorySupported reports whether this process can create shared buffers.
// Native callers must also know that the terminal shares the same local OS
// namespace and supports Kitty t=s; this function is not a terminal probe.
func KittySharedMemorySupported() bool { return kittyshm.Supported() }

func buildKittySharedMemoryAPC(img image.Image, id, cols, rows int, z ...int) (string, *kittyshm.Object, error) {
	b := img.Bounds()
	if b.Empty() {
		return "", nil, fmt.Errorf("empty shared-memory image")
	}
	obj, err := kittyshm.Create(4*b.Dx()*b.Dy(), func(dst []byte) error {
		writeKittyRGBA(dst, img)
		return nil
	})
	if err != nil {
		return "", nil, err
	}
	o := kittyRGBAOptions(b.Dx(), b.Dy(), id, cols, rows, z...)
	o.Transmission = kitty.SharedMemory
	o.Size = obj.Size
	var buf bytes.Buffer
	if err := encodeKittyGraphicsData(&buf, []byte(obj.Name), o); err != nil {
		_ = obj.Unlink()
		return "", nil, err
	}
	return buf.String(), obj, nil
}

// Commands run concurrently and may finish out of order. This state is shared
// by the model and its captured commands, so superseded commands cannot publish
// orphaned objects. Native submitted frames are retained until consumption;
// object creation caps their total size if the terminal stops reading.
type kittySharedState struct {
	mu        sync.Mutex
	seq       uint64
	object    *kittyshm.Object
	submitted bool
	retired   []*kittyshm.Object
}

func (s *kittySharedState) begin(seq uint64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq = seq
}

func (s *kittySharedState) replace(seq uint64, obj *kittyshm.Object) bool {
	s.mu.Lock()
	defer s.mu.Unlock()
	if seq != s.seq {
		_ = obj.Unlink()
		return false
	}
	if s.submitted {
		s.object.Retire()
		if !s.object.Done() {
			s.retired = append(s.retired, s.object)
		}
	} else {
		_ = s.object.Unlink()
	}
	kept := s.retired[:0]
	for _, old := range s.retired {
		if !old.Done() {
			kept = append(kept, old)
		}
	}
	clear(s.retired[len(kept):])
	s.retired = kept
	s.object, s.submitted = obj, false
	return true
}

func (s *kittySharedState) clear(seq uint64) {
	if s == nil {
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	s.seq = seq
	_ = s.object.Unlink()
	s.object, s.submitted = nil, false
	for _, old := range s.retired {
		_ = old.Unlink()
	}
	s.retired = nil
}

func (s *kittySharedState) submit(seq uint64, obj *kittyshm.Object) bool {
	if s == nil {
		return false
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.seq != seq || s.object != obj {
		return false
	}
	s.submitted = true
	return true
}
