package nfs

import (
	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/xdr"
)

type RPCContext interface {
	Reader() *xdr.Reader
	Writer() *xdr.Writer
	Authenticate(*Auth, *Auth) (*Auth, error) // Handle authentication and calls fs.FS.SetCreds(). Returns *Auth to reply to the client.
	GetFS() fs.FS
	Stat() StatService
}
