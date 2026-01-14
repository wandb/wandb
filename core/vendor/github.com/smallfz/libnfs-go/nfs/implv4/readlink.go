package implv4

import (
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func readlink(x nfs.RPCContext) (*nfs.READLINK4res, error) {
	stat := x.Stat()
	vfs := x.GetFS()

	name, err := vfs.ResolveHandle(stat.CurrentHandle())
	if err != nil {
		log.Warnf("vfs.ResolveHandle: %v", err)
		return &nfs.READLINK4res{Status: nfs.NFS4err(err)}, nil
	}

	_, err = vfs.Stat(name)
	if err != nil {
		log.Warnf("  remove: vfs.Stat(%s): %v", name, err)
	}

	link, err := vfs.Readlink(name)
	if err != nil {
		log.Warnf("remove: vfs.Readlink(%s): %v", name, err)
		return &nfs.READLINK4res{Status: nfs.NFS4err(err)}, nil
	}

	return &nfs.READLINK4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.READLINK4resok{
			Link: link,
		},
	}, nil
}
