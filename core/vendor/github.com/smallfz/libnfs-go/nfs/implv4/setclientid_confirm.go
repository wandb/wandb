package implv4

import (
	"github.com/smallfz/libnfs-go/nfs"
)

func setClientIdConfirm(args *nfs.SETCLIENTID_CONFIRM4args) (*nfs.SETCLIENTID_CONFIRM4res, error) {
	rs := &nfs.SETCLIENTID_CONFIRM4res{
		Status: nfs.NFS4_OK,
	}
	return rs, nil
}
