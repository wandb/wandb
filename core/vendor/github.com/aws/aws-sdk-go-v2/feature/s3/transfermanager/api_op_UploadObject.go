package transfermanager

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"sort"
	"sync"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/aws/middleware"
	"github.com/aws/aws-sdk-go-v2/feature/s3/transfermanager/types"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	s3types "github.com/aws/aws-sdk-go-v2/service/s3/types"
	smithymiddleware "github.com/aws/smithy-go/middleware"
)

// A MultipartUploadError wraps a failed S3 multipart upload. An error returned
// will satisfy this interface when a multi part upload failed to upload all
// chucks to S3. In the case of a failure the UploadID is needed to operate on
// the chunks, if any, which were uploaded.
//
// Example:
//
//	c := transfermanager.New(client, opts)
//	output, err := c.PutObject(context.Background(), input)
//	if err != nil {
//		var multierr transfermanager.MultipartUploadError
//		if errors.As(err, &multierr) {
//			fmt.Printf("upload failure UploadID=%s, %s\n", multierr.UploadID(), multierr.Error())
//		} else {
//			fmt.Printf("upload failure, %s\n", err.Error())
//		}
//	}
type MultipartUploadError interface {
	error

	// UploadID returns the upload id for the S3 multipart upload that failed.
	UploadID() string
}

// A multipartUploadError wraps the upload ID of a failed s3 multipart upload.
// Composed of BaseError for code, message, and original error
//
// Should be used for an error that occurred failing a S3 multipart upload,
// and a upload ID is available.
type multipartUploadError struct {
	err error

	// ID for multipart upload which failed.
	uploadID string
}

// Error returns the string representation of the error.
//
// Satisfies the error interface.
func (m *multipartUploadError) Error() string {
	var extra string
	if m.err != nil {
		extra = fmt.Sprintf(", cause: %s", m.err.Error())
	}
	return fmt.Sprintf("upload multipart failed, upload id: %s%s", m.uploadID, extra)
}

// Unwrap returns the underlying error that cause the upload failure
func (m *multipartUploadError) Unwrap() error {
	return m.err
}

// UploadID returns the id of the S3 upload which failed.
func (m *multipartUploadError) UploadID() string {
	return m.uploadID
}

