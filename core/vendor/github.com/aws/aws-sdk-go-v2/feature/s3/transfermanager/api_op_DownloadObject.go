package transfermanager

import (
	"context"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/middleware"
	"github.com/aws/aws-sdk-go-v2/feature/s3/transfermanager/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
	smithymiddleware "github.com/aws/smithy-go/middleware"
)

// DownloadObjectInput represents a request to the DownloadObject() call. It contains common fields
// of s3 GetObject input and destination WriterAt of object
type DownloadObjectInput struct {
	// Bucket where the object is downloaded from
	Bucket *string

	// Key of the object to get.
	Key *string

	// Destination WriterAt which object parts are written to
	WriterAt io.WriterAt

	// To retrieve the checksum, this mode must be enabled.
	//
	// General purpose buckets - In addition, if you enable checksum mode and the
	// object is uploaded with a [checksum]and encrypted with an Key Management Service (KMS)
	// key, you must have permission to use the kms:Decrypt action to retrieve the
	// checksum.
	//
	// [checksum]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_Checksum.html
	ChecksumMode types.ChecksumMode

	// The account ID of the expected bucket owner. If the account ID that you provide
	// does not match the actual owner of the bucket, the request fails with the HTTP
	// status code 403 Forbidden (access denied).
	ExpectedBucketOwner *string

	// Return the object only if its entity tag (ETag) is the same as the one
	// specified in this header; otherwise, return a 412 Precondition Failed error.
	//
	// If both of the If-Match and If-Unmodified-Since headers are present in the
	// request as follows: If-Match condition evaluates to true , and;
	// If-Unmodified-Since condition evaluates to false ; then, S3 returns 200 OK and
	// the data requested.
	//
	// For more information about conditional requests, see [RFC 7232].
	//
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfMatch *string

	// Return the object only if it has been modified since the specified time;
	// otherwise, return a 304 Not Modified error.
	//
	// If both of the If-None-Match and If-Modified-Since headers are present in the
	// request as follows: If-None-Match condition evaluates to false , and;
	// If-Modified-Since condition evaluates to true ; then, S3 returns 304 Not
	// Modified status code.
	//
	// For more information about conditional requests, see [RFC 7232].
	//
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfModifiedSince *time.Time

	// Return the object only if its entity tag (ETag) is different from the one
	// specified in this header; otherwise, return a 304 Not Modified error.
	//
	// If both of the If-None-Match and If-Modified-Since headers are present in the
	// request as follows: If-None-Match condition evaluates to false , and;
	// If-Modified-Since condition evaluates to true ; then, S3 returns 304 Not
	// Modified HTTP status code.
	//
	// For more information about conditional requests, see [RFC 7232].
	//
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfNoneMatch *string

	// Return the object only if it has not been modified since the specified time;
	// otherwise, return a 412 Precondition Failed error.
	//
	// If both of the If-Match and If-Unmodified-Since headers are present in the
	// request as follows: If-Match condition evaluates to true , and;
	// If-Unmodified-Since condition evaluates to false ; then, S3 returns 200 OK and
	// the data requested.
	//
	// For more information about conditional requests, see [RFC 7232].
	//
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfUnmodifiedSince *time.Time

	// Downloads the specified byte range of an object. This field only applies when GetObjectType is GetObjectRanges
	Range *string

	// Confirms that the requester knows that they will be charged for the request.
	// Bucket owners need not specify this parameter in their requests. If either the
	// source or destination S3 bucket has Requester Pays enabled, the requester will
	// pay for corresponding charges to copy the object. For information about
	// downloading objects from Requester Pays buckets, see [Downloading Objects in Requester Pays Buckets]in the Amazon S3 User
	// Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [Downloading Objects in Requester Pays Buckets]: https://docs.aws.amazon.com/AmazonS3/latest/dev/ObjectsinRequesterPaysBuckets.html
	RequestPayer types.RequestPayer

	// Sets the Cache-Control header of the response.
	ResponseCacheControl *string

	// Sets the Content-Disposition header of the response.
	ResponseContentDisposition *string

	// Sets the Content-Encoding header of the response.
	ResponseContentEncoding *string

	// Sets the Content-Language header of the response.
	ResponseContentLanguage *string

	// Sets the Content-Type header of the response.
	ResponseContentType *string

	// Sets the Expires header of the response.
	ResponseExpires *time.Time

	// Specifies the algorithm to use when decrypting the object (for example, AES256 ).
	//
	// If you encrypt an object by using server-side encryption with customer-provided
	// encryption keys (SSE-C) when you store the object in Amazon S3, then when you
	// GET the object, you must use the following headers:
	//
	//   - x-amz-server-side-encryption-customer-algorithm
	//
	//   - x-amz-server-side-encryption-customer-key
	//
	//   - x-amz-server-side-encryption-customer-key-MD5
	//
	// For more information about SSE-C, see [Server-Side Encryption (Using Customer-Provided Encryption Keys)] in the Amazon S3 User Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [Server-Side Encryption (Using Customer-Provided Encryption Keys)]: https://docs.aws.amazon.com/AmazonS3/latest/dev/ServerSideEncryptionCustomerKeys.html
	SSECustomerAlgorithm *string

	// Specifies the customer-provided encryption key that you originally provided for
	// Amazon S3 to encrypt the data before storing it. This value is used to decrypt
	// the object when recovering it and must match the one used when storing the data.
	// The key must be appropriate for use with the algorithm specified in the
	// x-amz-server-side-encryption-customer-algorithm header.
	//
	// If you encrypt an object by using server-side encryption with customer-provided
	// encryption keys (SSE-C) when you store the object in Amazon S3, then when you
	// GET the object, you must use the following headers:
	//
	//   - x-amz-server-side-encryption-customer-algorithm
	//
	//   - x-amz-server-side-encryption-customer-key
	//
	//   - x-amz-server-side-encryption-customer-key-MD5
	//
	// For more information about SSE-C, see [Server-Side Encryption (Using Customer-Provided Encryption Keys)] in the Amazon S3 User Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [Server-Side Encryption (Using Customer-Provided Encryption Keys)]: https://docs.aws.amazon.com/AmazonS3/latest/dev/ServerSideEncryptionCustomerKeys.html
	SSECustomerKey *string

	// Specifies the 128-bit MD5 digest of the customer-provided encryption key
	// according to RFC 1321. Amazon S3 uses this header for a message integrity check
	// to ensure that the encryption key was transmitted without error.
	//
	// If you encrypt an object by using server-side encryption with customer-provided
	// encryption keys (SSE-C) when you store the object in Amazon S3, then when you
	// GET the object, you must use the following headers:
	//
	//   - x-amz-server-side-encryption-customer-algorithm
	//
	//   - x-amz-server-side-encryption-customer-key
	//
	//   - x-amz-server-side-encryption-customer-key-MD5
	//
	// For more information about SSE-C, see [Server-Side Encryption (Using Customer-Provided Encryption Keys)] in the Amazon S3 User Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [Server-Side Encryption (Using Customer-Provided Encryption Keys)]: https://docs.aws.amazon.com/AmazonS3/latest/dev/ServerSideEncryptionCustomerKeys.html
	SSECustomerKeyMD5 *string

	// Version ID used to reference a specific version of the object.
	//
	// By default, the GetObject operation returns the current version of an object.
	// To return a different version, use the versionId subresource.
	//
	//   - If you include a versionId in your request header, you must have the
	//   s3:GetObjectVersion permission to access a specific version of an object. The
	//   s3:GetObject permission is not required in this scenario.
	//
	//   - If you request the current version of an object without a specific versionId
	//   in the request header, only the s3:GetObject permission is required. The
	//   s3:GetObjectVersion permission is not required in this scenario.
	//
	//   - Directory buckets - S3 Versioning isn't enabled and supported for directory
	//   buckets. For this API operation, only the null value of the version ID is
	//   supported by directory buckets. You can only specify null to the versionId
	//   query parameter in the request.
	//
	// For more information about versioning, see [PutBucketVersioning].
	//
	// [PutBucketVersioning]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketVersioning.html
	VersionID *string
}

