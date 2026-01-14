package nfs

import (
	"fmt"
	"time"
)

/* nfsstat3 */
const (
	NFS3_OK             = uint32(0)
	NFS3ERR_PERM        = uint32(1)
	NFS3ERR_NOENT       = uint32(2)
	NFS3ERR_IO          = uint32(5)
	NFS3ERR_NXIO        = uint32(6)
	NFS3ERR_ACCES       = uint32(13)
	NFS3ERR_EXIST       = uint32(17)
	NFS3ERR_XDEV        = uint32(18)
	NFS3ERR_NODEV       = uint32(19)
	NFS3ERR_NOTDIR      = uint32(20)
	NFS3ERR_ISDIR       = uint32(21)
	NFS3ERR_INVAL       = uint32(22)
	NFS3ERR_FBIG        = uint32(27)
	NFS3ERR_NOSPC       = uint32(28)
	NFS3ERR_ROFS        = uint32(30)
	NFS3ERR_MLINK       = uint32(31)
	NFS3ERR_NAMETOOLONG = uint32(63)
	NFS3ERR_NOTEMPTY    = uint32(66)
	NFS3ERR_DQUOT       = uint32(69)
	NFS3ERR_STALE       = uint32(70)
	NFS3ERR_REMOTE      = uint32(71)
	NFS3ERR_BADHANDLE   = uint32(10001)
	NFS3ERR_NOT_SYNC    = uint32(10002)
	NFS3ERR_BAD_COOKIE  = uint32(10003)
	NFS3ERR_NOTSUPP     = uint32(10004)
	NFS3ERR_TOOSMALL    = uint32(10005)
	NFS3ERR_SERVERFAULT = uint32(10006)
	NFS3ERR_BADTYPE     = uint32(10007)
	NFS3ERR_JUKEBOX     = uint32(10008)
)

const (
	ProcVoid        = uint32(0)
	ProcGetAttr     = uint32(1)
	ProcSetAttr     = uint32(2)
	ProcLookup      = uint32(3)
	ProcAccess      = uint32(4)
	ProcReadLink    = uint32(5)
	ProcRead        = uint32(6)
	ProcWrite       = uint32(7)
	ProcCreate      = uint32(8)
	ProcMkdir       = uint32(9)
	ProcSymlink     = uint32(10)
	ProcMknod       = uint32(11)
	ProcRemove      = uint32(12)
	ProcRmdir       = uint32(13)
	ProcRename      = uint32(14)
	ProcLink        = uint32(15)
	ProcReaddir     = uint32(16)
	ProcReaddirPlus = uint32(17)
	ProcFsStat      = uint32(18)
	ProcFsInfo      = uint32(19)
	ProcPathConf    = uint32(20)
	ProcCommit      = uint32(21)
)

func Proc3Name(proc uint32) string {
	switch proc {
	case ProcVoid:
		return "void"
	case ProcGetAttr:
		return "getattr"
	case ProcSetAttr:
		return "setattr"
	case ProcLookup:
		return "lookup"
	case ProcAccess:
		return "access"
	case ProcReadLink:
		return "readlink"
	case ProcRead:
		return "read"
	case ProcWrite:
		return "write"
	case ProcCreate:
		return "create"
	case ProcMkdir:
		return "mkdir"
	case ProcSymlink:
		return "symlink"
	case ProcMknod:
		return "mknod"
	case ProcRemove:
		return "remove"
	case ProcRmdir:
		return "rmdir"
	case ProcRename:
		return "rename"
	case ProcLink:
		return "link"
	case ProcReaddir:
		return "readdir"
	case ProcReaddirPlus:
		return "readdirplus"
	case ProcFsStat:
		return "fsstat"
	case ProcFsInfo:
		return "fsinfo"
	case ProcPathConf:
		return "pathconf"
	case ProcCommit:
		return "commit"
	}
	return fmt.Sprintf("%d", proc)
}