// UploadObjectInput represents a request to the PutObject() call. It contains common fields
// of s3 PutObject and CreateMultipartUpload input
type UploadObjectInput struct {
	// Bucket the object is uploaded into
	Bucket *string

	// Object key for which the PUT action was initiated
	Key *string

	// Object data
	Body io.Reader

	// The canned ACL to apply to the object. For more information, see [Canned ACL] in the Amazon
	// S3 User Guide.
	//
	// When adding a new object, you can use headers to grant ACL-based permissions to
	// individual Amazon Web Services accounts or to predefined groups defined by
	// Amazon S3. These permissions are then added to the ACL on the object. By
	// default, all objects are private. Only the owner has full access control. For
	// more information, see [Access Control List (ACL) Overview]and [Managing ACLs Using the REST API] in the Amazon S3 User Guide.
	//
	// If the bucket that you're uploading objects to uses the bucket owner enforced
	// setting for S3 Object Ownership, ACLs are disabled and no longer affect
	// permissions. Buckets that use this setting only accept PUT requests that don't
	// specify an ACL or PUT requests that specify bucket owner full control ACLs, such
	// as the bucket-owner-full-control canned ACL or an equivalent form of this ACL
	// expressed in the XML format. PUT requests that contain other ACLs (for example,
	// custom grants to certain Amazon Web Services accounts) fail and return a 400
	// error with the error code AccessControlListNotSupported . For more information,
	// see [Controlling ownership of objects and disabling ACLs]in the Amazon S3 User Guide.
	//
	//   - This functionality is not supported for directory buckets.
	//
	//   - This functionality is not supported for Amazon S3 on Outposts.
	//
	// [Managing ACLs Using the REST API]: https://docs.aws.amazon.com/AmazonS3/latest/dev/acl-using-rest-api.html
	// [Access Control List (ACL) Overview]: https://docs.aws.amazon.com/AmazonS3/latest/dev/acl-overview.html
	// [Canned ACL]: https://docs.aws.amazon.com/AmazonS3/latest/dev/acl-overview.html#CannedACL
	// [Controlling ownership of objects and disabling ACLs]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html
	ACL types.ObjectCannedACL

	// Specifies whether Amazon S3 should use an S3 Bucket Key for object encryption
	// with server-side encryption using Key Management Service (KMS) keys (SSE-KMS).
	// Setting this header to true causes Amazon S3 to use an S3 Bucket Key for object
	// encryption with SSE-KMS.
	//
	// Specifying this header with a PUT action doesn’t affect bucket-level settings
	// for S3 Bucket Key.
	//
	// This functionality is not supported for directory buckets.
	BucketKeyEnabled *bool

	// Can be used to specify caching behavior along the request/reply chain. For more
	// information, see [http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.9].
	//
	// [http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.9]: http://www.w3.org/Protocols/rfc2616/rfc2616-sec14.html#sec14.9
	CacheControl *string

	// Indicates the algorithm used to create the checksum for the object when you use
	// the SDK. This header will not provide any additional functionality if you don't
	// use the SDK. When you send this header, there must be a corresponding
	// x-amz-checksum-algorithm or x-amz-trailer header sent. Otherwise, Amazon S3
	// fails the request with the HTTP status code 400 Bad Request .
	//
	// For the x-amz-checksum-algorithm  header, replace  algorithm  with the
	// supported algorithm from the following list:
	//
	//   - CRC32
	//
	//   - CRC32C
	//
	//   - SHA1
	//
	//   - SHA256
	//
	// For more information, see [Checking object integrity] in the Amazon S3 User Guide.
	//
	// If the individual checksum value you provide through x-amz-checksum-algorithm
	// doesn't match the checksum algorithm you set through
	// x-amz-sdk-checksum-algorithm , Amazon S3 ignores any provided ChecksumAlgorithm
	// parameter and uses the checksum algorithm that matches the provided value in
	// x-amz-checksum-algorithm .
	//
	// For directory buckets, when you use Amazon Web Services SDKs, CRC32 is the
	// default checksum algorithm that's used for performance.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumAlgorithm types.ChecksumAlgorithm

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 32-bit CRC32 checksum of the object. For more information, see [Checking object integrity]
	// in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC32 *string

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 32-bit CRC32C checksum of the object. For more information, see [Checking object integrity]
	// in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC32C *string

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 64-bit CRC64NVME checksum of the object. The CRC64NVME checksum
	// is always a full object checksum. For more information, see [Checking object integrity in the Amazon S3 User Guide].
	//
	// [Checking object integrity in the Amazon S3 User Guide]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumCRC64NVME *string

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 160-bit SHA1 digest of the object. For more information, see [Checking object integrity]
	// in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumSHA1 *string

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 256-bit SHA256 digest of the object. For more information, see [Checking object integrity]
	// in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumSHA256 *string

	// This header can be used as a data integrity check to verify that the data
	// received is the same data that was originally sent. This header specifies the
	// Base64 encoded, 512-bit SHA512 digest of the object. For more information, see [Checking object integrity]
	// in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumSHA512 *string

	// Indicates the checksum type that you want Amazon S3 to use to calculate the
	// object’s checksum value. For more information, see [Checking object integrity in the Amazon S3 User Guide].
	//
	// [Checking object integrity in the Amazon S3 User Guide]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumType types.ChecksumType

	// Size of the body in bytes. This parameter is useful when the size of the body
	// cannot be determined automatically. For more information, see [https://www.rfc-editor.org/rfc/rfc9110.html#name-content-length].
	//
	// [https://www.rfc-editor.org/rfc/rfc9110.html#name-content-length]: https://www.rfc-editor.org/rfc/rfc9110.html#name-content-length
	ContentLength *int64

	// Specifies presentational information for the object. For more information, see [https://www.rfc-editor.org/rfc/rfc6266#section-4].
	//
	// [https://www.rfc-editor.org/rfc/rfc6266#section-4]: https://www.rfc-editor.org/rfc/rfc6266#section-4
	ContentDisposition *string

	// Specifies what content encodings have been applied to the object and thus what
	// decoding mechanisms must be applied to obtain the media-type referenced by the
	// Content-Type header field. For more information, see [https://www.rfc-editor.org/rfc/rfc9110.html#field.content-encoding].
	//
	// [https://www.rfc-editor.org/rfc/rfc9110.html#field.content-encoding]: https://www.rfc-editor.org/rfc/rfc9110.html#field.content-encoding
	ContentEncoding *string

	// The language the content is in.
	ContentLanguage *string

	// A standard MIME type describing the format of the contents. For more
	// information, see [https://www.rfc-editor.org/rfc/rfc9110.html#name-content-type].
	//
	// [https://www.rfc-editor.org/rfc/rfc9110.html#name-content-type]: https://www.rfc-editor.org/rfc/rfc9110.html#name-content-type
	ContentType *string

	// The account ID of the expected bucket owner. If the account ID that you provide
	// does not match the actual owner of the bucket, the request fails with the HTTP
	// status code 403 Forbidden (access denied).
	ExpectedBucketOwner *string

	// The date and time at which the object is no longer cacheable. For more
	// information, see [https://www.rfc-editor.org/rfc/rfc7234#section-5.3].
	//
	// [https://www.rfc-editor.org/rfc/rfc7234#section-5.3]: https://www.rfc-editor.org/rfc/rfc7234#section-5.3
	Expires *time.Time

	// Gives the grantee READ, READ_ACP, and WRITE_ACP permissions on the object.
	//
	//   - This functionality is not supported for directory buckets.
	//
	//   - This functionality is not supported for Amazon S3 on Outposts.
	GrantFullControl *string

	// Allows grantee to read the object data and its metadata.
	//
	//   - This functionality is not supported for directory buckets.
	//
	//   - This functionality is not supported for Amazon S3 on Outposts.
	GrantRead *string

	// Allows grantee to read the object ACL.
	//
	//   - This functionality is not supported for directory buckets.
	//
	//   - This functionality is not supported for Amazon S3 on Outposts.
	GrantReadACP *string

	// Allows grantee to write the ACL for the applicable object.
	//
	//   - This functionality is not supported for directory buckets.
	//
	//   - This functionality is not supported for Amazon S3 on Outposts.
	GrantWriteACP *string

	// Uploads the object only if the ETag (entity tag) value provided during the
	// WRITE operation matches the ETag of the object in S3. If the ETag values do not
	// match, the operation returns a 412 Precondition Failed error.
	//
	// If a conflicting operation occurs during the upload S3 returns a 409
	// ConditionalRequestConflict response. On a 409 failure you should fetch the
	// object's ETag and retry the upload.
	//
	// Expects the ETag value as a string.
	//
	// For more information about conditional requests, see [RFC 7232], or [Conditional requests] in the Amazon S3
	// User Guide.
	//
	// [Conditional requests]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-requests.html
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfMatch *string

	// Uploads the object only if the object key name does not already exist in the
	// bucket specified. Otherwise, Amazon S3 returns a 412 Precondition Failed error.
	//
	// If a conflicting operation occurs during the upload S3 returns a 409
	// ConditionalRequestConflict response. On a 409 failure you should retry the
	// upload.
	//
	// Expects the '*' (asterisk) character.
	//
	// For more information about conditional requests, see [RFC 7232], or [Conditional requests] in the Amazon S3
	// User Guide.
	//
	// [Conditional requests]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-requests.html
	// [RFC 7232]: https://tools.ietf.org/html/rfc7232
	IfNoneMatch *string

	// A map of metadata to store with the object in S3.
	Metadata map[string]string

	//  The expected total object size of the multipart upload request. If there’s a
	// mismatch between the specified object size value and the actual object size
	// value, it results in an HTTP 400 InvalidRequest error.
	MpuObjectSize *int64

	// Specifies whether a legal hold will be applied to this object. For more
	// information about S3 Object Lock, see [Object Lock]in the Amazon S3 User Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [Object Lock]: https://docs.aws.amazon.com/AmazonS3/latest/dev/object-lock.html
	ObjectLockLegalHoldStatus types.ObjectLockLegalHoldStatus

	// The Object Lock mode that you want to apply to this object.
	//
	// This functionality is not supported for directory buckets.
	ObjectLockMode types.ObjectLockMode

	// The date and time when you want this object's Object Lock to expire. Must be
	// formatted as a timestamp parameter.
	//
	// This functionality is not supported for directory buckets.
	ObjectLockRetainUntilDate *time.Time

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

	// Specifies the algorithm to use when encrypting the object (for example, AES256 ).
	//
	// This functionality is not supported for directory buckets.
	SSECustomerAlgorithm *string

	// Specifies the customer-provided encryption key for Amazon S3 to use in
	// encrypting data. This value is used to store the object and then it is
	// discarded; Amazon S3 does not store the encryption key. The key must be
	// appropriate for use with the algorithm specified in the
	// x-amz-server-side-encryption-customer-algorithm header.
	//
	// This functionality is not supported for directory buckets.
	SSECustomerKey *string

	// Specifies the 128-bit MD5 digest of the encryption key according to RFC 1321.
	// Amazon S3 uses this header for a message integrity check to ensure that the
	// encryption key was transmitted without error.
	//
	// This functionality is not supported for directory buckets.
	SSECustomerKeyMD5 *string

	// Specifies the Amazon Web Services KMS Encryption Context to use for object
	// encryption. The value of this header is a base64-encoded UTF-8 string holding
	// JSON with the encryption context key-value pairs. This value is stored as object
	// metadata and automatically gets passed on to Amazon Web Services KMS for future
	// GetObject or CopyObject operations on this object. This value must be
	// explicitly added during CopyObject operations.
	//
	// This functionality is not supported for directory buckets.
	SSEKMSEncryptionContext *string

	// If x-amz-server-side-encryption has a valid value of aws:kms or aws:kms:dsse ,
	// this header specifies the ID (Key ID, Key ARN, or Key Alias) of the Key
	// Management Service (KMS) symmetric encryption customer managed key that was used
	// for the object. If you specify x-amz-server-side-encryption:aws:kms or
	// x-amz-server-side-encryption:aws:kms:dsse , but do not provide
	// x-amz-server-side-encryption-aws-kms-key-id , Amazon S3 uses the Amazon Web
	// Services managed key ( aws/s3 ) to protect the data. If the KMS key does not
	// exist in the same account that's issuing the command, you must use the full ARN
	// and not just the ID.
	//
	// This functionality is not supported for directory buckets.
	SSEKMSKeyID *string

	// The server-side encryption algorithm that was used when you store this object
	// in Amazon S3 (for example, AES256 , aws:kms , aws:kms:dsse ).
	//
	// General purpose buckets - You have four mutually exclusive options to protect
	// data using server-side encryption in Amazon S3, depending on how you choose to
	// manage the encryption keys. Specifically, the encryption key options are Amazon
	// S3 managed keys (SSE-S3), Amazon Web Services KMS keys (SSE-KMS or DSSE-KMS),
	// and customer-provided keys (SSE-C). Amazon S3 encrypts data with server-side
	// encryption by using Amazon S3 managed keys (SSE-S3) by default. You can
	// optionally tell Amazon S3 to encrypt data at rest by using server-side
	// encryption with other key options. For more information, see [Using Server-Side Encryption]in the Amazon S3
	// User Guide.
	//
	// Directory buckets - For directory buckets, only the server-side encryption with
	// Amazon S3 managed keys (SSE-S3) ( AES256 ) value is supported.
	//
	// [Using Server-Side Encryption]: https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingServerSideEncryption.html
	ServerSideEncryption types.ServerSideEncryption

	// By default, Amazon S3 uses the STANDARD Storage Class to store newly created
	// objects. The STANDARD storage class provides high durability and high
	// availability. Depending on performance needs, you can specify a different
	// Storage Class. For more information, see [Storage Classes]in the Amazon S3 User Guide.
	//
	//   - For directory buckets, only the S3 Express One Zone storage class is
	//   supported to store newly created objects.
	//
	//   - Amazon S3 on Outposts only uses the OUTPOSTS Storage Class.
	//
	// [Storage Classes]: https://docs.aws.amazon.com/AmazonS3/latest/dev/storage-class-intro.html
	StorageClass types.StorageClass

	// The tag-set for the object. The tag-set must be encoded as URL Query
	// parameters. (For example, "Key1=Value1")
	//
	// This functionality is not supported for directory buckets.
	Tagging *string

	// If the bucket is configured as a website, redirects requests for this object to
	// another object in the same bucket or to an external URL. Amazon S3 stores the
	// value of this header in the object metadata. For information about object
	// metadata, see [Object Key and Metadata]in the Amazon S3 User Guide.
	//
	// In the following example, the request header sets the redirect to an object
	// (anotherPage.html) in the same bucket:
	//
	//     x-amz-website-redirect-location: /anotherPage.html
	//
	// In the following example, the request header sets the object redirect to
	// another website:
	//
	//     x-amz-website-redirect-location: http://www.example.com/
	//
	// For more information about website hosting in Amazon S3, see [Hosting Websites on Amazon S3] and [How to Configure Website Page Redirects] in the
	// Amazon S3 User Guide.
	//
	// This functionality is not supported for directory buckets.
	//
	// [How to Configure Website Page Redirects]: https://docs.aws.amazon.com/AmazonS3/latest/dev/how-to-page-redirect.html
	// [Hosting Websites on Amazon S3]: https://docs.aws.amazon.com/AmazonS3/latest/dev/WebsiteHosting.html
	// [Object Key and Metadata]: https://docs.aws.amazon.com/AmazonS3/latest/dev/UsingMetadata.html
	WebsiteRedirectLocation *string
}

