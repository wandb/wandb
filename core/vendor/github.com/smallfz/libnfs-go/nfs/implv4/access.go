package implv4

import (
	"os"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func computeAccessOnFile(mode os.FileMode, access uint32) (uint32, uint32) {
	support := nfs.ACCESS4_READ
	support |= nfs.ACCESS4_LOOKUP
	support |= nfs.ACCESS4_MODIFY
	support |= nfs.ACCESS4_EXTEND
	support |= nfs.ACCESS4_DELETE
	support |= nfs.ACCESS4_EXECUTE

	perm := (uint32(mode) >> 6) & uint32(0b0111)

	r := perm & (uint32(1) << 2)
	w := perm & (uint32(1) << 1)
	xe := perm & uint32(1)

	accForFh := uint32(0)

	if r > 0 {
		accForFh = accForFh | nfs.ACCESS4_READ
		accForFh = accForFh | nfs.ACCESS4_LOOKUP
	}
	if w > 0 {
		accForFh = accForFh | nfs.ACCESS4_MODIFY
		accForFh = accForFh | nfs.ACCESS4_EXTEND
		accForFh = accForFh | nfs.ACCESS4_DELETE
	}
	if xe > 0 {
		accForFh = accForFh | nfs.ACCESS4_LOOKUP
		accForFh = accForFh | nfs.ACCESS4_EXECUTE
	}

	accForFh = accForFh & access

	return support, accForFh
}

func access(x nfs.RPCContext, args *nfs.ACCESS4args) (*nfs.ACCESS4res, error) {
	stat := x.Stat()

	pathName, err := x.GetFS().ResolveHandle(stat.CurrentHandle())
	if err != nil {
		log.Warnf(" access: ResolveHandle: %v", err)
		return &nfs.ACCESS4res{
			Status: nfs.NFS4ERR_NOENT,
		}, nil
	}

	fi, err := x.GetFS().Stat(pathName)
	if err != nil {
		log.Warnf(" access: %s: %v", pathName, err)
		return &nfs.ACCESS4res{
			Status: nfs.NFS4ERR_NOENT,
		}, nil
	}

	// log.Debugf(" access(%v): %s: found: %v", args.Access, pathName, fi)

	support, accForFh := computeAccessOnFile(fi.Mode(), args.Access)

	// log.Printf("  support = %v, access = %v", support, accForFh)

	rs := &nfs.ACCESS4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.ACCESS4resok{
			Supported: support,
			Access:    accForFh,
		},
	}
	return rs, nil
}
