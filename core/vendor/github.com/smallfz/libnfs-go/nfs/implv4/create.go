package implv4

import (
	"os"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

func readOpCreateArgs(r *xdr.Reader) (*nfs.CREATE4args, int, error) {
	sizeConsumed := 0
	typ, err := r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4

	args := &nfs.CREATE4args{
		ObjType: typ,
	}

	switch typ {
	case nfs.NF4LNK:
		var linkData string
		size, err := r.ReadAs(&linkData)
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += size
		args.LinkData = linkData

	case nfs.NF4BLK, nfs.NF4CHR:
		devData := &nfs.Specdata4{}
		size, err := r.ReadAs(devData)
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += size
		args.DevData = devData
	}

	var objName string
	size, err := r.ReadAs(&objName)
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += size
	args.ObjName = objName

	attrs := &nfs.FAttr4{}
	size, err = r.ReadAs(attrs)
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += size
	args.CreateAttrs = attrs

	return args, sizeConsumed, nil
}

func create(x nfs.RPCContext, args *nfs.CREATE4args) (*nfs.CREATE4res, error) {
	switch args.ObjType {
	case nfs.NF4DIR, nfs.NF4REG, nfs.NF4LNK:
		// Supported types
	case nfs.NF4BLK, nfs.NF4CHR, nfs.NF4FIFO, nfs.NF4SOCK:
		return &nfs.CREATE4res{Status: nfs.NFS4ERR_PERM}, nil
	default:
		return &nfs.CREATE4res{Status: nfs.NFS4ERR_BADTYPE}, nil
	}

	resFailPerm := &nfs.CREATE4res{Status: nfs.NFS4ERR_PERM}
	resFail500 := &nfs.CREATE4res{Status: nfs.NFS4ERR_SERVERFAULT}

	// cwd := x.Stat().Cwd()
	vfs := x.GetFS()

	fh := x.Stat().CurrentHandle()
	cwd, err := vfs.ResolveHandle(fh)
	if err != nil {
		return resFailPerm, nil
	}

	fi, err := vfs.Stat(cwd)
	if err != nil {
		log.Debugf("    create: vfs.Stat(%s): %v", cwd, err)
		return resFail500, nil
	}
	if !fi.IsDir() {
		return resFailPerm, nil
	}

	pathName := fs.Join(cwd, args.ObjName)
	log.Debugf("    create: %s", pathName)
	if _, err := vfs.Stat(pathName); err == nil {
		return &nfs.CREATE4res{Status: nfs.NFS4ERR_EXIST}, nil
	}

	cinfo := &nfs.ChangeInfo4{}
	attrSet := []uint32{}

	decAttrs, err := decodeFAttrs4(args.CreateAttrs)
	if err != nil {
		log.Warnf("create: decodeFAttrs: %v", err)
		return resFailPerm, nil
	}

	switch args.ObjType {
	case nfs.NF4DIR:

		// create a directory

		mod := os.FileMode(0o755)
		if decAttrs.Mode != nil {
			mod = os.FileMode(*decAttrs.Mode)
		}
		mod = mod | os.ModeDir

		if err := vfs.MkdirAll(pathName, mod); err != nil {
			log.Warnf("create: vfs.MkdirAll(%s): %v", pathName, err)
			return resFailPerm, nil
		}

		fi, err := vfs.Stat(pathName)
		if err != nil {
			log.Warnf("create: vfs.Stat(%s): %v", pathName, err)
			return resFailPerm, nil
		}

		attr := fileInfoToAttrs(vfs, pathName, fi, nil)
		attrSet = attr.Mask

		// set current fh to the newly created one.
		fh, err := vfs.GetHandle(fi)
		if err != nil {
			return resFailPerm, nil
		}
		x.Stat().SetCurrentHandle(fh)

	case nfs.NF4REG:

		// create a regular file

		mod := os.FileMode(0o644)
		if decAttrs.Mode != nil {
			mod = os.FileMode(*decAttrs.Mode)
		}

		flag := os.O_CREATE | os.O_RDWR | os.O_TRUNC

		f, err := vfs.OpenFile(pathName, flag, mod)
		if err != nil {
			log.Warnf("create: vfs.OpenFile: %v", err)
			return resFailPerm, nil
		}
		defer f.Close()

		fi, err := f.Stat()
		if err != nil {
			log.Warnf("create: f.Stat(): %v", err)
			return resFailPerm, nil
		}

		attr := fileInfoToAttrs(vfs, pathName, fi, nil)
		attrSet = attr.Mask

		// set current fh to the newly created one.
		fh, err := vfs.GetHandle(fi)
		if err != nil {
			return resFailPerm, nil
		}
		x.Stat().SetCurrentHandle(fh)

	case nfs.NF4LNK:

		// create symlink

		err = vfs.Symlink(args.LinkData, pathName)
		if err != nil {
			return &nfs.CREATE4res{Status: nfs.NFS4err(err)}, nil
		}

		fi, err := vfs.Stat(pathName)
		if err != nil {
			log.Warnf("create: vfs.Stat(%s): %v", pathName, err)
			return resFailPerm, nil
		}

		attr := fileInfoToAttrs(vfs, pathName, fi, nil)
		attrSet = attr.Mask

		// set current fh to the newly created one.
		fh, err := vfs.GetHandle(fi)
		if err != nil {
			return resFailPerm, nil
		}
		x.Stat().SetCurrentHandle(fh)
	}

	res := &nfs.CREATE4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.CREATE4resok{
			CInfo:   cinfo,
			AttrSet: attrSet,
		},
	}
	return res, nil
}
