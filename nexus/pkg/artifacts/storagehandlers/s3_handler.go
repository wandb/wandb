package storagehandlers

import (
	"context"
	"fmt"
	"io"
	"net/url"
	"os"
	"strings"
	"sync"

	"github.com/aws/aws-sdk-go/aws"
	"github.com/aws/aws-sdk-go/aws/awserr"
	"github.com/aws/aws-sdk-go/aws/session"
	"github.com/aws/aws-sdk-go/service/s3"
	"github.com/hasura/go-graphql-client"
	"github.com/wandb/wandb/nexus/pkg/artifacts"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

type storageHandler struct {
	Ctx           context.Context
	Logger        *observability.NexusLogger
	ManifestEntry artifacts.ManifestEntry
	Local         bool
	// Cache artifacts.ArtifactsCache
	GraphqlClient graphql.Client
	WgOutstanding sync.WaitGroup
}

type S3StorageHandler struct {
	storageHandler
	Client *s3.S3
}

type StorageHandler interface {
	LoadPath(string, error)
}

type ETag string

func parseURI(uri string) (string, string, string, error) {
	u, err := url.Parse(uri)
	if err != nil {
		return "", "", "", err
	} else if u == nil {
		return "", "", "", fmt.Errorf("could not parse uri %v", uri)
	}

	query, err := url.ParseQuery(u.RawQuery)
	if err != nil {
		return "", "", "", err
	}
	// query.Get("versionId") -> returns "" if key not found
	return u.Host, strings.TrimPrefix(u.Path, "/"), query.Get("versionId"), nil
}

func (sh *S3StorageHandler) initClient() error {
	if sh.Client != nil {
		return nil
	}

	awsS3EndpointURL := os.Getenv("AWS_S3_ENDPOINT_URL")
	awsRegion := os.Getenv("AWS_REGION")

	sess := session.Must(session.NewSessionWithOptions(session.Options{
		Config: aws.Config{
			Endpoint: aws.String(awsS3EndpointURL),
			Region:   aws.String(awsRegion),
			// S3ForcePathStyle: aws.Bool(true),
		},
	}))

	sh.Client = s3.New(sess)
	return nil
}

func (sh *S3StorageHandler) loadPath() (string, error) {
	if sh.ManifestEntry.Ref == nil {
		return "", fmt.Errorf("reference not found manifest entry")
	}
	if !sh.Local {
		return *sh.ManifestEntry.Ref, nil
	}

	// todo: cache
	// path, hit, cache_open = sh.Cache.check_etag_obj_path()
	// if hit:
	//     return path

	sh.initClient()
	if sh.Client == nil {
		return "", fmt.Errorf("could not initiate client")
	}
	bucket, key, _, err := parseURI(*sh.ManifestEntry.Ref)
	if err != nil {
		return "", err
	}
	getObjectParams := &s3.GetObjectInput{
		Bucket: &bucket,
		Key:    &key,
	}

	extraArgs := map[string]interface{}{}
	version, ok := sh.ManifestEntry.Extra["versionId"].(string)
	if ok {
		getObjectParams.VersionId = &version
		extraArgs["VersionId"] = version
	}
	obj, err := sh.Client.GetObject(getObjectParams)
	if err != nil {
		if awsErr, ok := err.(awserr.Error); ok {
			switch awsErr.Code() {
			case s3.ErrCodeNoSuchBucket:
				return "", fmt.Errorf("bucket %s does not exist", bucket)
			case s3.ErrCodeNoSuchKey:
				return "", fmt.Errorf("object with key %s does not exist in bucket %s", key, bucket)
			default:
				return "", awsErr.OrigErr()
			}
		}
	} else if obj == nil {
		return "", fmt.Errorf("could not get object from %s/%s", bucket, key)
	}

	etag, err := etagFromObj(obj)
	if err != nil {
		return "", err
	} else if etag != ETag(sh.ManifestEntry.Digest) {
		// try to match etag with some other version
		if version != "" {
			return "", fmt.Errorf("digest mismatch for object %s with version %s: expected %s but found %s", *sh.ManifestEntry.Ref, version, sh.ManifestEntry.Digest, etag)
		}

		obj = nil
		objectVersions, err := sh.Client.ListObjectVersions(&s3.ListObjectVersionsInput{
			Bucket: &bucket,
			Prefix: &key,
		})
		if err != nil {
			return "", err
		} else if objectVersions == nil {
			return "", fmt.Errorf("could not get object versions from %s/%s", bucket, key)
		}
		manifestEntryEtag, ok := sh.ManifestEntry.Extra["etag"]
		if ok {
			for _, version := range objectVersions.Versions {
				versionEtag, err := etagFromObj(version)
				if err != nil {
					return "", err
				}
				if versionEtag == manifestEntryEtag {
					obj, err = sh.Client.GetObject(&s3.GetObjectInput{
						Bucket:    &bucket,
						Key:       &key,
						VersionId: version.VersionId,
					})
					if err != nil {
						return "", err
					}
					extraArgs["VersionId"] = version.VersionId
					break
				}

			}
		}
		if obj == nil {
			return "", fmt.Errorf("could not find object version for %s/%s matching etag %s", bucket, key, manifestEntryEtag)
		}
	}

	// todo: update cache

	path := os.Getenv("WANDB_CACHE_DIR")
	file, err := os.Create(path)
	if err != nil {
		fmt.Println("Error creating file:", err)
		os.Exit(1)
	}
	defer file.Close()
	_, copyErr := io.Copy(file, obj.Body)
	if copyErr != nil {
		fmt.Println("Error copying object data to file:", copyErr)
		os.Exit(1)
	}

	return path, nil
}

func etagFromObj(obj interface{}) (ETag, error) {
	var etagValue string
	switch obj := obj.(type) {
	case *s3.Object:
		etagValue = *obj.ETag
	case *s3.ObjectVersion:
		etagValue = *obj.ETag
	default:
		return "", fmt.Errorf("unsupported object type %T to retrieve etag", obj)
	}
	etag := ETag(etagValue[1 : len(etagValue)-1]) // escape leading and trailing quotes
	return etag, nil
}