func (i DownloadObjectInput) mapGetObjectInput(enableChecksumValidation bool) *s3.GetObjectInput {
	input := &s3.GetObjectInput{
		Bucket:                     i.Bucket,
		Key:                        i.Key,
		ExpectedBucketOwner:        i.ExpectedBucketOwner,
		IfMatch:                    i.IfMatch,
		IfNoneMatch:                i.IfNoneMatch,
		IfModifiedSince:            i.IfModifiedSince,
		IfUnmodifiedSince:          i.IfUnmodifiedSince,
		RequestPayer:               s3types.RequestPayer(i.RequestPayer),
		ResponseCacheControl:       i.ResponseCacheControl,
		ResponseContentDisposition: i.ResponseContentDisposition,
		ResponseContentEncoding:    i.ResponseContentEncoding,
		ResponseContentLanguage:    i.ResponseContentLanguage,
		ResponseContentType:        i.ResponseContentType,
		ResponseExpires:            i.ResponseExpires,
		SSECustomerAlgorithm:       i.SSECustomerAlgorithm,
		SSECustomerKey:             i.SSECustomerKey,
		SSECustomerKeyMD5:          i.SSECustomerKeyMD5,
		VersionId:                  i.VersionID,
	}

	if i.ChecksumMode != "" {
		input.ChecksumMode = s3types.ChecksumMode(i.ChecksumMode)
	} else if enableChecksumValidation {
		input.ChecksumMode = s3types.ChecksumModeEnabled
	}

	return input
}

