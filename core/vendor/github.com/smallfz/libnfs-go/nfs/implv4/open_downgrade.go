package implv4

import (
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

func readOpOpenDgArgs(r *xdr.Reader) (*nfs.OPENDG4args, int, error) {
	sizeConsumed := 0
	args := &nfs.OPENDG4args{}

	if size, err := r.ReadAs(args); err != nil {
		return nil, sizeConsumed, err
	} else {
		sizeConsumed += size
	}

	return args, sizeConsumed, nil
}

func openDg(x nfs.RPCContext, args *nfs.OPENDG4args) (*nfs.ResGenericRaw, error) {
	// log.Infof(toJson(args))

	// resFail500 := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_SERVERFAULT}
	resFailPerm := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_PERM}
	// resFailDup := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_EXIST}
	// resFail404 := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOENT}

	state := x.Stat().GetOpenedFile(args.SeqId)
	if state == nil {
		log.Warnf("try to open_downgrade on a not-openned file.")
		return resFailPerm, nil
	}

	return &nfs.ResGenericRaw{
		Status: nfs.NFS4_OK,
	}, nil
}