// map non-zero string to *string
func nzstring(v string) *string {
	if v == "" {
		return nil
	}
	return aws.String(v)
}

// map non-zero Time to *Time
func nztime(t time.Time) *time.Time {
	if t.IsZero() {
		return nil
	}
	return aws.Time(t)
}

func (i UploadObjectInput) mapSingleUploadInput(body io.Reader, checksumAlgorithm types.ChecksumAlgorithm) *s3.PutObjectInput {
	input := &s3.PutObjectInput{
		Bucket:                    i.Bucket,
		Key:                       i.Key,
		Body:                      body,
		ACL:                       s3types.ObjectCannedACL(i.ACL),
		BucketKeyEnabled:          i.BucketKeyEnabled,
		CacheControl:              i.CacheControl,
		ChecksumCRC32:             i.ChecksumCRC32,
		ChecksumCRC32C:            i.ChecksumCRC32C,
		ChecksumCRC64NVME:         i.ChecksumCRC64NVME,
		ChecksumSHA1:              i.ChecksumSHA1,
		ChecksumSHA256:            i.ChecksumSHA256,
		ChecksumSHA512:            i.ChecksumSHA512,
		ContentDisposition:        i.ContentDisposition,
		ContentEncoding:           i.ContentEncoding,
		ContentLanguage:           i.ContentLanguage,
		ContentType:               i.ContentType,
		ExpectedBucketOwner:       i.ExpectedBucketOwner,
		Expires:                   i.Expires,
		GrantFullControl:          i.GrantFullControl,
		GrantRead:                 i.GrantRead,
		GrantReadACP:              i.GrantReadACP,
		GrantWriteACP:             i.GrantWriteACP,
		IfMatch:                   i.IfMatch,
		IfNoneMatch:               i.IfNoneMatch,
		Metadata:                  i.Metadata,
		ObjectLockLegalHoldStatus: s3types.ObjectLockLegalHoldStatus(i.ObjectLockLegalHoldStatus),
		ObjectLockMode:            s3types.ObjectLockMode(i.ObjectLockMode),
		ObjectLockRetainUntilDate: i.ObjectLockRetainUntilDate,
		RequestPayer:              s3types.RequestPayer(i.RequestPayer),
		SSECustomerAlgorithm:      i.SSECustomerAlgorithm,
		SSECustomerKey:            i.SSECustomerKey,
		SSECustomerKeyMD5:         i.SSECustomerKeyMD5,
		SSEKMSEncryptionContext:   i.SSEKMSEncryptionContext,
		SSEKMSKeyId:               i.SSEKMSKeyID,
		ServerSideEncryption:      s3types.ServerSideEncryption(i.ServerSideEncryption),
		StorageClass:              s3types.StorageClass(i.StorageClass),
		Tagging:                   i.Tagging,
		WebsiteRedirectLocation:   i.WebsiteRedirectLocation,
	}
	if i.ChecksumAlgorithm != "" {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(i.ChecksumAlgorithm)
	} else {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(checksumAlgorithm)
	}

	return input
}

