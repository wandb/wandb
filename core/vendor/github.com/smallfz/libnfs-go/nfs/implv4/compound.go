package implv4

import (
	"io"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func Compound(h *nfs.RPCMsgCall, ctx nfs.RPCContext) (int, error) {
	r, w := ctx.Reader(), ctx.Writer()

	sizeConsumed := 0

	tag := ""
	if size, err := r.ReadAs(&tag); err != nil {
		return sizeConsumed, err
	} else {
		sizeConsumed += size
	}

	minorVer := uint32(0)
	if size, err := r.ReadAs(&minorVer); err != nil {
		return sizeConsumed, err
	} else {
		sizeConsumed += size
	}

	opsCnt := uint32(0)
	if size, err := r.ReadAs(&opsCnt); err != nil {
		return sizeConsumed, err
	} else {
		sizeConsumed += size
	}

	resp, err := ctx.Authenticate(h.Cred, h.Verf)
	if authErr, ok := err.(*nfs.AuthError); ok {
		rh := &nfs.RPCMsgReply{
			Xid:       h.Xid,
			MsgType:   nfs.RPC_REPLY,
			ReplyStat: nfs.MSG_DENIED,
		}

		if _, err := w.WriteAny(rh); err != nil {
			return sizeConsumed, err
		}

		if _, err := w.WriteUint32(nfs.REJECT_AUTH_ERROR); err != nil {
			return sizeConsumed, err
		}

		if _, err := w.WriteUint32(authErr.Code); err != nil {
			return sizeConsumed, err
		}

		// Discard all input
		for i := uint32(0); i < opsCnt; i++ {
			opnum4 := uint32(0)
			if size, err := r.ReadAs(&opnum4); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			switch opnum4 {
			case nfs.OP4_SETCLIENTID:
				args := &nfs.SETCLIENTID4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_SETCLIENTID_CONFIRM:
				args := &nfs.SETCLIENTID_CONFIRM4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_EXCHANGE_ID:
				args := &nfs.EXCHANGE_ID4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_PUTROOTFH:
			case nfs.OP4_GETATTR:
				args := &nfs.GETATTR4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_PUTFH:
				args := &nfs.PUTFH4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_GETFH:
			case nfs.OP4_LOOKUP:
				args := &nfs.LOOKUP4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_ACCESS:
				args := &nfs.ACCESS4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_READDIR:
				args := &nfs.READDIR4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_SECINFO:
				args := &nfs.SECINFO4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_RENEW:
				args := &nfs.RENEW4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_CREATE:
				// rfc7530, 16.4.2
				_, size, err := readOpCreateArgs(r)
				if err != nil {
					return sizeConsumed, err
				}
				sizeConsumed += size

			case nfs.OP4_OPEN:
				_, size, err := readOpOpenArgs(r)
				if err != nil {
					return sizeConsumed, err
				}
				sizeConsumed += size

			case nfs.OP4_OPEN_DOWNGRADE:
				_, size, err := readOpOpenDgArgs(r)
				if err != nil {
					return sizeConsumed, err
				}
				sizeConsumed += size

			case nfs.OP4_CLOSE:
				args := &nfs.CLOSE4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_SETATTR:
				args := &nfs.SETATTR4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_REMOVE:
				args := &nfs.REMOVE4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_COMMIT:
				args := &nfs.COMMIT4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_WRITE:
				args := &nfs.WRITE4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_READ:
				args := &nfs.READ4args{}
				if size, err := r.ReadAs(args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_SAVEFH:
			case nfs.OP4_RESTOREFH:
			case nfs.OP4_RENAME:
				var args nfs.RENAME4args
				if size, err := r.ReadAs(&args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_LINK:
				var args nfs.LINK4args
				if size, err := r.ReadAs(&args); err != nil {
					return sizeConsumed, err
				} else {
					sizeConsumed += size
				}

			case nfs.OP4_READLINK:
			default:
				log.Warnf("op not handled: %d.", opnum4)
				w.WriteUint32(nfs.NFS4ERR_OP_ILLEGAL)
				return sizeConsumed, nil
			}
		}
	} else if err != nil {
		return 0, err
	}

	rh := &nfs.RPCMsgReply{
		Xid:       h.Xid,
		MsgType:   nfs.RPC_REPLY,
		ReplyStat: nfs.MSG_ACCEPTED,
	}
	if _, err := w.WriteAny(rh); err != nil {
		return 0, err
	}

	if _, err := w.WriteAny(resp); err != nil {
		return 0, err
	}

	if _, err := w.WriteUint32(nfs.ACCEPT_SUCCESS); err != nil {
		return 0, err
	}

	// ---- proc ----

	log.Debugf("---------- compound proc (%d ops) ----------", opsCnt)

	rsStatusList := []uint32{}
	rsOpList := []uint32{}
	rsList := []interface{}{}

	for i := uint32(0); i < opsCnt; i++ {
		opnum4 := uint32(0)
		if size, err := r.ReadAs(&opnum4); err != nil {
			return sizeConsumed, err
		} else {
			sizeConsumed += size
		}

		log.Debugf("(%d) %s", i, nfs.Proc4Name(opnum4))

		switch opnum4 {
		case nfs.OP4_SETCLIENTID:
			args := &nfs.SETCLIENTID4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}
			res, err := setClientId(args)
			if err != nil {
				return sizeConsumed, err
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_SETCLIENTID_CONFIRM:
			args := &nfs.SETCLIENTID_CONFIRM4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}
			res, err := setClientIdConfirm(args)
			if err != nil {
				return sizeConsumed, err
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_EXCHANGE_ID:
			args := &nfs.EXCHANGE_ID4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			// todo: ...
			res := &nfs.EXCHANGE_ID4res{
				Status: nfs.NFS4_OK,
				Ok: &nfs.EXCHANGE_ID4resok{
					ClientId:     0,
					SequenceId:   0,
					StateProtect: &nfs.StateProtect4R{},
					ServerImplId: &nfs.NfsImplId4{
						Date: &nfs.NfsTime4{},
					},
				},
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_PUTROOTFH:
			// reset cwd to /
			stat := ctx.Stat()
			// stat.SetCwd("/")
			stat.SetCurrentHandle(ctx.GetFS().GetRootHandle())

			// log.Infof("  putrootfh(/)")

			res := &nfs.PUTROOTFH4res{
				Status: nfs.NFS4_OK,
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_GETATTR:
			args := &nfs.GETATTR4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := getAttr(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_PUTFH:
			args := &nfs.PUTFH4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			log.Debugf("    fh = %x", args.Fh)

			// set current handler to args.Fh
			stat := ctx.Stat()
			vfs := ctx.GetFS()

			res := &nfs.PUTFH4res{
				Status: nfs.NFS4_OK,
			}

			if _, err := vfs.ResolveHandle(args.Fh); err != nil {
				log.Warnf("vfs.ResolveHandle(%x): %v", args.Fh, err)
				res.Status = nfs.NFS4ERR_NOENT
			} else {
				res.Status = nfs.NFS4_OK
				stat.SetCurrentHandle(args.Fh)
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_GETFH:
			stat := ctx.Stat()
			// vfs := ctx.GetFS()

			// res := (*nfs.GETFH4res)(nil)
			fh := stat.CurrentHandle()
			res := &nfs.GETFH4res{
				Status: nfs.NFS4_OK,
				Ok: &nfs.GETFH4resok{
					Fh: fh,
				},
			}

			// fh, err := vfs.GetHandle(stat.Cwd())
			// if err != nil {
			// 	res = &nfs.GETFH4res{
			// 		Status: nfs.NFS4ERR_SERVERFAULT,
			// 	}
			// } else {
			// 	res = &nfs.GETFH4res{
			// 		Status: nfs.NFS4_OK,
			// 		Ok: &nfs.GETFH4resok{
			// 			Fh: fh,
			// 		},
			// 	}
			// }

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_LOOKUP:
			args := &nfs.LOOKUP4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := lookup(ctx, args)
			if err != nil {
				log.Warnf("lookup: %v", err)
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_ACCESS:
			args := &nfs.ACCESS4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := access(ctx, args)
			if err != nil {
				log.Warnf("access: %v", err)
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_READDIR:
			args := &nfs.READDIR4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := readDir(ctx, args)
			if err != nil {
				log.Warnf("readdir: %v", err)
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_SECINFO:
			args := &nfs.SECINFO4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			// log.Debugf("secinfo args.Name = %s", args.Name)
			res := &nfs.SECINFO4res{
				Status: nfs.NFS4_OK,
				Ok: &nfs.SECINFO4resok{
					Items: []*nfs.Secinfo4{
						{
							Flavor: 0,
							FlavorInfo: &nfs.RPCSecGssInfo{
								Service: nfs.RPC_GSS_SVC_NONE,
							},
						},
					},
				},
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_RENEW:
			args := &nfs.RENEW4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			// todo: renew client registration. somehow...

			res := &nfs.RENEW4res{
				Status: nfs.NFS4_OK,
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_CREATE:
			// rfc7530, 16.4.2
			args, size, err := readOpCreateArgs(r)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += size

			res, err := create(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_OPEN:
			args, size, err := readOpOpenArgs(r)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += size

			res, err := open(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_OPEN_DOWNGRADE:
			args, size, err := readOpOpenDgArgs(r)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += size

			res, err := openDg(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_CLOSE:
			args := &nfs.CLOSE4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := closeFile(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_SETATTR:
			args := &nfs.SETATTR4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := setAttr(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_REMOVE:
			args := &nfs.REMOVE4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := remove(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_COMMIT:
			args := &nfs.COMMIT4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := commit(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_WRITE:
			args := &nfs.WRITE4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := write(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_READ:
			args := &nfs.READ4args{}
			if size, err := r.ReadAs(args); err != nil {
				return sizeConsumed, err
			} else {
				sizeConsumed += size
			}

			res, err := read(ctx, args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_SAVEFH:
			st := ctx.Stat()
			st.PushHandle(st.CurrentHandle())
			// ctx.Stat().PushHandle(ctx.Stat().Cwd())
			res := &nfs.SAVEFH4res{
				Status: nfs.NFS4_OK,
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_RESTOREFH:
			st := ctx.Stat()
			fh, ok := st.PopHandle()
			if ok {
				// ctx.Stat().SetCwd(pathName)
				st.SetCurrentHandle(fh)
			}

			res := &nfs.RESTOREFH4res{
				Status: nfs.NFS4_OK,
			}
			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_RENAME:
			var args nfs.RENAME4args
			size, err := r.ReadAs(&args)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += size

			res, err := rename(ctx, &args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_LINK:
			var args nfs.LINK4args
			size, err := r.ReadAs(&args)
			if err != nil {
				return sizeConsumed, err
			}
			sizeConsumed += size

			res, err := link(ctx, &args)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		case nfs.OP4_READLINK:
			res, err := readlink(ctx)
			if err != nil {
				return sizeConsumed, err
			}

			rsOpList = append(rsOpList, opnum4)
			rsStatusList = append(rsStatusList, res.Status)
			rsList = append(rsList, res)

		default:
			log.Warnf("op not handled: %d.", opnum4)
			w.WriteUint32(nfs.NFS4ERR_OP_ILLEGAL)
			return sizeConsumed, nil
		}
	}

	lastStatus := nfs.NFS4_OK
	if len(rsStatusList) > 0 {
		lastStatus = rsStatusList[len(rsStatusList)-1]
	}

	w.WriteUint32(lastStatus)
	w.WriteAny(tag) // tag: use the same as in request.

	w.WriteUint32(uint32(len(rsStatusList)))
	for i, rs := range rsList {
		op := rsOpList[i]

		w.WriteUint32(op)

		switch res := rs.(type) {
		case *nfs.ResGenericRaw:
			w.WriteUint32(res.Status)
			if res.Reader != nil {
				if _, err := io.Copy(w, res.Reader); err != nil {
					log.Errorf("Compound(): io.Copy: %v", err)
				}
			}

		default:
			w.WriteAny(rs)
		}
	}

	return sizeConsumed, nil
}
