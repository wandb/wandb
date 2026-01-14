package implv4

import (
	"github.com/smallfz/libnfs-go/nfs"
)

func setClientId(args *nfs.SETCLIENTID4args) (*nfs.SETCLIENTID4res, error) {
	rs := &nfs.SETCLIENTID4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.SETCLIENTID4resok{
			ClientId:           uint64(1),
			SetClientIdConfirm: args.Client.Verifier,
		},
	}
	return rs, nil
}
