package implv3

import (
	"fmt"
	"time"

	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
)

func FsStat(h *nfs.RPCMsgCall, ctx nfs.RPCContext) (int, error) {
	r, w := ctx.Reader(), ctx.Writer()

	log.Info("handling fsstat.")
	sizeConsumed := 0

	fh3 := []byte{} // nfs.Fh3{}
	if size, err := r.ReadAs(&fh3); err != nil {
		return 0, err
	} else {
		sizeConsumed += size
	}

	log.Info(fmt.Sprintf("fsstat: root = %v", fh3))

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

	// ---- proc result ---

	if _, err := w.WriteUint32(nfs.NFS3_OK); err != nil {
		return sizeConsumed, err
	}

	now := time.Now()
	capacity := uint64(1024 * 1024 * 1024 * 1024 * 2)

	rs := &nfs.FSSTAT3resok{
		ObjAttrs: &nfs.PostOpAttr{
			AttributesFollow: true,
			Attributes: &nfs.FileAttrs{
				Type:  nfs.FTYPE_NF3DIR,
				Mode:  uint32(0o755),
				Size:  capacity,
				Used:  0,
				ATime: nfs.MakeNfsTime(now),
				MTime: nfs.MakeNfsTime(now),
				CTime: nfs.MakeNfsTime(now),
			},
		},
		Tbytes:   capacity,
		Fbytes:   capacity,
		Abytes:   capacity,
		Ffiles:   1024,
		Afiles:   1024,
		Invarsec: uint32(1),
	}

	if _, err := w.WriteAny(rs); err != nil {
		return sizeConsumed, err
	}

	return sizeConsumed, nil
}
