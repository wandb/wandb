package main

import (
	"context"
	"log"
	"os"
	"syscall"

	"bazil.org/fuse"
	"bazil.org/fuse/fs"
)

type FS struct{}
type File struct {
	triggerEIO bool
}

func (FS) Root() (fs.Node, error) {
	return &File{}, nil
}

func (f *File) Attr(ctx context.Context, a *fuse.Attr) error {
	a.Mode = 0666
	return nil
}

func (f *File) Write(ctx context.Context, req *fuse.WriteRequest, resp *fuse.WriteResponse) error {
	if f.triggerEIO {
		return syscall.EIO
	}
	if req.Offset > 100 { // Trigger EIO after 100 bytes
		f.triggerEIO = true
	}
	resp.Size = len(req.Data)
	return nil
}

func main() {
	if len(os.Args) != 2 {
		log.Fatalf("Usage: %s <mountpoint>", os.Args[0])
	}
	mountpoint := os.Args[1]

	c, err := fuse.Mount(
		mountpoint,
		fuse.FSName("eiofs"),
		fuse.Subtype("eiofs"),
	)
	if err != nil {
		log.Fatal(err)
	}
	defer func() {
		err := fuse.Unmount(mountpoint)
		if err != nil {
			log.Fatalf("Failed to unmount filesystem: %v", err)
		}
		c.Close()
	}()

	srv := fs.New(c, nil)
	if err := srv.Serve(FS{}); err != nil {
		log.Fatalf("Failed to serve filesystem: %v", err)
	}
}
