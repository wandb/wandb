package implv4

import (
	"bytes"

	"github.com/smallfz/libnfs-go/fs"
	"github.com/smallfz/libnfs-go/log"
	"github.com/smallfz/libnfs-go/nfs"
	"github.com/smallfz/libnfs-go/xdr"
)

func encodeReaddirResult(res *nfs.READDIR4res) *nfs.ResGenericRaw {
	// marshal the result
	buff := bytes.NewBuffer([]byte{})
	w := xdr.NewWriter(buff)

	if res.Status == nfs.NFS4_OK {
		w.WriteAny(res.Ok.CookieVerf)
		w.WriteAny(res.Ok.Reply.HasEntries)
		for _, entry := range res.Ok.Reply.Entries {
			w.WriteAny(entry)
		}
		w.WriteAny(res.Ok.Reply.Eof)
	}

	dat := buff.Bytes()
	log.Debugf("    readdir: result data size: %d bytes.", len(dat))

	// return a wrapped result.
	return &nfs.ResGenericRaw{
		Status: res.Status,
		Reader: bytes.NewReader(dat),
	}
}

func readDir(x nfs.RPCContext, args *nfs.READDIR4args) (*nfs.ResGenericRaw, error) {
	stat := x.Stat()
	vfs := x.GetFS()

	cwd, err := vfs.ResolveHandle(stat.CurrentHandle())
	if err != nil {
		log.Warnf("vfs.ResolveHandle: %v", err)
		return &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOENT}, nil
	}

	pathName := cwd

	// log.Debugf("readdir: '%s'", pathName)

	idxReq := (map[int]bool)(nil)
	if args.AttrRequest != nil {
		idxReq = bitmap4Decode(args.AttrRequest)
	}

	dir, err := vfs.Open(pathName)
	if err != nil {
		log.Warnf("vfs.Open(%s): %v", pathName, err)
		return &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOENT}, nil
	}

	children, err := dir.Readdir(-1)
	if err != nil {
		log.Warnf("dir.Readdir: %v", err)
		return &nfs.ResGenericRaw{Status: nfs.NFS4ERR_NOENT}, nil
	}

	log.Debugf("    readdir: actual entries count = %d", len(children))

	log.Debugf(
		"    readdir: dircount=%d, maxcount=%d. cookie=%d, cookieverf=%d.",
		args.DirCount,
		args.MaxCount,
		args.Cookie,
		args.CookieVerf,
	)

	// force to incease limitations giving by client.
	// if args.DirCount < 1024 * 32 {
	// 	args.DirCount = 1024 * 32
	// }
	// if args.MaxCount < 1024 * 128 {
	// 	args.MaxCount = 1024 * 128
	// }

	dirList := &nfs.DirList4{HasEntries: false, Eof: true}

	resCookieVerf := uint64(1000)

	cookieReq := int(args.Cookie)
	if cookieReq == 0 {
		cookieReq += 1000
	} else {
		cookieReq += 1
	}

	log.Debugf("    readdir: cookie-req = %d", cookieReq)

	attrSize := getAttrsMaxBytesSize(idxReq)

	resDirCount := uint32(0)
	resMaxCount := uint32(512)

	eof := false

	entryCookies := []int{}

	if len(children) > 0 {
		dirList.HasEntries = true
		dirList.Entries = []*nfs.Entry4{}

		for i, child := range children {
			cookie := 1000 + i

			if cookie < cookieReq {
				continue
			}

			entryCookies = append(entryCookies, cookie)
			resCookieVerf = uint64(cookie + 1)

			pathName := fs.Join(cwd, child.Name())
			// _, err := vfs.GetHandle(pathName)
			// if err != nil {
			// 	log.Warnf("vfs.GetHandle(%s): %v", pathName, err)
			// 	continue
			// }
			entry := &nfs.Entry4{
				Cookie:  uint64(cookie), // should be set. (blood and tears!)
				Name:    child.Name(),
				Attrs:   fileInfoToAttrs(vfs, pathName, child, idxReq),
				HasNext: true,
			}
			dirList.Entries = append(dirList.Entries, entry)
			// log.Debugf(" - entry: %s", child.Name())

			if i == len(children)-1 {
				eof = true
			}

			nameSize := uint32(xdr.Pad(len(child.Name())) + 4)
			resDirCount += nameSize + 8
			resMaxCount += uint32(nameSize + 8 + attrSize + 4)

			if resDirCount >= args.DirCount || resMaxCount > args.MaxCount {
				break
			}
		}

		if len(dirList.Entries) > 0 {
			dirList.Entries[len(dirList.Entries)-1].HasNext = false
		}
	} else {
		eof = true
	}

	if len(entryCookies) > 0 {
		log.Debugf("    readdir, response: range[%d, %d], count=%d, eof=%v.",
			entryCookies[0],
			entryCookies[len(entryCookies)-1],
			len(dirList.Entries),
			eof,
		)
	} else {
		log.Debugf("    readdir, response: range[<empty>], count=%d, eof=%v.",
			len(dirList.Entries),
			eof,
		)
	}

	dirList.Eof = eof

	log.Debugf("    readdir, response: cookieverf=%d", resCookieVerf)

	res := &nfs.READDIR4res{
		Status: nfs.NFS4_OK,
		Ok: &nfs.READDIR4resok{
			CookieVerf: resCookieVerf,
			Reply:      dirList,
		},
	}

	// if dat, err := json.MarshalIndent(res, "", "  "); err != nil {
	// 	log.Errorf("json.MarshalIndent: %v", err)
	// } else {
	// 	log.Println(string(dat))
	// }

	return encodeReaddirResult(res), nil
}
