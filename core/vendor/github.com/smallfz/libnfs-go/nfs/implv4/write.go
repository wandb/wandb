package implv4

import (
	"bytes"
	"io"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func write(x nfs.RPCContext, args *nfs.WRITE4args) (*nfs.WRITE4res, error) {
	// stat := x.Stat()
	// vfs := x.GetFS()

	// pathName := stat.Cwd()

	// log.Debugf("write data to file: '%s'", pathName)
	// log.Printf(toJson(args))

	seqId := uint32(0)
	if args != nil && args.StateId != nil {
		seqId = args.StateId.SeqId
	}

	of := x.Stat().GetOpenedFile(seqId)
	if of == nil {
		return &nfs.WRITE4res{Status: nfs.NFS4ERR_INVAL}, nil
	}

	f := of.File()

	if args.Offset >= 0 {
		// log.Printf("  seek %d", args.Offset)
		if _, err := f.Seek(int64(args.Offset), io.SeekStart); err != nil {
			log.Warnf("f.Seek(%d): %v", args.Offset, err)
			return &nfs.WRITE4res{Status: nfs.NFS4ERR_PERM}, nil
		}
	}

	sizeWrote := uint32(0)
	if args.Data != nil && len(args.Data) > 0 {
		buff := bytes.NewReader(args.Data)
		size, err := io.CopyN(f, buff, int64(len(args.Data)))
		if err != nil {
			log.Warnf("io.CopyN(): %v", err)
			return &nfs.WRITE4res{Status: nfs.NFS4ERR_PERM}, nil
		}
		sizeWrote = uint32(size)
		// log.Printf("  %d bytes wrote.", sizeWrote)
	} else {
		// log.Printf("  no data to be written.")
	}

	// resultCommitted := nfs.UNSTABLE4
	resultCommitted := nfs.UNSTABLE4
	fsync := false
	if sizeWrote >= 0 {
		switch args.Stable {
		case nfs.DATA_SYNC4:
			fsync = true
		case nfs.FILE_SYNC4:
			fsync = true
		}

		if fsync {
			if err := f.Sync(); err != nil {
				log.Warnf("f.Sync(%s): %v", f.Name(), err)
			} else {
				resultCommitted = args.Stable
			}
		}
	}

	res := &nfs.WRITE4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.WRITE4resok{
			Count:     sizeWrote,
			Committed: resultCommitted,
			WriteVerf: 0,
		},
	}
	return res, nil
}