// DownloadObjectOutput represents a response from DownloadObject() call. It contains common fields
// of s3 GetObject output except Body which is replaced by WriterAt of input
type DownloadObjectOutput struct {
	// Indicates that a range of bytes was specified in the request.
	AcceptRanges *string

	// Indicates whether the object uses an S3 Bucket Key for server-side encryption
	// with Key Management Service (KMS) keys (SSE-KMS).
	BucketKeyEnabled *bool

	// Specifies caching behavior along the request/reply chain.
	CacheControl *string

	// Specifies if the response checksum validation is enabled
	ChecksumMode types.ChecksumMode

	// The base64-encoded, 32-bit CRC-32 checksum of the object. This will only be
	// present if it was uploaded with the object. For more information, see [Checking object integrity]in the
	// Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC32 *string

	// The base64-encoded, 32-bit CRC-32C checksum of the object. This will only be
	// present if it was uploaded with the object. For more information, see [Checking object integrity]in the
	// Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC32C *string

	// The Base64 encoded, 64-bit CRC64NVME checksum of the object. For more
	// information, see [Checking object integrity in the Amazon S3 User Guide].
	//
	// [Checking object integrity in the Amazon S3 User Guide]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC64NVME *string

	// The base64-encoded, 160-bit SHA-1 digest of the object. This will only be
	// present if it was uploaded with the object. For more information, see [Checking object integrity]in the
	// Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumSHA1 *string

	// The base64-encoded, 256-bit SHA-256 digest of the object. This will only be
	// present if it was uploaded with the object. For more information, see [Checking object integrity]in the
	// Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumSHA256 *string

	// The checksum type, which determines how part-level checksums are combined to
	// create an object-level checksum for multipart objects. You can use this header
	// response to verify that the checksum type that is received is the same checksum
	// type that was specified in the CreateMultipartUpload request. For more
	// information, see [Checking object integrity]in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumType types.ChecksumType

	// Specifies presentational information for the object.
	ContentDisposition *string

	// Indicates what content encodings have been applied to the object and thus what
	// decoding mechanisms must be applied to obtain the media-type referenced by the
	// Content-Type header field.
	ContentEncoding *string

	// The language the content is in.
	ContentLanguage *string

	// Size of the body in bytes.
	ContentLength *int64

	// The portion of the object returned in the response.
	ContentRange *string

	// A standard MIME type describing the format of the object data.
	ContentType *string

	// Indicates whether the object retrieved was (true) or was not (false) a Delete
	// Marker. If false, this response header does not appear in the response.
	//
	//   - If the current version of the object is a delete marker, Amazon S3 behaves
	//   as if the object was deleted and includes x-amz-delete-marker: true in the
	//   response.
	//
	//   - If the specified version in the request is a delete marker, the response
	//   returns a 405 Method Not Allowed error and the Last-Modified: timestamp
	//   response header.
	DeleteMarker *bool

	// An entity tag (ETag) is an opaque identifier assigned by a web server to a
	// specific version of a resource found at a URL.
	ETag *string

	// If the object expiration is configured (see [PutBucketLifecycleConfiguration]PutBucketLifecycleConfiguration ),
	// the response includes this header. It includes the expiry-date and rule-id
	// key-value pairs providing object expiration information. The value of the
	// rule-id is URL-encoded.
	//
	// This functionality is not supported for directory buckets.
	//
	// [PutBucketLifecycleConfiguration]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutBucketLifecycleConfiguration.html
	Expiration *string

	// The date and time at which the object is no longer cacheable.
	//
	// Deprecated: This field is handled inconsistently across AWS SDKs. Prefer using
	// the ExpiresString field which contains the unparsed value from the service
	// response.
	Expires *time.Time

	// The unparsed value of the Expires field from the service response. Prefer use
	// of this value over the normal Expires response field where possible.
	ExpiresString *string

	// Date and time when the object was last modified.
	//
	// General purpose buckets - When you specify a versionId of the object in your
	// request, if the specified version in the request is a delete marker, the
	// response returns a 405 Method Not Allowed error and the Last-Modified: timestamp
	// response header.
	LastModified *time.Time

	// A map of metadata to store with the object in S3.
	//
	// Map keys will be normalized to lower-case.
	Metadata map[string]string

	// This is set to the number of metadata entries not returned in the headers that
	// are prefixed with x-amz-meta- . This can happen if you create metadata using an
	// API like SOAP that supports more flexible metadata than the REST API. For
	// example, using SOAP, you can create metadata whose values are not legal HTTP
	// headers.
	//
	// This functionality is not supported for directory buckets.
	MissingMeta *int32

	// Indicates whether this object has an active legal hold. This field is only
	// returned if you have permission to view an object's legal hold status.
	//
	// This functionality is not supported for directory buckets.
	ObjectLockLegalHoldStatus types.ObjectLockLegalHoldStatus

	// The Object Lock mode that's currently in place for this object.
	//
	// This functionality is not supported for directory buckets.
	ObjectLockMode types.ObjectLockMode

	// The date and time when this object's Object Lock will expire.
	//
	// This functionality is not supported for directory buckets.
	ObjectLockRetainUntilDate *time.Time

	// The count of parts this object has. This value is only returned if you specify
	// partNumber in your request and the object was uploaded as a multipart upload.
	PartsCount *int32

	// Amazon S3 can return this if your request involves a bucket that is either a
	// source or destination in a replication rule.
	//
	// This functionality is not supported for directory buckets.
	ReplicationStatus types.ReplicationStatus

	// If present, indicates that the requester was successfully charged for the
	// request.
	//
	// This functionality is not supported for directory buckets.
	RequestCharged types.RequestCharged

	// Provides information about object restoration action and expiration time of the
	// restored object copy.
	//
	// This functionality is not supported for directory buckets. Only the S3 Express
	// One Zone storage class is supported by directory buckets to store objects.
	Restore *string

	// If server-side encryption with a customer-provided encryption key was
	// requested, the response will include this header to confirm the encryption
	// algorithm that's used.
	//
	// This functionality is not supported for directory buckets.
	SSECustomerAlgorithm *string

	// If server-side encryption with a customer-provided encryption key was
	// requested, the response will include this header to provide the round-trip
	// message integrity verification of the customer-provided encryption key.
	//
	// This functionality is not supported for directory buckets.
	SSECustomerKeyMD5 *string

	// If present, indicates the ID of the KMS key that was used for object encryption.
	SSEKMSKeyID *string

	// The server-side encryption algorithm used when you store this object in Amazon
	// S3.
	ServerSideEncryption types.ServerSideEncryption

	// Provides storage class information of the object. Amazon S3 returns this header
	// for all objects except for S3 Standard storage class objects.
	//
	// Directory buckets - Only the S3 Express One Zone storage class is supported by
	// directory buckets to store objects.
	StorageClass types.StorageClass

	// The number of tags, if any, on the object, when you have the relevant
	// permission to read object tags.
	//
	// You can use [GetObjectTagging] to retrieve the tag set associated with an object.
	//
	// This functionality is not supported for directory buckets.
	//
	// [GetObjectTagging]: https://docs.aws.amazon.com/AmazonS3/latest/API/API_GetObjectTagging.html
	TagCount *int32

	// Version ID of the object.
	//
	// This functionality is not supported for directory buckets.
	VersionID *string

	// If the bucket is configured as a website, redirects requests for this object to
	// another object in the same bucket or to an external URL. Amazon S3 stores the
	// value of this header in the object metadata.
	//
	// This functionality is not supported for directory buckets.
	WebsiteRedirectLocation *string

	// Metadata pertaining to the operation's result.
	ResultMetadata smithymiddleware.Metadata
}

