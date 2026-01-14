package implv4

import (
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func getAttr(x nfs.RPCContext, args *nfs.GETATTR4args) (*nfs.GETATTR4res, error) {
	// cwd := x.Stat().Cwd()
	// pathName := cwd

	vfs := x.GetFS()
	fh := x.Stat().CurrentHandle()
	pathName, err := vfs.ResolveHandle(fh)
	if err != nil {
		log.Warnf("getattr: ResolveHandle: %v", err)
		return &nfs.GETATTR4res{Status: nfs.NFS4ERR_NOENT}, nil
	}

	// log.Debugf("    getattr(%s => %s)", fh, pathName)
	log.Debugf("    getattr(%s)", pathName)

	idxReq := bitmap4Decode(args.AttrRequest)

	// log.Debugf("getattr: attrs: %v", idxReq)
	// for id, on := range idxReq {
	// 	if on {
	// 		name, found := GetAttrNameById(id)
	// 		if found {
	// 			log.Debugf(" - request attr: [%d] %s.", id, name)
	// 		}
	// 	}
	// }

	fi, err := vfs.Stat(pathName)
	if err != nil {
		log.Debugf("getattr: vfs.Stat(%s): %v", pathName, err)
		return &nfs.GETATTR4res{Status: nfs.NFS4ERR_NOENT}, nil
	}

	_, err = vfs.GetHandle(fi)
	if err != nil {
		log.Warnf("getattr: vfs.GetHandle: %v", err)
		return &nfs.GETATTR4res{Status: nfs.NFS4ERR_NOENT}, nil
	}

	attrs := fileInfoToAttrs(vfs, pathName, fi, idxReq)

	rs := &nfs.GETATTR4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.GETATTR4resok{
			Attr: attrs,
		},
	}
	return rs, nil
}
