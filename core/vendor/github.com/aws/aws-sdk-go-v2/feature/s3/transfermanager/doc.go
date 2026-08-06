// Package transfermanager implements the Amazon S3 Transfer Manager, a
// high-level S3 client library.
//
// Package transfermanager is the new iteration of the original
// [feature/s3/manager] module implemented for the AWS SDK Go v2.
//
// # Why transfermanager?
//
// Package transfermanager achieves the following improvement compared with original
// [feature/s3/manager] module:
//
//   - Merge all features into a single Client, eliminating the need for separate uploader/downloader
//     clients, some common options like concurrency and part size could be shared across different APIs
//   - Simplify input/output configuration with new types for each API, users now deal with new input/output
//     like they do for normal services and do not need to concern conversion between new type and bottom
//     S3 request/response
//   - Optimize single object upload caching strategy to speed up multipart upload
//   - Introduce new [Client.GetObject] API with object data in output's io.Reader to align with [Client.UploadObject]
//     input source, while [Client.DownloadObject] from v1 will be ported to maintain backward compatibility
//   - Add support for downloading an object in parts or ranges according to user configuration
//   - Add directory transfer APIs for batch upload/download operations, user can define criteria for the
//     entire workflow. For example, user can add filter type to decide which files should be transferred and
//     how their S3 requests should be customized
//
// # Features
//
// Package transfermanager implements a high-level S3 client with support for the
// following:
//   - [Client.UploadObject] - enhanced object write support w/ automatic
//     multipart upload for large objects
//   - [Client.DownloadObject] - enhanced object read support w/ automatic
//     multipart download for large objects
//   - [Client.GetObject] - mimic s3.GetObject API to support sequential
//     io.Reader output w/ concurrent multipart download for large objects
//   - [Client.UploadDirectory] - enhanced directory write support w/ automatic
//     concurrent files upload for folders with different hierarchy
//   - [Client.DownloadDirectory] - enhanced bucket read support w/ automatic
//     concurrent objects download for a bucket's objects
//
// The package also exposes several opt-in hooks that configure an
// http.Transport that may convey performance/reliability enhancements in
// certain user environments:
//   - round-robin DNS ([WithRoundRobinDNS])
//   - multi-NIC dialer ([WithRotoDialer])
//
// [feature/s3/manager]: https://pkg.go.dev/github.com/aws/aws-sdk-go-v2/feature/s3/manager
package transfermanager
