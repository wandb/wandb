package backend

import (
	"sync"
	"time"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

type openedFile struct {
	f              fs.File
	pathName       string
	lastAccessTime *time.Time
}

func (f *openedFile) File() fs.File {
	return f.f
}

func (f *openedFile) Path() string {
	return f.pathName
}

type Stat struct {
	lck         sync.RWMutex
	current     nfs.FileHandle4
	handleStack []nfs.FileHandle4

	clientId uint64

	openedFiles map[uint32]*openedFile // stateid4.seqid => *openedFile

	seqId uint32
}

func (t *Stat) SetCurrentHandle(fh nfs.FileHandle4) {
	t.current = fh
}

func (t *Stat) CurrentHandle() nfs.FileHandle4 {
	t.lck.Lock()
	defer t.lck.Unlock()

	if t.current == nil {
		t.current = []byte{}
	}
	return t.current
}

func (t *Stat) PopHandle() (nfs.FileHandle4, bool) {
	t.lck.Lock()
	defer t.lck.Unlock()

	if len(t.handleStack) == 0 {
		return nil, false
	}

	size := len(t.handleStack)
	last := t.handleStack[size-1]
	t.handleStack = t.handleStack[:size-1]
	return last, true
}

func (t *Stat) PeekHandle() (nfs.FileHandle4, bool) {
	t.lck.Lock()
	defer t.lck.Unlock()

	if len(t.handleStack) == 0 {
		return nil, false
	}

	size := len(t.handleStack)
	return t.handleStack[size-1], true
}

func (t *Stat) PushHandle(item nfs.FileHandle4) {
	t.lck.Lock()
	defer t.lck.Unlock()

	t.handleStack = append(t.handleStack, item) // append handles the fact that t.handleStack may be nil
}

func (t *Stat) SetClientId(clientId uint64) {
	t.lck.Lock()
	defer t.lck.Unlock()

	t.clientId = clientId
}

func (t *Stat) ClientId() (uint64, bool) {
	return t.clientId, t.clientId > 0
}

func (t *Stat) nextSeqId() uint32 {
	if t.seqId <= 0 {
		t.seqId = 1000
	}
	t.seqId++
	return t.seqId
}

func (t *Stat) AddOpenedFile(pathName string, f fs.File) uint32 {
	t.lck.Lock()
	defer t.lck.Unlock()

	if t.openedFiles == nil {
		t.openedFiles = map[uint32]*openedFile{}
	}
	seqId := t.nextSeqId()
	now := time.Now()
	t.openedFiles[seqId] = &openedFile{
		pathName:       pathName,
		f:              f,
		lastAccessTime: &now,
	}
	return seqId
}

func (t *Stat) GetOpenedFile(seqId uint32) fs.FileOpenState {
	t.lck.RLock()
	defer t.lck.RUnlock()

	if t.openedFiles != nil {
		if of, found := t.openedFiles[seqId]; found {
			return of
		}
	}
	return nil
}

func (t *Stat) FindOpenedFiles(pathName string) []fs.FileOpenState {
	t.lck.RLock()
	defer t.lck.RUnlock()

	rs := []fs.FileOpenState{}
	if t.openedFiles != nil {
		for _, of := range t.openedFiles {
			if of.pathName == pathName {
				rs = append(rs, of)
			}
		}
	}

	return rs
}

func (t *Stat) RemoveOpenedFile(seqId uint32) fs.FileOpenState {
	t.lck.Lock()
	defer t.lck.Unlock()

	if t.openedFiles != nil {
		if of, found := t.openedFiles[seqId]; found {
			delete(t.openedFiles, seqId)
			return of
		}
	}
	return nil
}

func (t *Stat) CloseAndRemoveStallFiles() {
	t.lck.Lock()
	defer t.lck.Unlock()

	ttl := time.Minute * 5
	now := time.Now()
	seqs := []uint32{}
	for seqId, f := range t.openedFiles {
		if f.lastAccessTime.Add(ttl).Before(now) {
			seqs = append(seqs, seqId)
			if err := f.f.Close(); err != nil {
				log.Warnf("f.Close: %v", err)
			}
		}
	}

	if len(seqs) <= 0 {
		return
	}

	for _, seqId := range seqs {
		delete(t.openedFiles, seqId)
	}
}

func (t *Stat) CleanUp() {
	t.lck.Lock()
	defer t.lck.Unlock()

	log.Debugf("stat: cleanup()")
	t.current = []byte{}

	if t.handleStack != nil {
		t.handleStack = t.handleStack[0:0]
	}

	if t.openedFiles != nil {
		for _, of := range t.openedFiles {
			of.f.Close()
		}
		t.openedFiles = nil
	}
}
