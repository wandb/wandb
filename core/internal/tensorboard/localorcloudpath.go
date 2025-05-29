package tensorboard

import (
	"context"
	"errors"
	"fmt"
	"log/slog"
	"net/url"
	"path/filepath"
	"strings"

	"github.com/wandb/wandb/core/internal/paths"
	"gocloud.dev/blob"
	"gocloud.dev/blob/fileblob"

	// Imported for the side-effect of registering blob.OpenBucket() providers.
	_ "gocloud.dev/blob/azureblob"
	_ "gocloud.dev/blob/gcsblob"
	_ "gocloud.dev/blob/s3blob"
)

// LocalOrCloudPath is a path to a local or cloud file.
type LocalOrCloudPath struct {
	// CloudPath is a URL to a blob in a supported cloud storage system.
	//
	// It is nil if this is not a cloud file.
	CloudPath *CloudPath

	// LocalPath is an absolute path on the local filesystem.
	//
	// It is nil if this is not a local file.
	LocalPath *paths.AbsolutePath
}

func (path *LocalOrCloudPath) String() string {
	switch {
	case path.CloudPath != nil:
		return fmt.Sprintf("LocalOrCloudPath(CloudPath=%q)", path.CloudPath)

	case path.LocalPath != nil:
		return fmt.Sprintf(
			"LocalOrCloudPath(LocalPath=%q)", path.LocalPath.OrEmpty())

	default:
		return "LocalOrCloudPath(nil)"
	}
}

// LogValue implements slog.LogValuer.
func (path *LocalOrCloudPath) LogValue() slog.Value {
	return slog.StringValue(path.String())
}

// CloudPath is a path to a cloud storage file.
type CloudPath struct {
	// Scheme is a scheme understood by the go-cloud package.
	//
	// The possible schemes are "gs" and "s3".
	Scheme string

	// BucketName is the name of the bucket.
	BucketName string

	// Path is the name or a prefix of an object in the bucket.
	//
	// It is assumed that forward slashes "/" create a directory structure
	// within the bucket, and this integration will not work with bucket
	// URLs like "s3://my-bucket/my\windows\style\file.txt".
	//
	// The Path never ends with a forward slash.
	Path string
}

func (path *CloudPath) String() string {
	return fmt.Sprintf("%s://%s/%s", path.Scheme, path.BucketName, path.Path)
}

// LogValue implements slog.LogValuer.
func (path *CloudPath) LogValue() slog.Value {
	return slog.StringValue(path.String())
}

// ParseTBPath parses a path string supported by this TensorBoard integration.
//
// The original W&B TensorBoard integration relied on the Python tensorboard
// package's internals, which supports cloud paths through tensorflow's
// "gfile" abstraction. This function supports some of the same formats for
// backward compatibility, specifically:
//
//   - Amazon S3: "s3://bucket/some/file/name"
//   - GCS: "gs://bucket/some/file/name"
//   - Microsoft Azure: "az://account/bucket/some/file/name"
//
// Any other formats are interpreted as local file system paths.
func ParseTBPath(pathURLString string) (*LocalOrCloudPath, error) {
	isS3 := strings.HasPrefix(pathURLString, "s3://")
	isGS := strings.HasPrefix(pathURLString, "gs://")
	isAZ := strings.HasPrefix(pathURLString, "az://")

	if isS3 || isGS || isAZ {
		pathURL, err := url.Parse(pathURLString)

		if err != nil {
			return nil, fmt.Errorf("failed to parse cloud URL: %v", err)
		}

		trimmedURLPath := strings.Trim(pathURL.EscapedPath(), "/")

		var path *CloudPath

		switch {
		case isS3:
			path = &CloudPath{
				Scheme:     "s3",
				BucketName: pathURL.Host,
				Path:       trimmedURLPath,
			}

		case isGS:
			path = &CloudPath{
				Scheme:     "gs",
				BucketName: pathURL.Host,
				Path:       trimmedURLPath,
			}

		case isAZ:
			urlPathParts := strings.Split(trimmedURLPath, "/")
			if len(urlPathParts) < 2 {
				return nil, fmt.Errorf("invalid Azure cloud URL: %q", pathURLString)
			}

			// NOTE: For Azure blob URLs, the URL Host is the account name,
			// and the bucket name is the first path component. While it is
			// possible to pass the account name via the `storage_account`
			// query parameter when using blob.OpenBucket(),
			// the AZURE_STORAGE_ACCOUNT variable must be set anyway or else
			// Azure will ignore the AZURE_STORAGE_KEY variable.
			bucketName := urlPathParts[0]

			path = &CloudPath{
				Scheme:     "azblob",
				BucketName: bucketName,
				Path:       strings.Join(urlPathParts[1:], "/"),
			}

		default:
			return nil, fmt.Errorf("invalid cloud URL: %q", pathURLString)
		}

		return &LocalOrCloudPath{CloudPath: path}, nil
	}

	path, err := paths.Absolute(pathURLString)
	if err != nil {
		return nil, fmt.Errorf("failed to make path absolute: %v", err)
	}

	return &LocalOrCloudPath{LocalPath: path}, nil
}