func (i UploadObjectInput) mapCreateMultipartUploadInput(checksumAlgorithm types.ChecksumAlgorithm) *s3.CreateMultipartUploadInput {
	input := &s3.CreateMultipartUploadInput{
		Bucket:                    i.Bucket,
		Key:                       i.Key,
		ACL:                       s3types.ObjectCannedACL(i.ACL),
		BucketKeyEnabled:          i.BucketKeyEnabled,
		CacheControl:              i.CacheControl,
		ChecksumType:              s3types.ChecksumType(i.ChecksumType),
		ContentDisposition:        i.ContentDisposition,
		ContentEncoding:           i.ContentEncoding,
		ContentLanguage:           i.ContentLanguage,
		ContentType:               i.ContentType,
		ExpectedBucketOwner:       i.ExpectedBucketOwner,
		Expires:                   i.Expires,
		GrantFullControl:          i.GrantFullControl,
		GrantRead:                 i.GrantRead,
		GrantReadACP:              i.GrantReadACP,
		GrantWriteACP:             i.GrantWriteACP,
		Metadata:                  i.Metadata,
		ObjectLockLegalHoldStatus: s3types.ObjectLockLegalHoldStatus(i.ObjectLockLegalHoldStatus),
		ObjectLockMode:            s3types.ObjectLockMode(i.ObjectLockMode),
		ObjectLockRetainUntilDate: i.ObjectLockRetainUntilDate,
		RequestPayer:              s3types.RequestPayer(i.RequestPayer),
		SSECustomerAlgorithm:      i.SSECustomerAlgorithm,
		SSECustomerKey:            i.SSECustomerKey,
		SSECustomerKeyMD5:         i.SSECustomerKeyMD5,
		SSEKMSEncryptionContext:   i.SSEKMSEncryptionContext,
		SSEKMSKeyId:               i.SSEKMSKeyID,
		ServerSideEncryption:      s3types.ServerSideEncryption(i.ServerSideEncryption),
		StorageClass:              s3types.StorageClass(i.StorageClass),
		Tagging:                   i.Tagging,
		WebsiteRedirectLocation:   i.WebsiteRedirectLocation,
	}
	if i.ChecksumAlgorithm != "" {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(i.ChecksumAlgorithm)
	} else {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(checksumAlgorithm)
	}
	return input
}

func (i UploadObjectInput) mapCompleteMultipartUploadInput(uploadID *string, completedParts completedParts) *s3.CompleteMultipartUploadInput {
	input := &s3.CompleteMultipartUploadInput{
		Bucket:               i.Bucket,
		Key:                  i.Key,
		UploadId:             uploadID,
		ChecksumCRC32:        i.ChecksumCRC32,
		ChecksumCRC32C:       i.ChecksumCRC32C,
		ChecksumCRC64NVME:    i.ChecksumCRC64NVME,
		ChecksumSHA1:         i.ChecksumSHA1,
		ChecksumSHA256:       i.ChecksumSHA256,
		ChecksumSHA512:       i.ChecksumSHA512,
		ChecksumType:         s3types.ChecksumType(i.ChecksumType),
		ExpectedBucketOwner:  i.ExpectedBucketOwner,
		IfMatch:              i.IfMatch,
		IfNoneMatch:          i.IfNoneMatch,
		MpuObjectSize:        i.MpuObjectSize,
		RequestPayer:         s3types.RequestPayer(i.RequestPayer),
		SSECustomerAlgorithm: i.SSECustomerAlgorithm,
		SSECustomerKey:       i.SSECustomerKey,
		SSECustomerKeyMD5:    i.SSECustomerKeyMD5,
	}
	var parts []s3types.CompletedPart
	for _, part := range completedParts {
		parts = append(parts, part.MapCompletedPart())
	}
	if parts != nil {
		input.MultipartUpload = &s3types.CompletedMultipartUpload{Parts: parts}
	}
	return input
}