func (o *DownloadObjectOutput) mapFromGetObjectOutput(out *s3.GetObjectOutput, checksumMode s3types.ChecksumMode) {
	o.AcceptRanges = out.AcceptRanges
	o.BucketKeyEnabled = out.BucketKeyEnabled
	o.CacheControl = out.CacheControl
	o.ChecksumMode = types.ChecksumMode(checksumMode)
	o.ChecksumCRC32 = out.ChecksumCRC32
	o.ChecksumCRC32C = out.ChecksumCRC32C
	o.ChecksumCRC64NVME = out.ChecksumCRC64NVME
	o.ChecksumSHA1 = out.ChecksumSHA1
	o.ChecksumSHA256 = out.ChecksumSHA256
	o.ChecksumType = types.ChecksumType(out.ChecksumType)
	o.ContentDisposition = out.ContentDisposition
	o.ContentEncoding = out.ContentEncoding
	o.ContentLanguage = out.ContentLanguage
	o.ContentLength = out.ContentLength
	o.ContentRange = out.ContentRange
	o.ContentType = out.ContentType
	o.DeleteMarker = out.DeleteMarker
	o.ETag = out.ETag
	o.Expiration = out.Expiration
	o.Expires = out.Expires
	o.ExpiresString = out.ExpiresString
	o.LastModified = out.LastModified
	o.Metadata = out.Metadata
	o.MissingMeta = out.MissingMeta
	o.ObjectLockLegalHoldStatus = types.ObjectLockLegalHoldStatus(out.ObjectLockLegalHoldStatus)
	o.ObjectLockMode = types.ObjectLockMode(out.ObjectLockMode)
	o.ObjectLockRetainUntilDate = out.ObjectLockRetainUntilDate
	o.PartsCount = out.PartsCount
	o.ReplicationStatus = types.ReplicationStatus(out.ReplicationStatus)
	o.RequestCharged = types.RequestCharged(out.RequestCharged)
	o.Restore = out.Restore
	o.SSECustomerAlgorithm = out.SSECustomerAlgorithm
	o.SSECustomerKeyMD5 = out.SSECustomerKeyMD5
	o.SSEKMSKeyID = out.SSEKMSKeyId
	o.ServerSideEncryption = types.ServerSideEncryption(out.ServerSideEncryption)
	o.StorageClass = types.StorageClass(out.StorageClass)
	o.TagCount = out.TagCount
	o.VersionID = out.VersionId
	o.WebsiteRedirectLocation = out.WebsiteRedirectLocation
	o.ResultMetadata = out.ResultMetadata
}

