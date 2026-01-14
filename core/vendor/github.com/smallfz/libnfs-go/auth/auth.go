package auth

import (
	"bytes"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

func Null(_, _ *nfs.Auth) (*nfs.Auth, fs.Creds, error) {
	return &nfs.Auth{Flavor: nfs.AUTH_FLAVOR_NULL, Body: []byte{}}, nil, nil
}

func Unix(cred, _ *nfs.Auth) (*nfs.Auth, fs.Creds, error) {
	if cred.Flavor < nfs.AUTH_FLAVOR_UNIX {
		return nil, nil, nfs.ErrTooWeak
	}

	var credentials Creds

	if _, err := xdr.NewReader(bytes.NewBuffer(cred.Body)).ReadAs(&credentials); err != nil {
		return nil, nil, err
	}

	return &nfs.Auth{Flavor: nfs.AUTH_FLAVOR_UNIX, Body: []byte{}}, &credentials, nil
}

type Creds struct {
	ExpirationValue  uint32
	Hostname         string
	UID              uint32
	GID              uint32
	AdditionalGroups []uint32
}

func (c *Creds) Host() string {
	return c.Hostname
}

func (c *Creds) Uid() uint32 {
	return c.UID
}

func (c *Creds) Gid() uint32 {
	return c.GID
}

func (c *Creds) Groups() []uint32 {
	return c.AdditionalGroups
}
