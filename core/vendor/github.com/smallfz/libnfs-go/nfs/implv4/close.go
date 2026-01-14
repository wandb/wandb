package implv4

import (
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func closeFile(x nfs.RPCContext, args *nfs.CLOSE4args) (*nfs.CLOSE4res, error) {
	seqId := uint32(0)
	if args != nil && args.OpenStateId != nil {
		seqId = args.OpenStateId.SeqId
	}

	log.Infof("CLOSE4, seq=%d", seqId)

	f := x.Stat().RemoveOpenedFile(seqId)
	if f == nil {
		log.Warnf("close: opened file in stat not exists.")
		return &nfs.CLOSE4res{Status: nfs.NFS4ERR_INVAL}, nil
	} else {
		log.Debugf(" - %s closed.", f.File().Name())
		f.File().Close()
	}

	res := &nfs.CLOSE4res{
		Status: nfs.NFS4_OK,
		Ok:     args.OpenStateId,
	}
	return res, nil
}