// DownloadObject downloads an object from S3, intelligently splitting large
// files into smaller parts/ranges according to config and getting them in parallel across
// multiple goroutines. You can configure the download type, chunk size and concurrency
// through the Options parameters.
//
// Additional functional options can be provided to configure the individual
// download. These options are copies of the original Options instance, the client of which DownloadObject is called from.
// Modifying the options will not impact the original Client and Options instance.
func (c *Client) DownloadObject(ctx context.Context, input *DownloadObjectInput, opts ...func(*Options)) (*DownloadObjectOutput, error) {
	i := downloader{in: input, options: c.options.Copy()}
	for _, opt := range opts {
		opt(&i.options)
	}

	return i.download(ctx)
}

type downloader struct {
	options Options
	in      *DownloadObjectInput
	out     *DownloadObjectOutput

	wg             sync.WaitGroup
	m              sync.Mutex
	etagOnce       sync.Once
	totalBytesOnce sync.Once

	offset     int64
	pos        int64
	totalBytes int64
	written    atomic.Int64
	etag       string

	err error

	emitter *singleObjectProgressEmitter
}

func (d *downloader) download(ctx context.Context) (*DownloadObjectOutput, error) {
	if err := d.init(); err != nil {
		return nil, fmt.Errorf("unable to initialize download: %w", err)
	}

	clientOptions := []func(*s3.Options){
		func(o *s3.Options) {
			o.APIOptions = append(o.APIOptions,
				middleware.AddSDKAgentKey(middleware.FeatureMetadata, userAgentKey),
				addFeatureUserAgent,
			)
		}}

	var output *DownloadObjectOutput
	if d.options.GetObjectType == types.GetObjectParts {
		output = d.getChunk(ctx, 1, "", clientOptions...)
		if d.err != nil {
			freshCtx, cancel := d.freshContext(ctx)
			defer cancel()
			d.emitter.Failed(freshCtx, d.err)
			return output, d.err
		}

		if aws.ToInt32(output.PartsCount) > 1 {
			partSize := aws.ToInt64(output.ContentLength)
			ch := make(chan dlChunk, d.options.Concurrency)
			for i := 0; i < d.options.Concurrency; i++ {
				d.wg.Add(1)
				go d.downloadPart(ctx, ch, clientOptions...)
			}

			for i := int32(2); i <= aws.ToInt32(output.PartsCount); i++ {
				if d.getErr() != nil {
					break
				}

				ch <- dlChunk{w: d.in.WriterAt, start: d.pos - d.offset, part: i}
				d.pos += partSize
			}

			close(ch)
			d.wg.Wait()
		}
	} else {
		if rng := aws.ToString(d.in.Range); rng != "" {
			rangeStart, rangeEnd, err := getReqRange(rng)
			if err != nil {
				freshCtx, cancel := d.freshContext(ctx)
				defer cancel()
				d.emitter.Failed(freshCtx, d.err)
				return nil, err
			}
			d.offset = rangeStart
			d.totalBytes = rangeEnd + 1
			d.pos = rangeStart
		}
		d.getChunk(ctx, 0, d.byteRange(), clientOptions...)
		if d.err != nil {
			// early check to see if error is caused by range download a zero object
			// which will always return an invalid range error from s3 side
			var responseError interface {
				HTTPStatusCode() int
			}
			if errors.As(d.err, &responseError) {
				if responseError.HTTPStatusCode() == http.StatusRequestedRangeNotSatisfiable {
					out := &DownloadObjectOutput{
						ContentLength: aws.Int64(0),
					}
					d.emitter.Complete(ctx, out)
					return out, nil
				}
			}
			freshCtx, cancel := d.freshContext(ctx)
			defer cancel()
			d.emitter.Failed(freshCtx, d.err)
			return nil, d.err
		}
		total := d.totalBytes

		ch := make(chan dlChunk, d.options.Concurrency)
		for i := 0; i < d.options.Concurrency; i++ {
			d.wg.Add(1)
			go d.downloadPart(ctx, ch, clientOptions...)
		}

		// Assign work
		for d.getErr() == nil {
			if d.pos >= total {
				break // We finish queuing chunks
			}

			// Queue the next range of bytes to read.
			ch <- dlChunk{w: d.in.WriterAt, start: d.pos - d.offset, withRange: d.byteRange()}
			d.pos += d.options.PartSizeBytes
		}

		// Wait for completion
		close(ch)
		d.wg.Wait()
	}

	if d.err != nil {
		freshCtx, cancel := d.freshContext(ctx)
		defer cancel()
		d.emitter.Failed(freshCtx, d.err)
		return nil, d.err
	}

	d.emitter.Complete(ctx, d.out)

	d.out.ContentRange = aws.String(fmt.Sprintf("bytes=%d-%d", d.offset, d.totalBytes-1))
	d.out.ContentLength = aws.Int64(d.written.Load())
	if d.out.ChecksumType == types.ChecksumTypeComposite {
		d.out.ChecksumCRC32 = nil
		d.out.ChecksumCRC32C = nil
		d.out.ChecksumCRC64NVME = nil
		d.out.ChecksumSHA1 = nil
		d.out.ChecksumSHA256 = nil
	}
	return d.out, nil
}

