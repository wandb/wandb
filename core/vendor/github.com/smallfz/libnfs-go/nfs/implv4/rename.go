package implv4

import (
	"io/fs"
	"os"
	"path"
	"strconv"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func rename(x nfs.RPCContext, args *nfs.RENAME4args) (*nfs.RENAME4res, error) {
	log.Infof("remame obj: %s -> %s", strconv.Quote(args.OldName), strconv.Quote(args.NewName))

	stat := x.Stat()
	vfs := x.GetFS()

	fh := stat.CurrentHandle()

	//
	// Check source.
	//
	folder, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("ResolveHandle: %v", err)
		return &nfs.RENAME4res{Status: nfs.NFS4err(err)}, nil
	}

	oldpath := path.Join(folder, args.OldName)
	_, err = vfs.Stat(oldpath)
	if err != nil {
		log.Warnf("  rename: vfs.Stat(%s): %v", oldpath, err)
		return &nfs.RENAME4res{Status: nfs.NFS4err(err)}, nil
	}

	//
	// Check destination.
	//
	newpath := path.Join(folder, args.NewName)
	fi, err := vfs.Stat(newpath)
	if err == nil && fi.Mode().Type() != os.ModeSymlink {
		// According to NFStest (nfstest_posix),
		// nfsv4 can remane a file to an existing symlink so we should not return an error in this case.
		err = fs.ErrExist
	}
	if err != nil && !os.IsNotExist(err) {
		log.Warnf("  rename: vfs.Stat(%s): %v", newpath, err)
		return &nfs.RENAME4res{Status: nfs.NFS4err(err)}, nil
	}

	//
	// Perform Rename.
	//
	if err := vfs.Rename(oldpath, newpath); err != nil {
		log.Warnf("rename: vfs.Rename(%s, %s): %v", oldpath, newpath, err)
		return &nfs.RENAME4res{Status: nfs.NFS4err(err)}, nil
	}

	res := &nfs.RENAME4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.RENAME4resok{
			SourceCInfo: &nfs.ChangeInfo4{
				Atomic: true,
				Before: 0,
				After:  0,
			},
			TargetCInfo: &nfs.ChangeInfo4{
				Atomic: true,
				Before: 0,
				After:  0,
			},
		},
	}
	return res, nil
}
