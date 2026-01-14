package implv4

import (
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func commit(x nfs.RPCContext, args *nfs.COMMIT4args) (*nfs.COMMIT4res, error) {
	vfs := x.GetFS()
	fh := x.Stat().CurrentHandle()
	pathName, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("commit: ResolveHandle: %v", err)
		return &nfs.COMMIT4res{Status: nfs.NFS4ERR_NOENT}, nil
	}

	log.Debugf("    commit(%s, offset=%d, count=%d)",
		pathName,
		args.Offset,
		args.Count,
	)

	// verifier := args.Offset

	files := x.Stat().FindOpenedFiles(pathName)
	if files != nil && len(files) > 0 {
		for _, of := range files {
			f := of.File()
			if err := f.Sync(); err != nil {
				log.Warnf("commit(%s): of.f.Sync: %v", pathName, err)
			} else {
				log.Infof("commit(%s): ok.", pathName)
			}
		}
	}

	rs := &nfs.COMMIT4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.COMMIT4resok{
			Verifier: 0,
		},
	}
	return rs, nil
}