func (d *downloader) init() error {
	if d.options.PartBodyMaxRetries < 0 {
		return fmt.Errorf("part body retry must be non-negative")
	}

	d.totalBytes = -1
	d.emitter = &singleObjectProgressEmitter{
		Listeners: d.options.ObjectProgressListeners,
	}

	return nil
}

func (d *downloader) downloadPart(ctx context.Context, ch chan dlChunk, clientOptions ...func(*s3.Options)) {
	defer d.wg.Done()
	for {
		chunk, ok := <-ch
		if !ok {
			break
		}
		if d.getErr() != nil {
			continue
		}
		out, err := d.downloadChunk(ctx, chunk, clientOptions...)
		if err != nil {
			d.setErr(err)
		} else {
			d.setOutput(out)
		}
	}
}

// getChunk grabs a chunk of data from the body.
// Not thread safe. Should only be used when grabbing data on a single thread.
func (d *downloader) getChunk(ctx context.Context, part int32, rng string, clientOptions ...func(*s3.Options)) *DownloadObjectOutput {
	chunk := dlChunk{w: d.in.WriterAt, start: d.pos - d.offset, part: part, withRange: rng}

	output, err := d.downloadChunk(ctx, chunk, clientOptions...)
	if err != nil {
		d.setErr(err)
		return output
	}

	d.setOutput(output)
	d.pos += aws.ToInt64(output.ContentLength)
	return output
}

