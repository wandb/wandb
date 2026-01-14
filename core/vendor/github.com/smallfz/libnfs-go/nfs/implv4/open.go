package implv4

import (
	"bytes"
	"fmt"
	"os"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

func readOpOpenArgs(r *xdr.Reader) (*nfs.OPEN4args, int, error) {
	sizeConsumed := 0

	args := &nfs.OPEN4args{}

	seqId, err := r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4
	args.SeqId = seqId

	v, err := r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4
	args.ShareAccess = v

	v, err = r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4
	args.ShareDeny = v

	/* open_owner4 */

	owner := &nfs.OpenOwner4{}
	size, err := r.ReadAs(owner)
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += size
	args.Owner = owner

	v, err = r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4
	args.OpenHow = v

	/* openflag4 */

	switch args.OpenHow {
	case nfs.OPEN4_CREATE:
		how := &nfs.CreateHow4{}
		v, err = r.ReadUint32()
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += 4
		how.CreateMode = v

		switch how.CreateMode {
		case nfs.UNCHECKED4, nfs.GUARDED4:
			attr := &nfs.FAttr4{}
			size, err = r.ReadAs(attr)
			if err != nil {
				return nil, sizeConsumed, err
			}
			sizeConsumed += size
			how.CreateAttrs = attr

		case nfs.EXCLUSIVE4:
			verf := uint64(0)
			size, err = r.ReadAs(&verf)
			if err != nil {
				return nil, sizeConsumed, err
			}
			sizeConsumed += size
			how.CreateVerf = verf

		default:
			return nil, sizeConsumed, fmt.Errorf(
				"unexpected createmode: %v",
				how.CreateMode,
			)
		}

		args.CreateHow = how
	}

	// open_claim4

	claim := &nfs.OpenClaim4{}
	v, err = r.ReadUint32()
	if err != nil {
		return nil, sizeConsumed, err
	}
	sizeConsumed += 4
	claim.Claim = v

	switch claim.Claim {
	case nfs.CLAIM_NULL:
		var file string
		size, err := r.ReadAs(&file)
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += size
		claim.File = file

	case nfs.CLAIM_PREVIOUS:
		delegateTyp, err := r.ReadUint32()
		if err != nil {
			return nil, sizeConsumed, err
		}
		claim.DelegateType = delegateTyp

	case nfs.CLAIM_DELEGATE_CUR:
		curInfo := &nfs.OpenClaimDelegateCur4{}
		size, err = r.ReadAs(curInfo)
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += size
		claim.DelegateCurInfo = curInfo

	case nfs.CLAIM_DELEGATE_PREV:
		var prev string
		size, err = r.ReadAs(&prev)
		if err != nil {
			return nil, sizeConsumed, err
		}
		sizeConsumed += size
		claim.FileDelegatePrev = prev

	default:
		return nil, sizeConsumed, fmt.Errorf("invalid claim: %v", claim.Claim)
	}

	args.Claim = claim
	return args, sizeConsumed, nil
}

func open(x nfs.RPCContext, args *nfs.OPEN4args) (*nfs.ResGenericRaw, error) {
	// log.Infof(toJson(args))

	resFail500 := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_SERVERFAULT}
	resFailPerm := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_PERM}
	resFailDup := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_EXIST}
	resFail404 := &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOENT}

	createIfNotExists := false
	raiseWhenExists := true
	trunc := false

	decAttrs := (*Attr)(nil)

	if args.OpenHow == nfs.OPEN4_CREATE {
		createIfNotExists = true
		switch args.CreateHow.CreateMode {
		case nfs.UNCHECKED4:
			// no error if target exists. truncate existing target.
			raiseWhenExists = false
			trunc = true
			attr, err := decodeFAttrs4(args.CreateHow.CreateAttrs)
			if err != nil {
				return resFail500, nil
			}
			decAttrs = attr

		case nfs.GUARDED4:
			// raise NFS4ERR_EXIST if target exists.
			raiseWhenExists = true
		case nfs.EXCLUSIVE4:
			// Nothing to do here.
		default:
			return &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOTSUPP}, nil
		}
	} else {
		raiseWhenExists = false
	}

	stat := x.Stat()
	vfs := x.GetFS()

	cwd, err := vfs.ResolveHandle(stat.CurrentHandle())
	if err != nil {
		return &nfs.ResGenericRaw{Status: nfs.NFS4ERR_PERM}, nil
	}

	if di, err := vfs.Stat(cwd); err != nil {
		return resFail500, nil
	} else if !di.IsDir() {
		return resFailPerm, nil
	}

	pathName := fs.Join(cwd, args.Claim.File)
	createNew := false

	fi, err := vfs.Stat(pathName)
	if err != nil {
		if os.IsNotExist(err) {
			if !createIfNotExists {
				return resFail404, nil
			} else {
				// todo: create new file.
				createNew = true
			}
		} else {
			return resFail500, nil
		}
	} else {
		if raiseWhenExists {
			return resFailDup, nil
		}
		if fi.IsDir() {
			return resFailPerm, nil
		}
		// ok, already exists. nothing to do.
	}

	var finalFi fs.FileInfo = fi

	attrSet := []uint32{}

	seqId := uint32(0) // RFC7531: stateid4.seqid

	if createNew {
		flag := os.O_CREATE | os.O_RDWR | os.O_TRUNC

		mode := os.FileMode(0o644)
		if decAttrs != nil && decAttrs.Mode != nil {
			mode = os.FileMode(*decAttrs.Mode)
		}

		if f, err := vfs.OpenFile(pathName, flag, mode); err != nil {
			log.Warnf("vfs.OpenFile(%s): %v", pathName, err)
			return resFailPerm, nil
		} else {
			seqId = x.Stat().AddOpenedFile(pathName, f)

			fi, err := f.Stat()
			if err != nil {
				return resFailPerm, nil
			}

			finalFi = fi

			if args.CreateHow != nil && args.CreateHow.CreateAttrs != nil {
				idxReq := bitmap4Decode(args.CreateHow.CreateAttrs.Mask)
				a4 := fileInfoToAttrs(vfs, pathName, fi, idxReq)
				attrSet = a4.Mask
			}
		}

	} else {

		flag := os.O_RDWR
		if trunc {
			flag = flag | os.O_TRUNC
		}

		if f, err := vfs.OpenFile(pathName, flag, fi.Mode()); err != nil {
			log.Warnf("vfs.OpenFile(%s): %v", pathName, err)
			return resFailPerm, nil
		} else {
			seqId = x.Stat().AddOpenedFile(pathName, f)
		}

	}

	if fh, err := vfs.GetHandle(finalFi); err != nil {
		log.Warnf("vfs.GetHandle: %v", err)
		return resFailPerm, nil
	} else {
		stat.SetCurrentHandle(fh)
	}

	res := &nfs.OPEN4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.OPEN4resok{
			StateId: &nfs.StateId4{
				SeqId: seqId,
				Other: [3]uint32{0, 0, 0},
			},
			CInfo:   &nfs.ChangeInfo4{},
			Rflags:  uint32(0), // OPEN4_RESULT_*
			AttrSet: attrSet,
			Delegation: &nfs.OpenDelegation4{
				Type: nfs.OPEN_DELEGATE_NONE,
			},
		},
	}

	buff := bytes.NewBuffer([]byte{})
	w := xdr.NewWriter(buff)

	w.WriteAny(res.Ok)

	return &nfs.ResGenericRaw{
		Status: res.Status,
		Reader: bytes.NewReader(buff.Bytes()),
	}, nil
}
