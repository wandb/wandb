package implv4

import (
	"io"
	"os"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func setAttr(x nfs.RPCContext, args *nfs.SETATTR4args) (*nfs.SETATTR4res, error) {
	resFailNotSupp := &nfs.SETATTR4res{Status: nfs.NFS4ERR_ATTRNOTSUPP}
	resFailPerm := &nfs.SETATTR4res{Status: nfs.NFS4ERR_PERM}

	a4 := args.Attrs
	idxReq := bitmap4Decode(a4.Mask)

	// uncheck not-writable attributes

	off := map[int]bool{}
	for id, on := range idxReq {
		if on && !isAttrWritable(id) {
			off[id] = false
		}
	}
	for id := range off {
		if on, found := idxReq[id]; found && on {
			idxReq[id] = false
		}
	}

	// cwd := x.Stat().Cwd()
	vfs := x.GetFS()
	fh := x.Stat().CurrentHandle()
	pathName, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return resFailPerm, nil
	}

	seqId := uint32(0)
	if args.StateId != nil {
		seqId = args.StateId.SeqId
	}

	f := (fs.File)(nil)
	// pathName := cwd

	of := x.Stat().GetOpenedFile(seqId)

	if of != nil {
		f = of.File()
		pathName = of.Path()
	} else {
		if _f, err := vfs.Open(pathName); err != nil {
			log.Warnf("vfs.Open(%s): %v", pathName, err)
			return resFailPerm, nil
		} else {
			defer _f.Close()
			f = _f
		}
	}

	decAttrs, err := decodeFAttrs4(args.Attrs)
	if err != nil {
		return resFailNotSupp, nil
	}
	// log.Println(toJson(decAttrs))

	// TODO: actually set the attributes....
	if decAttrs.Mode != nil {
		perm := os.FileMode(*decAttrs.Mode)
		if err := vfs.Chmod(pathName, perm); err != nil {
			log.Warnf("vfs.Chmod(%s, %o): %v", pathName, perm, err)
			return resFailPerm, nil
		}
	}
	if decAttrs.Size != nil {
		size := int64(*decAttrs.Size)

		if _, err := f.Seek(size, io.SeekStart); err != nil {
			log.Warnf("f.Seek(%d, %d): %v", size, io.SeekStart, err)
		} else {
			if err := f.Truncate(); err != nil {
				log.Warnf("f.Truncate: %v", err)
				return resFailPerm, nil
			}
		}
	}
	if decAttrs.Owner != "" || decAttrs.OwnerGroup != "" {
		if vfs.Attributes().ChownRestricted {
			log.Warn("vfs.Chown: Operation not permitted due to chown_restricted attr")
			return resFailPerm, nil
		}

		uid, gid, err := chownAttrs(decAttrs.Owner, decAttrs.OwnerGroup)
		if err != nil {
			log.Warnf("vfs.Chown(%s, %s, %s): %v", pathName, decAttrs.Owner, decAttrs.OwnerGroup, err)
			return resFailPerm, nil
		}

		if err = vfs.Chown(pathName, uid, gid); err != nil {
			log.Warnf("vfs.Chown(%s, %d, %d): %v", pathName, uid, gid, err)
			return resFailPerm, err
		}
	}

	fi, err := f.Stat()
	if err != nil {
		log.Warnf("f.Stat: %v", err)
		return resFailPerm, nil
	}

	attrs := fileInfoToAttrs(vfs, pathName, fi, idxReq)
	attrSet := attrs.Mask

	return &nfs.SETATTR4res{
		Status:  nfs.NFS4_OK,
		AttrSet: attrSet,
	}, nil
}