// downloadChunk downloads the chunk from s3
func (d *downloader) downloadChunk(ctx context.Context, chunk dlChunk, clientOptions ...func(*s3.Options)) (*DownloadObjectOutput, error) {
	params := d.in.mapGetObjectInput(!d.options.DisableChecksumValidation)
	if chunk.part != 0 {
		params.PartNumber = aws.Int32(chunk.part)
	}
	if chunk.withRange != "" {
		params.Range = aws.String(chunk.withRange)
	}
	if params.VersionId == nil && d.etag != "" {
		params.IfMatch = aws.String(d.etag)
	}

	var out *s3.GetObjectOutput
	var err error
	for retry := 0; retry < d.options.PartBodyMaxRetries; retry++ {
		out, err = d.tryDownloadChunk(ctx, params, &chunk, clientOptions...)
		if err == nil {
			break
		}
		// Check if the returned error is an errReadingBody.
		// If err is errReadingBody this indicates that an error
		// occurred while copying the http response body.
		// If this occurs we unwrap the err to set the underlying error
		// and attempt any remaining retries.
		if bodyErr, ok := err.(*errReadingBody); ok {
			err = bodyErr
		} else {
			return nil, err
		}

		chunk.cur = 0
	}

	var output *DownloadObjectOutput
	if out != nil {
		output = &DownloadObjectOutput{}
		output.mapFromGetObjectOutput(out, params.ChecksumMode)
		d.etagOnce.Do(func() {
			d.etag = aws.ToString(out.ETag)
		})
	}
	return output, err
}

func (d *downloader) tryDownloadChunk(ctx context.Context, params *s3.GetObjectInput, chunk *dlChunk, clientOptions ...func(*s3.Options)) (*s3.GetObjectOutput, error) {
	out, err := d.options.S3.GetObject(ctx, params, clientOptions...)
	if err != nil {
		return nil, err
	}

	if params.Range != nil && out.ContentRange != nil {
		reqStart, reqEnd, err := getReqRange(aws.ToString(params.Range))
		if err != nil {
			return nil, err
		}
		respStart, respEnd, err := getRespRange(aws.ToString(out.ContentRange))
		if err != nil {
			return nil, err
		}
		// don't validate first chunk since object size is unknown when getting that
		if reqStart != 0 && (reqStart != respStart || reqEnd != respEnd) {
			return nil, fmt.Errorf("range mismatch between request %d-%d and response %d-%d", reqStart, reqEnd, respStart, respEnd)
		}
	}

	d.totalBytesOnce.Do(func() {
		d.setTotalBytes(out)
		d.emitter.Start(ctx, d.in, d.totalBytes-d.offset)
	}) // Set total in first GET

	var n int64
	defer out.Body.Close()
	n, err = io.Copy(chunk, out.Body)
	if err != nil {
		return nil, &errReadingBody{err: err}
	}

	d.written.Add(n)
	d.emitter.BytesTransferred(ctx, n)
	return out, nil
}

