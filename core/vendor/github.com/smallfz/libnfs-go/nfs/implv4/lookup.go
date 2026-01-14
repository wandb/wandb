package implv4

import (
	"path"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func lookup(x nfs.RPCContext, args *nfs.LOOKUP4args) (*nfs.LOOKUP4res, error) {
	// log.Debugf("lookup obj: '%s'", args.ObjName)

	if len(args.ObjName) <= 0 {
		return &nfs.LOOKUP4res{
			Status: nfs.NFS4ERR_INVAL,
		}, nil
	}

	stat := x.Stat()
	vfs := x.GetFS()

	fh4 := stat.CurrentHandle()
	folder, err := vfs.ResolveHandle(fh4)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return &nfs.LOOKUP4res{Status: nfs.NFS4ERR_PERM}, nil
	}

	pathName := path.Join(folder, args.ObjName)

	fi, err := x.GetFS().Stat(pathName)
	if err != nil {
		log.Warnf(" lookup: %s: %v", pathName, err)
		return &nfs.LOOKUP4res{
			Status: nfs.NFS4ERR_NOENT,
		}, nil
	}

	// stat.SetCwd(pathName)
	fh, err := vfs.GetHandle(fi)
	if err != nil {
		return &nfs.LOOKUP4res{
			Status: nfs.NFS4ERR_NOENT,
		}, nil
	}
	stat.SetCurrentHandle(fh)

	res := &nfs.LOOKUP4res{
		Status: nfs.NFS4_OK,
	}
	return res, nil
}