func (i UploadObjectInput) mapUploadPartInput(body io.Reader, partNum *int32, uploadID *string, checksumAlgorithm types.ChecksumAlgorithm) *s3.UploadPartInput {
	input := &s3.UploadPartInput{
		Bucket:               i.Bucket,
		Key:                  i.Key,
		Body:                 body,
		PartNumber:           partNum,
		UploadId:             uploadID,
		ExpectedBucketOwner:  i.ExpectedBucketOwner,
		RequestPayer:         s3types.RequestPayer(i.RequestPayer),
		SSECustomerAlgorithm: i.SSECustomerAlgorithm,
		SSECustomerKey:       i.SSECustomerKey,
		SSECustomerKeyMD5:    i.SSECustomerKeyMD5,
	}
	if i.ChecksumAlgorithm != "" {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(i.ChecksumAlgorithm)
	} else {
		input.ChecksumAlgorithm = s3types.ChecksumAlgorithm(checksumAlgorithm)
	}

	return input
}

func (i *UploadObjectInput) mapAbortMultipartUploadInput(uploadID *string) *s3.AbortMultipartUploadInput {
	input := &s3.AbortMultipartUploadInput{
		Bucket:              i.Bucket,
		Key:                 i.Key,
		UploadId:            uploadID,
		ExpectedBucketOwner: i.ExpectedBucketOwner,
		RequestPayer:        s3types.RequestPayer(i.RequestPayer),
	}
	return input
}

// UploadObjectOutput represents a response from the PutObject() call. It contains common fields
// of s3 PutObject and CompleteMultipartUpload output
type UploadObjectOutput struct {
	// The bucket where the newly created object is put
	Bucket *string

	// The object key of the newly created object.
	Key *string

	// Indicates whether the uploaded object uses an S3 Bucket Key for server-side
	// encryption with Amazon Web Services KMS (SSE-KMS).
	BucketKeyEnabled *bool

	// The base64-encoded, 32-bit CRC32 checksum of the object.
	ChecksumCRC32 *string

	// The base64-encoded, 32-bit CRC32C checksum of the object.
	ChecksumCRC32C *string

	// The Base64 encoded, 64-bit CRC64NVME checksum of the object.
	ChecksumCRC64NVME *string

	// The base64-encoded, 160-bit SHA-1 digest of the object.
	ChecksumSHA1 *string

	// The base64-encoded, 256-bit SHA-256 digest of the object.
	ChecksumSHA256 *string

	// The base64-encoded, 512-bit SHA-512 digest of the object.
	ChecksumSHA512 *string

	// This header specifies the checksum type of the object, which determines how
	// part-level checksums are combined to create an object-level checksum for
	// multipart objects. For PutObject uploads, the checksum type is always
	// FULL_OBJECT . You can use this header as a data integrity check to verify that
	// the checksum type that is received is the same checksum that was specified. For
	// more information, see [Checking object integrity]in the Amazon S3 User Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html
	ChecksumType types.ChecksumType

	// Entity tag for the uploaded object.
	ETag *string

	// If the object expiration is configured, this will contain the expiration date
	// (expiry-date) and rule ID (rule-id). The value of rule-id is URL encoded.
	Expiration *string

	// The URI that identifies the newly created object.
	Location *string

	// The ID for a multipart upload to S3. In the case of an error the error
	// can be cast to the MultiUploadFailure interface to extract the upload ID.
	// Will be empty string if multipart upload was not used, and the object
	// was uploaded as a single PutObject call.
	UploadID *string

	// The list of parts that were uploaded and their checksums. Will be empty
	// if multipart upload was not used, and the object was uploaded as a
	// single PutObject call.
	CompletedParts []types.CompletedPart

	// Total length of the object
	ContentLength *int64

	// If present, indicates that the requester was successfully charged for the
	// request.
	RequestCharged types.RequestCharged

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

	// If present, indicates the Amazon Web Services KMS Encryption Context to use for
	// object encryption. The value of this header is a Base64 encoded string of a
	// UTF-8 encoded JSON, which contains the encryption context as key-value pairs.
	// This value is stored as object metadata and automatically gets passed on to
	// Amazon Web Services KMS for future GetObject operations on this object.
	SSEKMSEncryptionContext *string

	// If present, specifies the ID of the Amazon Web Services Key Management Service
	// (Amazon Web Services KMS) symmetric customer managed customer master key (CMK)
	// that was used for the object.
	SSEKMSKeyID *string

	// If you specified server-side encryption either with an Amazon S3-managed
	// encryption key or an Amazon Web Services KMS customer master key (CMK) in your
	// initiate multipart upload request, the response includes this header. It
	// confirms the encryption algorithm that Amazon S3 used to encrypt the object.
	ServerSideEncryption types.ServerSideEncryption

	//  The size of the object in bytes. This value is only be present if you append
	// to an object.
	//
	// This functionality is only supported for objects in the Amazon S3 Express One
	// Zone storage class in directory buckets.
	Size *int64

	// The version of the object that was uploaded. Will only be populated if
	// the S3 Bucket is versioned. If the bucket is not versioned this field
	// will not be set.
	VersionID *string

	// Metadata pertaining to the operation's result.
	ResultMetadata smithymiddleware.Metadata
}