// setTotalBytes is a thread-safe setter for setting the total byte status.
// Will extract the object's total bytes from the Content-Range if the file
// will be chunked, or Content-Length. Content-Length is used when the response
// does not include a Content-Range. Meaning the object was not chunked. This
// occurs when the full file fits within the PartSize directive.
func (d *downloader) setTotalBytes(resp *s3.GetObjectOutput) {
	if d.totalBytes >= 0 {
		return
	}

	if resp.ContentRange == nil {
		// ContentRange is nil when the full file contents is provided, and
		// is not chunked. Use ContentLength instead.
		d.totalBytes = aws.ToInt64(resp.ContentLength)
	} else {
		parts := strings.Split(*resp.ContentRange, "/")
		totalStr := parts[len(parts)-1]
		total, err := strconv.ParseInt(totalStr, 10, 64)
		if err != nil {
			d.err = err
			return
		}

		d.totalBytes = total
	}
}

func (d *downloader) freshContext(ctx context.Context) (context.Context, context.CancelFunc) {
	if d.options.FailTimeout <= 0 {
		return ctx, func() {}
	}
	return context.WithTimeout(context.Background(), d.options.FailTimeout)
}

func (d *downloader) setOutput(resp *DownloadObjectOutput) {
	d.m.Lock()
	defer d.m.Unlock()

	if d.out != nil {
		return
	}
	d.out = resp
}

// byteRange returns a HTTP Byte-Range header value that should be used by the
// client to request a chunk range.
func (d *downloader) byteRange() string {
	if d.totalBytes >= 0 {
		return fmt.Sprintf("bytes=%d-%d", d.pos, int64(math.Min(float64(d.totalBytes-1), float64(d.pos+d.options.PartSizeBytes-1))))
	}
	return fmt.Sprintf("bytes=%d-%d", d.pos, d.pos+d.options.PartSizeBytes-1)
}

func getReqRange(rng string) (int64, int64, error) {
	// rng fmt "bytes=start-end"
	rangeFmt := strings.Split(rng, "=")
	if len(rangeFmt) != 2 {
		return -1, -1, fmt.Errorf("invalid range format %s, should be bytes=start-end format", rng)
	}
	startEnd := strings.Split(rangeFmt[1], "-")
	if len(startEnd) != 2 {
		return -1, -1, fmt.Errorf("invalid range format %s, should be bytes=start-end format", rng)
	}

	start, err := strconv.ParseInt(startEnd[0], 10, 64)
	if err != nil {
		return -1, -1, fmt.Errorf("invalid range start %v", err)
	}
	end, err := strconv.ParseInt(startEnd[1], 10, 64)
	if err != nil {
		return -1, -1, fmt.Errorf("invalid range end %v", err)
	}
	return start, end, nil
}

func getRespRange(rng string) (int64, int64, error) {
	// rng format "bytes %d-%d/%d"
	ranges := strings.Split(strings.Split(strings.Split(rng, " ")[1], "/")[0], "-")
	start, err := strconv.ParseInt(ranges[0], 10, 64)
	if err != nil {
		return 0, 0, fmt.Errorf("error when parsing response start: %v", err)
	}
	end, err := strconv.ParseInt(ranges[1], 10, 64)
	if err != nil {
		return 0, 0, fmt.Errorf("error when parsing response end: %v", err)
	}
	return start, end, nil
}

func (d *downloader) getErr() error {
	d.m.Lock()
	defer d.m.Unlock()

	return d.err
}

func (d *downloader) setErr(e error) {
	d.m.Lock()
	defer d.m.Unlock()

	d.err = e
}

type dlChunk struct {
	w io.WriterAt

	start int64
	cur   int64

	part      int32
	withRange string
}

func (c *dlChunk) Write(p []byte) (int, error) {
	n, err := c.w.WriteAt(p, c.start+c.cur)
	c.cur += int64(n)

	return n, err
}
