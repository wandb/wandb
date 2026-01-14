package xdr

const (
	RPC_CALL = uint32(iota)
	RPC_REPLY
)

type Header struct {
	Xid     uint32
	MsgType uint32 /* RPC_CALL|RPC_REPLY */
}