func (o *UploadObjectOutput) mapFromPutObjectOutput(out *s3.PutObjectOutput, bucket, key *string, contentLength int64) {
	o.Bucket = bucket
	o.Key = key
	o.BucketKeyEnabled = out.BucketKeyEnabled
	o.ChecksumCRC32 = out.ChecksumCRC32
	o.ChecksumCRC32C = out.ChecksumCRC32C
	o.ChecksumCRC64NVME = out.ChecksumCRC64NVME
	o.ChecksumSHA1 = out.ChecksumSHA1
	o.ChecksumSHA256 = out.ChecksumSHA256
	o.ChecksumSHA512 = out.ChecksumSHA512
	o.ChecksumType = types.ChecksumType(out.ChecksumType)
	o.ContentLength = aws.Int64(contentLength)
	o.ETag = out.ETag
	o.Expiration = out.Expiration
	o.RequestCharged = types.RequestCharged(out.RequestCharged)
	o.SSECustomerAlgorithm = out.SSECustomerAlgorithm
	o.SSECustomerKeyMD5 = out.SSECustomerKeyMD5
	o.SSEKMSEncryptionContext = out.SSEKMSEncryptionContext
	o.SSEKMSKeyID = out.SSEKMSKeyId
	o.ServerSideEncryption = types.ServerSideEncryption(out.ServerSideEncryption)
	o.Size = out.Size
	o.VersionID = out.VersionId
	o.ResultMetadata = out.ResultMetadata
}

func (o *UploadObjectOutput) mapFromCompleteMultipartUploadOutput(out *s3.CompleteMultipartUploadOutput, bucket, uploadID *string, contentLength int64, completedParts completedParts) {
	o.Bucket = bucket
	o.Key = out.Key
	o.UploadID = uploadID
	o.CompletedParts = completedParts
	o.BucketKeyEnabled = out.BucketKeyEnabled
	o.ChecksumCRC32 = out.ChecksumCRC32
	o.ChecksumCRC32C = out.ChecksumCRC32C
	o.ChecksumCRC64NVME = out.ChecksumCRC64NVME
	o.ChecksumSHA1 = out.ChecksumSHA1
	o.ChecksumSHA256 = out.ChecksumSHA256
	o.ChecksumSHA512 = out.ChecksumSHA512
	o.ChecksumType = types.ChecksumType(out.ChecksumType)
	o.ContentLength = aws.Int64(contentLength)
	o.ETag = out.ETag
	o.Expiration = out.Expiration
	o.Location = out.Location
	o.RequestCharged = types.RequestCharged(out.RequestCharged)
	o.SSEKMSKeyID = out.SSEKMSKeyId
	o.ServerSideEncryption = types.ServerSideEncryption(out.ServerSideEncryption)
	o.VersionID = out.VersionId
	o.ResultMetadata = out.ResultMetadata
}

// UploadObject uploads an object to S3, intelligently buffering large
// files into smaller chunks and sending them in parallel across multiple
// goroutines. You can configure the chunk size and concurrency through the
// Options parameters.
//
// Additional functional options can be provided to configure the individual
// upload. These options are copies of the original Options instance, the client of which UploadObject is called from.
// Modifying the options will not impact the original Client and Options instance.
func (c *Client) UploadObject(ctx context.Context, input *UploadObjectInput, opts ...func(*Options)) (*UploadObjectOutput, error) {
	i := uploader{in: input, options: c.options.Copy()}
	for _, opt := range opts {
		opt(&i.options)
	}

	return i.upload(ctx)
}

type uploader struct {
	options Options
	in      *UploadObjectInput

	// PartPool allows for the re-usage of streaming payload part buffers between upload calls
	partPool     bytesBufferPool
	objectSize   int64
	multipleRead bool

	progressEmitter *singleObjectProgressEmitter
}

func (u *uploader) upload(ctx context.Context) (*UploadObjectOutput, error) {
	if err := u.init(); err != nil {
		return nil, fmt.Errorf("unable to initialize upload: %w", err)
	}

	clientOptions := []func(o *s3.Options){
		func(o *s3.Options) {
			o.APIOptions = append(o.APIOptions,
				middleware.AddSDKAgentKey(middleware.FeatureMetadata, userAgentKey),
				addFeatureUserAgent,
			)
		}}

	r, n, cleanUp, err := u.nextReader(ctx)

	if err == io.EOF {
		return u.singleUpload(ctx, r, n, cleanUp, clientOptions...)
	} else if err != nil {
		cleanUp()
		return nil, err
	}

	u.partPool = newDefaultSlicePool(u.options.PartSizeBytes, u.options.Concurrency+1) // only create the caching pool for multipart upload
	defer u.partPool.Close()
	mu := multiUploader{
		uploader: u,
	}
	return mu.upload(ctx, r, n, cleanUp, clientOptions...)
}

func (u *uploader) init() error {
	u.progressEmitter = &singleObjectProgressEmitter{
		Listeners: u.options.ObjectProgressListeners,
	}
	if err := u.initSize(); err != nil {
		return err
	}

	return nil
}

// initSize checks user configured partsize and up-size it if calculated part count exceeds max value
func (u *uploader) initSize() error {
	u.objectSize = -1
	switch r := u.in.Body.(type) {
	case io.Seeker:
		n, err := types.SeekerLen(r)
		if err != nil {
			return err
		}
		u.objectSize = n
	default:
		if l := aws.ToInt64(u.in.ContentLength); l > 0 {
			u.objectSize = l
		}
	}

	if u.options.MaxUploadParts <= 0 || u.options.MaxUploadParts > defaultMaxUploadParts {
		return fmt.Errorf("max upload parts must be greater than 0 and less than %d", defaultMaxUploadParts)
	}
	// Try to adjust partSize if it is too small and account for
	// integer division truncation.
	if u.objectSize/u.options.PartSizeBytes >= u.options.MaxUploadParts {
		// Add one to the part size to account for remainders
		// during the size calculation. e.g odd number of bytes.
		u.options.PartSizeBytes = u.objectSize/u.options.MaxUploadParts + 1
	}
	return nil
}

