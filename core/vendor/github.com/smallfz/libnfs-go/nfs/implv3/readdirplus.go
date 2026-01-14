package implv3

import (
	"bytes"
	"fmt"
	"time"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func ReaddirPlus(h *nfs.RPCMsgCall, ctx nfs.RPCContext) (int, error) {
	r, w := ctx.Reader(), ctx.Writer()

	log.Info("> handling readdirplus: enter")
	defer func() {
		log.Info("< handling readdirplus: return")
	}()

	sizeConsumed := 0

	args := &nfs.READDIRPLUS3args{}
	if size, err := r.ReadAs(args); err != nil {
		return 0, err
	} else {
		sizeConsumed += size
	}

	log.Info(fmt.Sprintf(
		"readdirplus: args = %v", args,
	))
	log.Debugf(" args.dir : %v", args.Dir)

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

		return sizeConsumed, nil
	} else if err != nil {
		return sizeConsumed, err
	}

	rh := &nfs.RPCMsgReply{
		Xid:       h.Xid,
		MsgType:   nfs.RPC_REPLY,
		ReplyStat: nfs.MSG_ACCEPTED,
	}
	if _, err := w.WriteAny(rh); err != nil {
		return sizeConsumed, err
	}

	if _, err := w.WriteAny(resp); err != nil {
		return sizeConsumed, err
	}

	if _, err := w.WriteUint32(nfs.ACCEPT_SUCCESS); err != nil {
		return sizeConsumed, err
	}

	// --- proc result ---

	fail := func(code uint32) error {
		if _, err := w.WriteUint32(nfs.NFS3ERR_IO); err != nil {
			return err
		}
		attributesFollow := false
		if _, err := w.WriteAny(attributesFollow); err != nil {
			return err
		}
		return nil
	}

	zeros := string([]byte{0})
	folder := string(bytes.TrimRight(args.Dir, zeros))
	folder = fs.Abs(folder)

	log.Debugf(" - dir: %s", folder)

	vfs := ctx.GetFS()

	if vfs != nil {
		if di, err := vfs.Stat(folder); err != nil {
			return sizeConsumed, fail(nfs.NFS3ERR_IO)
		} else {
			dir, err := vfs.Open(folder)
			if err != nil {
				return sizeConsumed, fail(nfs.NFS3ERR_IO)
			}

			children, err := dir.Readdir(-1)
			if err != nil {
				return sizeConsumed, fail(nfs.NFS3ERR_IO)
			}

			now := time.Now()

			entries := []*nfs.EntryPlus3{}

			for i, fi := range children {
				item := fileinfoToEntryPlus3(folder, fi)

				// pathName := fs.Join(folder, fi.Name())
				// h, err := vfs.GetHandle(pathName)
				// if err != nil {
				// 	log.Warnf("vfs.GetHandle: %v", err)
				// } else {
				// 	item.NameHandle.Handle = h
				// }

				item.Cookie = uint64(i + 1)
				entries = append(entries, item)
			}

			log.Infof(" %d entries found.", len(entries))
			for _, item := range entries {
				log.Infof(
					"  > %s(fileid=%d)",
					item.Name,
					item.FileId,
				)
			}

			dirAttrs := &nfs.PostOpAttr{
				AttributesFollow: true,
				Attributes: &nfs.FileAttrs{
					Type:  nfs.FTYPE_NF3DIR,
					Mode:  uint32(di.Mode()),
					ATime: nfs.MakeNfsTime(now),
					MTime: nfs.MakeNfsTime(di.ModTime()),
					CTime: nfs.MakeNfsTime(di.ModTime()),
				},
			}

			if _, err := w.WriteUint32(nfs.NFS3_OK); err != nil {
				return sizeConsumed, err
			}

			// READDIRPLUS3resok.dir_attributes
			if _, err := w.WriteAny(dirAttrs); err != nil {
				return sizeConsumed, err
			}

			// READDIRPLUS3resok.cookieverf
			cookieverf := make([]byte, 8)
			if _, err := w.WriteAny(cookieverf); err != nil {
				return sizeConsumed, err
			}

			// dirlistplus3.entries
			if len(entries) > 0 {
				if _, err := w.WriteAny(true); err != nil {
					return sizeConsumed, err
				}
				for i, entry := range entries {
					if _, err := w.WriteAny(entry); err != nil {
						return sizeConsumed, err
					} else {
						// has next
						hasNext := i < len(entries)-1
						if _, err := w.WriteAny(hasNext); err != nil {
							return sizeConsumed, err
						}
					}
				}
			} else {
				if _, err := w.WriteAny(false); err != nil {
					return sizeConsumed, err
				}
			}

			// dirlistplus3.eof
			eof := true
			if _, err := w.WriteAny(eof); err != nil {
				return sizeConsumed, err
			}

			return sizeConsumed, nil
		}
	}

	log.Warnf("no filesystem specified.")
	return sizeConsumed, fail(nfs.NFS3ERR_IO)
}