/* rpc1813: ftype3 */
const (
	FTYPE_NF3REG = uint32(iota + 1)
	FTYPE_NF3DIR
	FTYPE_NF3BLK
	FTYPE_NF3CHR
	FTYPE_NF3LNK
	FTYPE_NF3SOCK
	FTYPE_NF3FIFO
)

/* specdata3 */
type SpecData struct {
	D1 uint32
	D2 uint32
}

type NFSTime struct {
	Seconds     uint32
	NanoSeconds uint32
}

func MakeNfsTime(t time.Time) NFSTime {
	return NFSTime{
		Seconds: uint32(t.Unix()),
	}
}

type FileAttrs struct {
	Type   uint32 /* ftype3 */
	Mode   uint32
	NLink  uint32
	Uid    uint32
	Gid    uint32
	Size   uint64
	Used   uint64
	Rdev   SpecData
	Fsid   uint64
	FileId uint64
	ATime  NFSTime
	MTime  NFSTime
	CTime  NFSTime
}

type PostOpAttr struct {
	AttributesFollow bool
	Attributes       *FileAttrs
}

type Fh3 struct {
	Opaque []byte
}

const (
	FSF3_LINK        = uint32(0x0001)
	FSF3_SYMLINK     = uint32(0x0002)
	FSF3_HOMOGENEOUS = uint32(0x0008)
	FSF3_CANSETTIME  = uint32(0x0010)
)

type FSINFO3resok struct {
	ObjAttrs    *PostOpAttr
	Rtmax       uint32
	Rtpref      uint32
	Rtmult      uint32
	Wtmax       uint32
	Wtpref      uint32
	Wtmult      uint32
	Dtpref      uint32
	MaxFileSize uint64
	TimeDelta   NFSTime
	Properties  uint32
}

type PATHCONF3resok struct {
	ObjAttrs        *PostOpAttr
	LinkMax         uint32
	NameMax         uint32
	NoTrunc         bool
	ChownRestricted bool
	CaseInsensitive bool
	CasePreserving  bool
}

type FSSTAT3resok struct {
	ObjAttrs *PostOpAttr
	Tbytes   uint64
	Fbytes   uint64
	Abytes   uint64
	Tfiles   uint64
	Ffiles   uint64
	Afiles   uint64
	Invarsec uint32
}

const (
	ACCESS3_READ    = 0x0001
	ACCESS3_LOOKUP  = 0x0002
	ACCESS3_MODIFY  = 0x0004
	ACCESS3_EXTEND  = 0x0008
	ACCESS3_DELETE  = 0x0010
	ACCESS3_EXECUTE = 0x0020
)

type ACCESS3resok struct {
	ObjAttrs *PostOpAttr
	Access   uint32
}

//////////////////////  lookup  //////////////////////

type DirOpArgs3 struct {
	Dir      []byte
	Filename string
}

type LOOKUP3resok struct {
	Object   []byte
	ObjAttrs *PostOpAttr
	DirAttrs *PostOpAttr
}

////////////////////// readdirplus //////////////////////

type READDIRPLUS3args struct {
	Dir        []byte // type: nfs_fh3
	Cookie     uint64 // type: cookie3
	CookieVerf uint64 // type: cookieverf3
	DirCount   uint32 // type: count3
	MaxCount   uint32 // type: count3
}

type PostOpFh3yes struct {
	HandleFollow bool
	Handle       []byte
}

type PostOpFh3no struct {
	HandleFollow bool
}

type EntryPlus3 struct {
	FileId     uint64
	Name       string
	Cookie     uint64
	NameAttrs  *PostOpAttr
	NameHandle *PostOpFh3yes
	// HasNext bool
}

type DirListPlus3 struct {
	Entries []*EntryPlus3
	EOF     bool
}

type READDIRPLUS3resok struct {
	DirAttrs   *PostOpAttr
	CookieVerf uint64
	Reply      *DirListPlus3
}
