package storagehandlers

import (
	"context"
	"fmt"
	"net/url"
	"os"
	"strings"

	"cloud.google.com/go/storage"
)

type GCSClient interface {
	Bucket(name string) *storage.BucketHandle
	Close() error
}

type GCSStorageHandler struct {
	storageHandler
	Client            GCSClient
	VersioningEnabled *bool
}

func parseGCSURI(uri string) (string, string, string, error) {
	u, err := url.Parse(uri)
	if err != nil {
		return "", "", "", err
	} else if u == nil {
		return "", "", "", fmt.Errorf("could not parse uri %v", uri)
	}

	return u.Host, strings.TrimPrefix(u.Path, "/"), u.Fragment, nil
}

func (sh *GCSStorageHandler) initClient() error {
	if sh.Client != nil {
		return nil
	}

	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		return err
	}
	sh.Client = client
	return nil
}

func (sh *GCSStorageHandler) loadPath() (string, error) {
	if sh.ManifestEntry.Ref == nil {
		return "", fmt.Errorf("reference not found in manifest entry")
	}
	if sh.Local != nil && !(*sh.Local) {
		return *sh.ManifestEntry.Ref, nil
	}

	// todo: check for cache hit

	err := sh.initClient()
	if err != nil {
		return "", fmt.Errorf("could not initialize client: %v", err)
	}
	if sh.Client == nil {
		return "", fmt.Errorf("could not initialize client")
	}

	bucket, key, _, err := parseGCSURI(*sh.ManifestEntry.Ref)
	if err != nil {
		return "", err
	}
	var obj *storage.ObjectHandle
	version, ok := sh.ManifestEntry.Extra["versionID"].(int64)
	if ok {
		// todo: check what happens if object versioning is disabled
		// First attempt to get the generation specified, this will return None if versioning is not enabled
		obj = obj.Generation(version)
		if obj == nil {
			return "", fmt.Errorf("could not find object at bucket: %s, key: %s, version: %d", bucket, key, version)
		}
	}
	// Object versioning is disabled on the bucket, so just get
	// the latest version and make sure the MD5 matches.
	if obj == nil {
		obj = sh.Client.Bucket(bucket).Object(key)
		if obj == nil {
			return "", fmt.Errorf("could not find object at bucket: %s, key: %s", bucket, key)
		}
		objAttrs, err := obj.Attrs(sh.Ctx)
		if err != nil {
			return "", err
		} else if objAttrs == nil {
			return "", fmt.Errorf("could not get attributes for object at bucket: %s, key: %s", bucket, key)
		}
		md5 := string(objAttrs.MD5)
		if md5 != sh.ManifestEntry.Digest {
			return "", fmt.Errorf("diget mismatch for object %s: expected %s but found %s", *sh.ManifestEntry.Ref, sh.ManifestEntry.Digest, md5)
		}
	}

	// todo: set path based on etag
	path := os.Getenv("WANDB_CACHE_DIR")
	rc, err := obj.NewReader(sh.Ctx)
	if err != nil {
		return "", err
	} else if rc == nil {
		return "", fmt.Errorf("could not read object at %s", *sh.ManifestEntry.Ref)
	}
	defer rc.Close()

	/*
		file, err := os.Create(path)
		if err != nil {
			return "", fmt.Errorf("Error creating file: %v", err)
		}
		defer file.Close()
		_, err = io.Copy(file, rc)
		if err != nil {
			return "", fmt.Errorf("Error copying object content %v:", err)
		}
	*/

	return path, nil
}
