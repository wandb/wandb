package implv4

import (
	"path"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func remove(x nfs.RPCContext, args *nfs.REMOVE4args) (*nfs.REMOVE4res, error) {
	log.Debugf("remove obj: '%s'", args.Target)

	stat := x.Stat()
	vfs := x.GetFS()

	fh := stat.CurrentHandle()
	folder, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return &nfs.REMOVE4res{Status: nfs.NFS4ERR_PERM}, nil
	}

	pathName := path.Join(folder, args.Target)

	fi, err := vfs.Stat(pathName)
	if err != nil {
		log.Warnf("  remove: vfs.Stat(%s): %v", pathName, err)
		return &nfs.REMOVE4res{Status: nfs.NFS4ERR_PERM}, nil
	}

	if fi.IsDir() && fi.NumLinks() > 2 {
		// Should not be able to remove an non-empty directory (more than 2 numlinks).
		return &nfs.REMOVE4res{Status: nfs.NFS3ERR_NOTEMPTY}, nil
	}

	if err := vfs.Remove(pathName); err != nil {
		log.Warnf("remove: vfs.Remove(%s): %v", pathName, err)
		return &nfs.REMOVE4res{Status: nfs.NFS4ERR_PERM}, nil
	}

	res := &nfs.REMOVE4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.REMOVE4resok{
			CInfo: &nfs.ChangeInfo4{
				Atomic: true,
				Before: 0,
				After:  0,
			},
		},
	}
	return res, nil
}
