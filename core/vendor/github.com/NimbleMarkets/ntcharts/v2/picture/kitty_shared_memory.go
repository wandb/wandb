package picture

import (
	"bytes"
	"encoding/base64"
	"fmt"
	"image"
	"runtime"
	"sync"
	"sync/atomic"

	"github.com/NimbleMarkets/ntcharts/v2/internal/kittyshm"
	"github.com/charmbracelet/x/ansi/kitty"
)

// KittyMedium selects where a Kitty frame's bytes are transferred.
type KittyMedium int8

const (
	// KittyMediumDirect sends the configured PNG or RGBA format through the terminal.
	KittyMediumDirect KittyMedium = iota
	// KittyMediumSharedMemory sends raw RGBA through a named shared buffer.
	// Unsupported environments, and native terminals that have not answered
	// QueryKittySupport's t=s query with OK, fall back to Direct with the
	// configured format.
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
// It is not a terminal probe: QueryKittySupport asks a native terminal whether
// it can read them.
func KittySharedMemorySupported() bool { return kittyshm.Supported() }

// kittySharedProbeID is the image ID used for the shared-memory query.
const kittySharedProbeID = kittyProbeID + 1

var (
	kittySharedCap   atomic.Int32 // KittyCapability of the t=s medium
	kittySharedProbe atomic.Pointer[kittyshm.Object]
)

// kittySharedUsable reports whether frames may use t=s. A browser terminal
// signals support by installing its registry; a native one must answer the query.
func kittySharedUsable() bool {
	return runtime.GOOS == "js" || KittyCapability(kittySharedCap.Load()) == KittyCapabilitySupported
}

// kittySharedProbeable reports whether this process has a medium to query.
func kittySharedProbeable() bool { return runtime.GOOS != "js" && kittyshm.Supported() }

// kittySharedQueryAPC returns a Kitty query (a=q) naming a one-pixel shared
// object, or "" when there is nothing to probe. Only a terminal that can read
// the object replies OK.
func kittySharedQueryAPC() string {
	if !kittySharedProbeable() {
		return ""
	}
	obj, err := kittyshm.Create(4, func([]byte) error { return nil })
	if err != nil {
		return ""
	}
	_ = kittySharedProbe.Swap(obj).Unlink()
	name := base64.StdEncoding.EncodeToString([]byte(obj.Name))
	return tmuxWrap(fmt.Sprintf("\x1b_Ga=q,t=s,f=32,s=1,v=1,S=4,i=%d;%s\x1b\\", kittySharedProbeID, name))
}

// recordKittySharedResponse resolves the shared-memory query. A late OK
// overrides the timeout, as in recordKittyResponse.
func recordKittySharedResponse(ok bool) {
	if ok {
		kittySharedCap.Store(int32(KittyCapabilitySupported))
	} else {
		kittySharedCap.CompareAndSwap(int32(KittyCapabilityUnknown), int32(KittyCapabilityUnsupported))
	}
	_ = kittySharedProbe.Swap(nil).Unlink()
}

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