// ToSlashPath returns a slash-separated ("/") representation of the path,
// for the purpose of computing common prefixes.
func (p *LocalOrCloudPath) ToSlashPath() string {
	switch {
	case p.CloudPath != nil:
		return fmt.Sprintf("%s/%s", p.CloudPath.BucketName, p.CloudPath.Path)

	case p.LocalPath != nil:
		return filepath.ToSlash(string(*p.LocalPath))

	default:
		return ""
	}
}

// Bucket opens the prefixed bucket corresponding to the path.
//
// For local paths, this may return an error if the directory does not exist.
// For cloud paths, this may do network operations and return an error.
func (p *LocalOrCloudPath) Bucket(ctx context.Context) (*blob.Bucket, error) {
	switch {
	case p.CloudPath != nil:
		bucket, err := blob.OpenBucket(ctx,
			fmt.Sprintf("%s://%s", p.CloudPath.Scheme, p.CloudPath.BucketName))

		if err != nil {
			return nil, fmt.Errorf("failed to open bucket: %v", err)
		}

		if p.CloudPath.Path == "" {
			return bucket, nil
		} else {
			return blob.PrefixedBucket(bucket, p.CloudPath.Path+"/"), nil
		}

	case p.LocalPath != nil:
		bucket, err := fileblob.OpenBucket(string(*p.LocalPath), nil)

		if err != nil {
			return nil, fmt.Errorf("failed to open bucket: %v", err)
		}

		return bucket, nil

	default:
		return nil, errors.New("invalid LocalOrCloudPath")
	}
}

// Child interprets this path as a directory and returns the path to a file
// inside it with the given name.
//
// For cloud paths, a forward slash "/" is used to join the key to the prefix.
func (p *LocalOrCloudPath) Child(key string) (*LocalOrCloudPath, error) {
	switch {
	case p.CloudPath != nil:
		var childPath string

		if p.CloudPath.Path != "" {
			childPath = fmt.Sprintf("%s/%s", p.CloudPath.Path, key)
		} else {
			childPath = key
		}

		return &LocalOrCloudPath{
			CloudPath: &CloudPath{
				Scheme:     p.CloudPath.Scheme,
				BucketName: p.CloudPath.BucketName,
				Path:       childPath,
			},
		}, nil

	case p.LocalPath != nil:
		maybeChildName, err := paths.Relative(key)
		if err != nil {
			return nil, err
		}
		childName := *maybeChildName

		if !childName.IsLocal() {
			return nil, fmt.Errorf("invalid file name: %s", childName)
		}

		childPath := p.LocalPath.Join(childName)
		return &LocalOrCloudPath{LocalPath: &childPath}, nil

	default:
		return nil, errors.New("invalid LocalOrCloudPath")
	}
}
