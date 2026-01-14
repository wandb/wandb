package implv4

import (
	"github.com/smallfz/libnfs-go/nfs"
)

func Void(h *nfs.RPCMsgCall, ctx nfs.RPCContext) (int, error) {
	w := ctx.Writer()

	rh := &nfs.RPCMsgReply{
		Xid:       h.Xid,
		MsgType:   nfs.RPC_REPLY,
		ReplyStat: nfs.MSG_ACCEPTED,
	}
	if _, err := w.WriteAny(rh); err != nil {
		return 0, err
	}

	auth := &nfs.Auth{
		Flavor: nfs.AUTH_FLAVOR_NULL,
		Body:   []byte{},
	}
	if _, err := w.WriteAny(auth); err != nil {
		return 0, err
	}

	acceptStat := nfs.ACCEPT_SUCCESS
	if _, err := w.WriteUint32(acceptStat); err != nil {
		return 0, err
	}

	// void => [0]byte
	if _, err := w.WriteAny([0]byte{}); err != nil {
		return 0, err
	}

	return 0, nil
}
