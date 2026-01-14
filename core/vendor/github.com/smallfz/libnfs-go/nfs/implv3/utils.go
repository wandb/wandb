package implv3

import (
	"crypto/md5"
	"encoding/binary"
	"os"
	"path"
	"time"

	"github.com/smallfz/libnfs-go/nfs"
)

func getFileId(name string) uint64 {
	h := md5.New()
	h.Write([]byte(name))
	dat := h.Sum(nil)
	return binary.BigEndian.Uint64(dat[0:8])
}

func fileinfoToEntryPlus3(dir string, fi os.FileInfo) *nfs.EntryPlus3 {
	now := time.Now()

	ftype := nfs.FTYPE_NF3REG
	if fi.IsDir() {
		ftype = nfs.FTYPE_NF3DIR
	}

	name := path.Base(fi.Name())
	pathName := fi.Name()
	if len(dir) > 0 {
		pathName = path.Join(dir, name)
	}

	fileId := getFileId(pathName)

	return &nfs.EntryPlus3{
		FileId: fileId,
		Name:   name,
		Cookie: uint64(0),
		NameAttrs: &nfs.PostOpAttr{
			AttributesFollow: true,
			Attributes: &nfs.FileAttrs{
				Type:   ftype,
				Mode:   uint32(fi.Mode()),
				NLink:  4,
				Uid:    0,
				Gid:    0,
				Size:   uint64(fi.Size()),
				Used:   uint64(fi.Size()),
				Rdev:   nfs.SpecData{D1: 0, D2: 0},
				Fsid:   0,
				FileId: fileId,
				ATime:  nfs.MakeNfsTime(now),
				MTime:  nfs.MakeNfsTime(fi.ModTime()),
				CTime:  nfs.MakeNfsTime(fi.ModTime()),
			},
		},
		NameHandle: &nfs.PostOpFh3yes{
			HandleFollow: true,
			Handle:       []byte{},
		},
	}
}
