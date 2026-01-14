package implv4

import (
	"bytes"
	"io"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func read(x nfs.RPCContext, args *nfs.READ4args) (*nfs.READ4res, error) {
	// stat := x.Stat()
	// vfs := x.GetFS()

	// pathName := stat.Cwd()

	// log.Debugf("read data from file: '%s'", pathName)

	seqId := uint32(0)
	if args != nil && args.StateId != nil {
		seqId = args.StateId.SeqId
	}

	of := x.Stat().GetOpenedFile(seqId)
	if of == nil {
		return &nfs.READ4res{Status: nfs.NFS4ERR_INVAL}, nil
	}

	f := of.File()

	if args.Offset >= 0 {
		if _, err := f.Seek(int64(args.Offset), io.SeekStart); err != nil {
			log.Warnf("f.Seek(%d): %v", args.Offset, err)
			return &nfs.READ4res{Status: nfs.NFS4ERR_PERM}, nil
		}
	}

	// log.Printf("  read(offset = %d, count = %d):", args.Offset, args.Count)

	cnt := int64(args.Count)
	eof := false

	buff := bytes.NewBuffer([]byte{})
	if _, err := io.CopyN(buff, f, cnt); err != nil {
		if err != io.EOF {
			log.Warnf("io.CopyN(): %v", err)
			return &nfs.READ4res{Status: nfs.NFS4ERR_PERM}, nil
		} else {
			eof = true
		}
	}

	// log.Printf("    %d bytes read. eof = %v.", len(buff.Bytes()), eof)

	res := &nfs.READ4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.READ4resok{
			Eof:  eof,
			Data: buff.Bytes(),
		},
	}
	return res, nil
}
