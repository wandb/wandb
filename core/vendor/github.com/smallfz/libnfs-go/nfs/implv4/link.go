package implv4

import (
	"io/fs"
	"os"
	"path"
	"strconv"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func link(x nfs.RPCContext, args *nfs.LINK4args) (*nfs.LINK4res, error) {
	log.Debugf("link obj: %s", strconv.Quote(args.NewName))

	stat := x.Stat()
	vfs := x.GetFS()

	//
	// Check source stored by previous SAVE_FH call.
	//
	savefh, ok := stat.PeekHandle()
	if !ok {
		log.Warn("PopHandle: SAVED_FH not found")
		return &nfs.LINK4res{Status: nfs.NFS4ERR_INVAL}, nil
	}

	oldpath, err := vfs.ResolveHandle(savefh)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return &nfs.LINK4res{Status: nfs.NFS4err(err)}, nil
	}

	_, err = vfs.Stat(oldpath)
	if err != nil {
		log.Warnf("  link: vfs.Stat(%s): %v", oldpath, err)
		return &nfs.LINK4res{Status: nfs.NFS4err(err)}, nil
	}

	//
	// Check destination.
	//
	fh := stat.CurrentHandle()
	folder, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return &nfs.LINK4res{Status: nfs.NFS4err(err)}, nil
	}

	newpath := path.Join(folder, args.NewName)
	_, err = vfs.Stat(newpath)
	if err == nil || os.IsExist(err) {
		if err == nil {
			err = fs.ErrExist
		}
		log.Warnf("  link: exists: vfs.Stat(%s): %v", newpath, err)
		return &nfs.LINK4res{Status: nfs.NFS4err(err)}, nil
	}

	//
	// Perform Link.
	//
	if err := vfs.Link(oldpath, newpath); err != nil {
		log.Warnf("link: vfs.Link(%s, %s): %v", oldpath, newpath, err)
		return &nfs.LINK4res{Status: nfs.NFS4err(err)}, nil
	}

	return &nfs.LINK4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.LINK4resok{
			CInfo: &nfs.ChangeInfo4{
				Atomic: true,
				Before: 0,
				After:  0,
			},
		},
	}, nil
}
