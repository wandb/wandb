package storagehandlers

import (
	"context"
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
		// todo: return error
	} else if u == nil {
		// todo: return error
	}

	query, err := url.ParseQuery(u.RawQuery)
	if err != nil {
		// todo: return error
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
		// todo: return error
	}
	if !sh.Local {
		return *sh.ManifestEntry.Ref, nil
	}

	// todo: cache
	sh.initClient()
	if sh.Client == nil {
		// todo: return error
	}
	bucket, key, _, err := parseURI(*sh.ManifestEntry.Ref)
	if bucket == "" || key == "" {
		// todo: return error
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
				// todo: error ("bucket %s does not exist", bucket)
			case s3.ErrCodeNoSuchKey:
				//todo: error ("object with key %s does not exist in bucket %s", key, bucket)
			default:
				// todo: return error
			}
		}
	} else if obj == nil {
		// todo: return error
	}

	etag, err := etagFromObj(obj)
	if err != nil {
		// todo: return error
	} else if etag != ETag(sh.ManifestEntry.Digest) {
		// try to match etag with some other version
		if version != "" {
			// todo: return error
		}

		obj = nil
		object_versions, err := sh.Client.ListObjectVersions(&s3.ListObjectVersionsInput{
			Bucket: &bucket,
			Prefix: &key,
		})
		if err != nil {
			// todo: return error
		} else if object_versions == nil {
			// todo: return error
		}
		manifest_entry_etag, ok := sh.ManifestEntry.Extra["etag"]
		if ok {
			for _, version := range object_versions.Versions {
				version_etag, err := etagFromObj(version)
				if err != nil {
					// todo: return error
				}
				if version_etag == manifest_entry_etag {
					obj, err = sh.Client.GetObject(&s3.GetObjectInput{
						Bucket:    &bucket,
						Key:       &key,
						VersionId: version.VersionId,
					})
					if err != nil {
						// todo: return error
					}
					extraArgs["VersionId"] = version.VersionId
					break
				}

			}
		}
		if obj == nil {
			// todo: return error
		}
	}

	// todo: download files and write to cache

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
		// todo: return error
	}
	etag := ETag(etagValue[1 : len(etagValue)-1]) // escape leading and trailing quotes
	return etag, nil
}