func (u *uploader) singleUpload(ctx context.Context, r io.Reader, sz int, cleanUp func(), clientOptions ...func(*s3.Options)) (*UploadObjectOutput, error) {
	defer cleanUp()

	params := u.in.mapSingleUploadInput(r, u.options.ChecksumAlgorithm)
	objectSize := int64(sz)

	var loc recordLocationClient
	opts := append(clientOptions, loc.WrapClient())

	u.progressEmitter.Start(ctx, u.in, objectSize)
	out, err := u.options.S3.PutObject(ctx, params, opts...)
	if err != nil {
		freshCtx, cancel := u.freshContext(ctx)
		defer cancel()
		u.progressEmitter.Failed(freshCtx, err)
		return nil, err
	}

	var output UploadObjectOutput
	output.mapFromPutObjectOutput(out, u.in.Bucket, u.in.Key, objectSize)
	output.Location = nzstring(loc.location)

	u.progressEmitter.BytesTransferred(ctx, objectSize)
	u.progressEmitter.Complete(ctx, &output)
	return &output, nil
}

// nextReader reads the next chunk of data from input Body
func (u *uploader) nextReader(ctx context.Context) (io.Reader, int, func(), error) {
	if !u.multipleRead {
		u.multipleRead = true
		// read first part up to a maximum of PartSize to avoid allocating 8MB buffer out of the gate
		r := io.LimitReader(u.in.Body, u.options.MultipartUploadThreshold)
		firstPart, err := io.ReadAll(r)
		if err != nil {
			return nil, 0, func() {}, err
		}
		n := len(firstPart)
		if int64(n) < u.options.MultipartUploadThreshold {
			return bytes.NewReader(firstPart), n, func() {}, io.EOF
		}
		if int64(n) > u.options.PartSizeBytes {
			u.in.Body = io.MultiReader(bytes.NewReader(firstPart[u.options.PartSizeBytes:]), u.in.Body)
			return bytes.NewReader(firstPart[:u.options.PartSizeBytes]), int(u.options.PartSizeBytes), func() {}, nil
		}
		remainedBytes := u.options.PartSizeBytes - int64(n)
		r = io.LimitReader(u.in.Body, remainedBytes)
		remainedPart, err := io.ReadAll(r)
		if err != nil {
			return nil, 0, func() {}, err
		}
		firstPart = append(firstPart, remainedPart...)
		return bytes.NewReader(firstPart), len(firstPart), func() {}, nil
	}
	part, err := u.partPool.Get(ctx)
	if err != nil {
		return nil, 0, func() {}, err
	}

	n, err := readFillBuf(u.in.Body, part)

	cleanup := func() {
		u.partPool.Put(part)
	}
	return bytes.NewReader(part[0:n]), n, cleanup, err
}

func (u *uploader) freshContext(ctx context.Context) (context.Context, context.CancelFunc) {
	if u.options.FailTimeout <= 0 {
		return ctx, func() {}
	}
	return context.WithTimeout(context.Background(), u.options.FailTimeout)
}

func readFillBuf(r io.Reader, b []byte) (offset int, err error) {
	for offset < len(b) && err == nil {
		var n int
		n, err = r.Read(b[offset:])
		offset += n
	}
	return offset, err
}

type multiUploader struct {
	*uploader
	wg       sync.WaitGroup
	m        sync.Mutex
	err      error
	uploadID *string
	parts    completedParts
}

type ulChunk struct {
	buf     io.Reader
	buflen  int64
	partNum *int32
	cleanup func()
}

type completedParts []types.CompletedPart

func (cp completedParts) Len() int {
	return len(cp)
}

func (cp completedParts) Less(i, j int) bool {
	return aws.ToInt32(cp[i].PartNumber) < aws.ToInt32(cp[j].PartNumber)
}

func (cp completedParts) Swap(i, j int) {
	cp[i], cp[j] = cp[j], cp[i]
}

// upload will perform a multipart upload using the firstBuf buffer containing
// the first chunk of data.
func (u *multiUploader) upload(ctx context.Context, firstBuf io.Reader, firstBuflen int, cleanup func(), clientOptions ...func(*s3.Options)) (*UploadObjectOutput, error) {
	params := u.uploader.in.mapCreateMultipartUploadInput(u.options.ChecksumAlgorithm)

	// We are **ignoring** the output.Location here for backwards compat.
	//
	// In output.Location S3 URL-encodes the key (e.g. "a/b" -> "a%2Fb"). v1
	// (feature/s3/manager) used recordLocationClient which did not do that. We
	// are electing to preserve that behavior here.
	var loc recordLocationClient
	u.progressEmitter.Start(ctx, u.in, u.objectSize)
	resp, err := u.uploader.options.S3.CreateMultipartUpload(ctx, params,
		append(clientOptions, loc.WrapClient())...)
	if err != nil {
		cleanup()
		freshCtx, cancel := u.freshContext(ctx)
		defer cancel()
		u.progressEmitter.Failed(freshCtx, err)
		return nil, err
	}
	u.uploadID = resp.UploadId

	ch := make(chan ulChunk, u.options.Concurrency)
	for i := 0; i < u.options.Concurrency; i++ {
		// launch workers
		u.wg.Add(1)
		go u.readChunk(ctx, ch, clientOptions...)
	}

	var partNum int32 = 1
	ch <- ulChunk{
		buf:     firstBuf,
		buflen:  int64(firstBuflen),
		partNum: aws.Int32(partNum),
		cleanup: cleanup,
	}
	for u.geterr() == nil && err == nil {
		partNum++
		var (
			data         io.Reader
			nextChunkLen int
			ok           bool
		)
		data, nextChunkLen, cleanup, err = u.nextReader(ctx)
		ok, err = u.shouldContinue(partNum, nextChunkLen, err)
		if !ok {
			cleanup()
			if err != nil {
				u.seterr(err)
			}
			break
		}

		ch <- ulChunk{
			buf:     data,
			buflen:  int64(nextChunkLen),
			partNum: aws.Int32(partNum),
			cleanup: cleanup,
		}
	}

	// close the channel, wait for workers and complete upload
	close(ch)
	u.wg.Wait()
	completeOut := u.complete(ctx, clientOptions...)

	if err := u.geterr(); err != nil {
		freshCtx, cancel := u.freshContext(ctx)
		defer cancel()
		u.progressEmitter.Failed(freshCtx, err)
		return nil, &multipartUploadError{
			err:      err,
			uploadID: *u.uploadID,
		}
	}

	var out UploadObjectOutput
	out.mapFromCompleteMultipartUploadOutput(completeOut, params.Bucket, u.uploadID, u.progressEmitter.bytesTransferred.Load(), u.parts)
	out.Location = nzstring(loc.location)

	u.progressEmitter.Complete(ctx, &out)
	return &out, nil
}

