package nfs

import (
	"fmt"
)

// https://datatracker.ietf.org/doc/html/rfc1057

const (
	RPC_CALL = uint32(iota)
	RPC_REPLY
)

const (
	MSG_ACCEPTED = uint32(iota)
	MSG_DENIED
)

const (
	ACCEPT_SUCCESS       = uint32(iota) /* RPC executed successfully       */
	ACCEPT_PROG_UNAVAIL                 /* remote hasn't exported program  */
	ACCEPT_PROG_MISMATCH                /* remote can't support version #  */
	ACCEPT_PROC_UNAVAIL                 /* program can't support procedure */
	ACCEPT_GRABAGE_ARGS                 /* procedure can't decode params   */
)

const (
	REJECT_RPC_MISMATCH = uint32(iota) /* RPC version number != 2          */
	REJECT_AUTH_ERROR                  /* remote can't authenticate caller */
)

const (
	AUTH_FLAVOR_NULL = iota
	AUTH_FLAVOR_UNIX
	AUTH_FLAVOR_SHORT
	AUTH_FLAVOR_DES
)

const (
	AUTH_BADCRED      = uint32(iota + 1) /* bad credentials (seal broken) */
	AUTH_REJECTEDCRED                    /* client must begin new session */
	AUTH_BADVERF                         /* bad verifier (seal broken)    */
	AUTH_REJECTEDVERF                    /* verifier expired or replayed  */
	AUTH_TOOWEAK                         /* rejected for security reasons */
)

type Auth struct {
	Flavor uint32
	Body   []byte
}

type AuthError struct {
	Code uint32
}

func (err *AuthError) Error() string {
	return fmt.Sprintf("auth error: %d", err.Code)
}

var (
	ErrBadCredentials = &AuthError{Code: AUTH_BADCRED}
	ErrTooWeak        = &AuthError{Code: AUTH_TOOWEAK}
)

func NewEmptyAuth() *Auth {
	return &Auth{Flavor: 0, Body: []byte{}}
}

type RPCMsgCall struct {
	Xid     uint32
	MsgType uint32 /* RPC_CALL */
	RPCVer  uint32 /* rfc1057, const: 2 */

	Prog uint32 /* nfs: 100003 */
	Vers uint32 /* 3 */
	Proc uint32 /* see proc.go */

	Cred *Auth
	Verf *Auth
}

func (h *RPCMsgCall) String() string {
	procName := fmt.Sprintf("%d", h.Proc)
	if h.Prog == 100003 {
		switch h.Vers {
		case 3:
			procName = Proc3Name(h.Proc)
		case 4:
			procName = Proc4Name(h.Proc)
		}
	}
	return fmt.Sprintf(
		"<prog=%d, v=%d, proc=%s>",
		h.Prog, h.Vers, procName,
	)
}

type RPCMsgReply struct {
	Xid       uint32 /* exact as the corresponding call. */
	MsgType   uint32 /* RPC_REPLY */
	ReplyStat uint32 /* MSG_ACCEPT | MSG_DENIED */
}

type RejectReply struct {
	RejectStat uint32 /* RPC_MISMATCH | AUTH_ERROR */
	Lo         uint32
	Hi         uint32
}