func (u *multiUploader) shouldContinue(part int32, nextChunkLen int, err error) (bool, error) {
	if err != nil && err != io.EOF {
		return false, fmt.Errorf("read multipart upload data failed, %w", err)
	}

	if nextChunkLen == 0 {
		// No need to upload empty part, if file was empty to start
		// with empty single part would of been created and never
		// started multipart upload.
		return false, nil
	}

	// This upload exceeded maximum number of supported parts, error now.
	if int64(part) > u.options.MaxUploadParts {
		return false, fmt.Errorf("exceeded total allowed MaxUploadParts (%d). Adjust PartSize to fit in this limit", u.options.MaxUploadParts)
	}

	return true, err
}

// readChunk runs in worker goroutines to pull chunks off of the ch channel
// and send() them as UploadPart requests.
func (u *multiUploader) readChunk(ctx context.Context, ch chan ulChunk, clientOptions ...func(*s3.Options)) {
	defer u.wg.Done()
	for {
		data, ok := <-ch

		if !ok {
			break
		}

		if u.geterr() == nil {
			if err := u.send(ctx, data, clientOptions...); err != nil {
				u.seterr(err)
			}
		}

		data.cleanup()
	}
}

// send performs an UploadPart request and keeps track of the completed
// part information.
func (u *multiUploader) send(ctx context.Context, c ulChunk, clientOptions ...func(*s3.Options)) error {
	params := u.in.mapUploadPartInput(c.buf, c.partNum, u.uploadID, u.options.ChecksumAlgorithm)
	resp, err := u.options.S3.UploadPart(ctx, params, clientOptions...)
	if err != nil {
		// progress failed() is NOT emitted here, it's emitted once at the end
		return err
	}

	u.progressEmitter.BytesTransferred(ctx, c.buflen)
	var completed types.CompletedPart
	completed.MapFrom(resp, c.partNum)

	u.m.Lock()
	u.parts = append(u.parts, completed)
	u.m.Unlock()

	return nil
}

// geterr is a thread-safe getter for the error object
func (u *multiUploader) geterr() error {
	u.m.Lock()
	defer u.m.Unlock()

	return u.err
}

// seterr is a thread-safe setter for the error object
func (u *multiUploader) seterr(e error) {
	u.m.Lock()
	defer u.m.Unlock()

	u.err = e
}

func (u *multiUploader) fail(ctx context.Context, clientOptions ...func(*s3.Options)) {
	params := u.in.mapAbortMultipartUploadInput(u.uploadID)
	freshCtx, cancel := u.freshContext(ctx)
	defer cancel()
	_, err := u.options.S3.AbortMultipartUpload(freshCtx, params, clientOptions...)
	if err != nil {
		u.seterr(fmt.Errorf("failed to abort multipart upload (%v), triggered after multipart upload failed: %v", err, u.geterr()))
	}
}

// complete successfully completes a multipart upload and returns the response.
func (u *multiUploader) complete(ctx context.Context, clientOptions ...func(*s3.Options)) *s3.CompleteMultipartUploadOutput {
	if u.geterr() != nil {
		u.fail(ctx)
		return nil
	}

	// Parts must be sorted in PartNumber order.
	sort.Sort(u.parts)

	params := u.in.mapCompleteMultipartUploadInput(u.uploadID, u.parts)
	if params.MpuObjectSize == nil && u.objectSize > 0 {
		params.MpuObjectSize = aws.Int64(u.objectSize)
	}

	resp, err := u.options.S3.CompleteMultipartUpload(ctx, params, clientOptions...)
	if err != nil {
		u.seterr(err)
		log.Printf("failed to complete multipart upload for upload ID %v: %v", u.uploadID, err)
		u.fail(ctx)
	}

	return resp
}

func addFeatureUserAgent(stack *smithymiddleware.Stack) error {
	ua, err := getOrAddRequestUserAgent(stack)
	if err != nil {
		return err
	}

	ua.AddUserAgentFeature(middleware.UserAgentFeatureS3Transfer)
	return nil
}

func getOrAddRequestUserAgent(stack *smithymiddleware.Stack) (*middleware.RequestUserAgent, error) {
	id := (*middleware.RequestUserAgent)(nil).ID()
	mw, ok := stack.Build.Get(id)
	if !ok {
		mw = middleware.NewRequestUserAgent()
		if err := stack.Build.Add(mw, smithymiddleware.After); err != nil {
			return nil, err
		}
	}

	ua, ok := mw.(*middleware.RequestUserAgent)
	if !ok {
		return nil, fmt.Errorf("%T for %s middleware did not match expected type", mw, id)
	}

	return ua, nil
}

type httpClient interface {
	Do(r *http.Request) (*http.Response, error)
}

type recordLocationClient struct {
	httpClient
	location string
}

func (c *recordLocationClient) WrapClient() func(o *s3.Options) {
	return func(o *s3.Options) {
		c.httpClient = o.HTTPClient
		o.HTTPClient = c
	}
}

func (c *recordLocationClient) Do(r *http.Request) (resp *http.Response, err error) {
	resp, err = c.httpClient.Do(r)
	if err != nil {
		return resp, err
	}

	if resp.Request != nil && resp.Request.URL != nil {
		url := *resp.Request.URL
		url.RawQuery = ""
		c.location = url.String()
	}

	return resp, err
}
