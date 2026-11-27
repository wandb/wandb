package types

import (
	"io"
	"sync"

	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

// ReadSeekCloser wraps a io.Reader returning a ReaderSeekerCloser. Allows the
// SDK to accept an io.Reader that is not also an io.Seeker for unsigned
// streaming payload API operations.
//
// A readSeekCloser wrapping an nonseekable io.Reader used in an API operation's
// input will prevent that operation being retried in the case of
// network errors, and cause operation requests to fail if the operation
// requires payload signing.
func ReadSeekCloser(r io.Reader) *ReaderSeekerCloser {
	return &ReaderSeekerCloser{r}
}

// ReaderSeekerCloser represents a reader that can also delegate io.Seeker and
// io.Closer interfaces to the underlying object if they are available.
type ReaderSeekerCloser struct {
	r io.Reader
}

// SeekerLen attempts to get the number of bytes remaining at the seeker's
// current position.  Returns the number of bytes remaining or error.
func SeekerLen(s io.Seeker) (int64, error) {
	// Determine if the seeker is actually seekable. ReaderSeekerCloser
	// hides the fact that a io.Readers might not actually be seekable.
	switch v := s.(type) {
	case *ReaderSeekerCloser:
		return v.GetLen()
	}

	return computeSeekerLength(s)
}

// GetLen returns the length of the bytes remaining in the underlying reader.
// Checks first for Len(), then io.Seeker to determine the size of the
// underlying reader.
//
// Will return -1 if the length cannot be determined.
func (r *ReaderSeekerCloser) GetLen() (int64, error) {
	if l, ok := r.HasLen(); ok {
		return int64(l), nil
	}

	if s, ok := r.r.(io.Seeker); ok {
		return computeSeekerLength(s)
	}

	return -1, nil
}

func computeSeekerLength(s io.Seeker) (int64, error) {
	curOffset, err := s.Seek(0, io.SeekCurrent)
	if err != nil {
		return 0, err
	}

	endOffset, err := s.Seek(0, io.SeekEnd)
	if err != nil {
		return 0, err
	}

	_, err = s.Seek(curOffset, io.SeekStart)
	if err != nil {
		return 0, err
	}

	return endOffset - curOffset, nil
}

// HasLen returns the length of the underlying reader if the value implements
// the Len() int method.
func (r *ReaderSeekerCloser) HasLen() (int, bool) {
	type lenner interface {
		Len() int
	}

	if lr, ok := r.r.(lenner); ok {
		return lr.Len(), true
	}

	return 0, false
}

// Read reads from the reader up to size of p. The number of bytes read, and
// error if it occurred will be returned.
//
// If the reader is not an io.Reader zero bytes read, and nil error will be
// returned.
//
// Performs the same functionality as io.Reader Read
func (r *ReaderSeekerCloser) Read(p []byte) (int, error) {
	switch t := r.r.(type) {
	case io.Reader:
		return t.Read(p)
	}
	return 0, nil
}

// Seek sets the offset for the next Read to offset, interpreted according to
// whence: 0 means relative to the origin of the file, 1 means relative to the
// current offset, and 2 means relative to the end. Seek returns the new offset
// and an error, if any.
//
// If the ReaderSeekerCloser is not an io.Seeker nothing will be done.
func (r *ReaderSeekerCloser) Seek(offset int64, whence int) (int64, error) {
	switch t := r.r.(type) {
	case io.Seeker:
		return t.Seek(offset, whence)
	}
	return int64(0), nil
}

// IsSeeker returns if the underlying reader is also a seeker.
func (r *ReaderSeekerCloser) IsSeeker() bool {
	_, ok := r.r.(io.Seeker)
	return ok
}

// Close closes the ReaderSeekerCloser.
//
// If the ReaderSeekerCloser is not an io.Closer nothing will be done.
func (r *ReaderSeekerCloser) Close() error {
	switch t := r.r.(type) {
	case io.Closer:
		return t.Close()
	}
	return nil
}

// ChecksumAlgorithm indicates the algorithm used to create the checksum for the object
type ChecksumAlgorithm string

// Enum values for ChecksumAlgorithm
const (
	ChecksumAlgorithmCrc32  ChecksumAlgorithm = "CRC32"
	ChecksumAlgorithmCrc32c                   = "CRC32C"
	ChecksumAlgorithmSha1                     = "SHA1"
	ChecksumAlgorithmSha256                   = "SHA256"
	ChecksumAlgorithmSha512                   = "SHA512"
)

// ObjectCannedACL defines the canned ACL to apply to the object, see [Canned ACL] in the
// Amazon S3 User Guide.
type ObjectCannedACL string

// Enum values for ObjectCannedACL
const (
	ObjectCannedACLPrivate                ObjectCannedACL = "private"
	ObjectCannedACLPublicRead                             = "public-read"
	ObjectCannedACLPublicReadWrite                        = "public-read-write"
	ObjectCannedACLAuthenticatedRead                      = "authenticated-read"
	ObjectCannedACLAwsExecRead                            = "aws-exec-read"
	ObjectCannedACLBucketOwnerRead                        = "bucket-owner-read"
	ObjectCannedACLBucketOwnerFullControl                 = "bucket-owner-full-control"
)

// Values returns all known values for ObjectCannedACL. Note that this can be
// expanded in the future, and so it is only as up to date as the client.
//
// The ordering of this slice is not guaranteed to be stable across updates.
func (ObjectCannedACL) Values() []ObjectCannedACL {
	return []ObjectCannedACL{
		"private",
		"public-read",
		"public-read-write",
		"authenticated-read",
		"aws-exec-read",
		"bucket-owner-read",
		"bucket-owner-full-control",
	}
}

// ObjectLockLegalHoldStatus specifies whether a legal hold will be applied to this object. For more
// information about S3 Object Lock, see [Object Lock] in the Amazon S3 User Guide.
type ObjectLockLegalHoldStatus string

// Enum values for ObjectLockLegalHoldStatus
const (
	ObjectLockLegalHoldStatusOn  ObjectLockLegalHoldStatus = "ON"
	ObjectLockLegalHoldStatusOff                           = "OFF"
)

// ObjectLockMode is the Object Lock mode that you want to apply to this object.
type ObjectLockMode string

// Enum values for ObjectLockMode
const (
	ObjectLockModeGovernance ObjectLockMode = "GOVERNANCE"
	ObjectLockModeCompliance                = "COMPLIANCE"
)

// RequestPayer confirms that the requester knows that they will be charged for the request.
// Bucket owners need not specify this parameter in their requests. If either the
// source or destination S3 bucket has Requester Pays enabled, the requester will
// pay for corresponding charges to copy the object. For information about
// downloading objects from Requester Pays buckets, see [Downloading Objects in Requester Pays Buckets]in the Amazon S3 User
// Guide.
type RequestPayer string

// Enum values for RequestPayer
const (
	RequestPayerRequester RequestPayer = "requester"
)

// ServerSideEncryption indicates the server-side encryption algorithm that was used when you store this object
// in Amazon S3 (for example, AES256 , aws:kms , aws:kms:dsse )
type ServerSideEncryption string

// Enum values for ServerSideEncryption
const (
	ServerSideEncryptionAes256     ServerSideEncryption = "AES256"
	ServerSideEncryptionAwsKms                          = "aws:kms"
	ServerSideEncryptionAwsKmsDsse                      = "aws:kms:dsse"
)

// StorageClass specifies class to store newly created
// objects, which has default value of STANDARD. For more information, see
// [Storage Classes] in the Amazon S3 User Guide.
type StorageClass string

// Enum values for StorageClass
const (
	StorageClassStandard           StorageClass = "STANDARD"
	StorageClassReducedRedundancy               = "REDUCED_REDUNDANCY"
	StorageClassStandardIa                      = "STANDARD_IA"
	StorageClassOnezoneIa                       = "ONEZONE_IA"
	StorageClassIntelligentTiering              = "INTELLIGENT_TIERING"
	StorageClassGlacier                         = "GLACIER"
	StorageClassDeepArchive                     = "DEEP_ARCHIVE"
	StorageClassOutposts                        = "OUTPOSTS"
	StorageClassGlacierIr                       = "GLACIER_IR"
	StorageClassSnow                            = "SNOW"
	StorageClassExpressOnezone                  = "EXPRESS_ONEZONE"
)

// CompletedPart includes details of the parts that were uploaded.
type CompletedPart struct {

	// The base64-encoded, 32-bit CRC32 checksum of the object. This will only be
	// present if it was uploaded with the object. When you use an API operation on an
	// object that was uploaded using multipart uploads, this value may not be a direct
	// checksum value of the full object. Instead, it's a calculation based on the
	// checksum values of each individual part. For more information about how
	// checksums are calculated with multipart uploads, see [Checking object integrity]in the Amazon S3 User
	// Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums
	ChecksumCRC32 *string

	// The base64-encoded, 32-bit CRC32C checksum of the object. This will only be
	// present if it was uploaded with the object. When you use an API operation on an
	// object that was uploaded using multipart uploads, this value may not be a direct
	// checksum value of the full object. Instead, it's a calculation based on the
	// checksum values of each individual part. For more information about how
	// checksums are calculated with multipart uploads, see [Checking object integrity]in the Amazon S3 User
	// Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums
	ChecksumCRC32C *string

	// The base64-encoded, 160-bit SHA-1 digest of the object. This will only be
	// present if it was uploaded with the object. When you use the API operation on an
	// object that was uploaded using multipart uploads, this value may not be a direct
	// checksum value of the full object. Instead, it's a calculation based on the
	// checksum values of each individual part. For more information about how
	// checksums are calculated with multipart uploads, see [Checking object integrity]in the Amazon S3 User
	// Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums
	ChecksumSHA1 *string

	// The base64-encoded, 256-bit SHA-256 digest of the object. This will only be
	// present if it was uploaded with the object. When you use an API operation on an
	// object that was uploaded using multipart uploads, this value may not be a direct
	// checksum value of the full object. Instead, it's a calculation based on the
	// checksum values of each individual part. For more information about how
	// checksums are calculated with multipart uploads, see [Checking object integrity]in the Amazon S3 User
	// Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums
	ChecksumSHA256 *string

	// The base64-encoded, 512-bit SHA-512 digest of the object. This will only be
	// present if it was uploaded with the object. When you use an API operation on an
	// object that was uploaded using multipart uploads, this value may not be a direct
	// checksum value of the full object. Instead, it's a calculation based on the
	// checksum values of each individual part. For more information about how
	// checksums are calculated with multipart uploads, see [Checking object integrity]in the Amazon S3 User
	// Guide.
	//
	// [Checking object integrity]: https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity.html#large-object-checksums
	ChecksumSHA512 *string

	// Entity tag returned when the part was uploaded.
	ETag *string

	// Part number that identifies the part. This is a positive integer between 1 and
	// 10,000.
	//
	//   - General purpose buckets - In CompleteMultipartUpload , when a additional
	//   checksum (including x-amz-checksum-crc32 , x-amz-checksum-crc32c ,
	//   x-amz-checksum-sha1 , or x-amz-checksum-sha256 ) is applied to each part, the
	//   PartNumber must start at 1 and the part numbers must be consecutive.
	//   Otherwise, Amazon S3 generates an HTTP 400 Bad Request status code and an
	//   InvalidPartOrder error code.
	//
	//   - Directory buckets - In CompleteMultipartUpload , the PartNumber must start
	//   at 1 and the part numbers must be consecutive.
	PartNumber *int32
}

// MapCompletedPart maps CompletedPart to s3 types
func (cp CompletedPart) MapCompletedPart() types.CompletedPart {
	return types.CompletedPart{
		ChecksumCRC32:  cp.ChecksumCRC32,
		ChecksumCRC32C: cp.ChecksumCRC32C,
		ChecksumSHA1:   cp.ChecksumSHA1,
		ChecksumSHA256: cp.ChecksumSHA256,
		ChecksumSHA512: cp.ChecksumSHA512,
		ETag:           cp.ETag,
		PartNumber:     cp.PartNumber,
	}
}

// MapFrom set CompletedPart fields from s3 UploadPartOutput
func (cp *CompletedPart) MapFrom(resp *s3.UploadPartOutput, partNum *int32) {
	cp.ChecksumCRC32 = resp.ChecksumCRC32
	cp.ChecksumCRC32C = resp.ChecksumCRC32C
	cp.ChecksumSHA1 = resp.ChecksumSHA1
	cp.ChecksumSHA256 = resp.ChecksumSHA256
	cp.ChecksumSHA512 = resp.ChecksumSHA512
	cp.ETag = resp.ETag
	cp.PartNumber = partNum
}

// RequestCharged indicates that the requester was successfully charged for the request.
type RequestCharged string

// Enum values for RequestCharged
const (
	RequestChargedRequester RequestCharged = "requester"
)

// Metadata provides storing and reading metadata values. Keys may be any
// comparable value type. Get and set will panic if key is not a comparable
// value type.
//
// Metadata uses lazy initialization, and Set method must be called as an
// addressable value, or pointer. Not doing so may cause key/value pair to not
// be set.
type Metadata struct {
	values map[interface{}]interface{}
}

// GetObjectType specifies how transfer manager should perform multipart download
type GetObjectType string

// Enum values for MultipartDownloadType
const (
	GetObjectParts  GetObjectType = "PART"
	GetObjectRanges               = "RANGE"
)

// ChecksumMode indicates if the response checksum validation is enabled
type ChecksumMode string

// Enum values for ChecksumMode
const (
	ChecksumModeEnabled ChecksumMode = "ENABLED"
)

// ReplicationStatus indicates if your request involves a bucket that's either a
// source or destination in a replication rule
type ReplicationStatus string

// Enum values for ReplicationStatus
const (
	ReplicationStatusComplete  ReplicationStatus = "COMPLETE"
	ReplicationStatusPending   ReplicationStatus = "PENDING"
	ReplicationStatusFailed    ReplicationStatus = "FAILED"
	ReplicationStatusReplica   ReplicationStatus = "REPLICA"
	ReplicationStatusCompleted ReplicationStatus = "COMPLETED"
)

// A WriteAtBuffer provides a in memory buffer supporting the io.WriterAt interface
// Can be used with the s3manager.Downloader to download content to a buffer
// in memory. Safe to use concurrently.
type WriteAtBuffer struct {
	buf []byte
	m   sync.Mutex

	// GrowthCoeff defines the growth rate of the internal buffer. By
	// default, the growth rate is 1, where expanding the internal
	// buffer will allocate only enough capacity to fit the new expected
	// length.
	GrowthCoeff float64
}

// NewWriteAtBuffer creates a WriteAtBuffer with an internal buffer
// provided by buf.
func NewWriteAtBuffer(buf []byte) *WriteAtBuffer {
	return &WriteAtBuffer{buf: buf}
}

// WriteAt writes a slice of bytes to a buffer starting at the position provided
// The number of bytes written will be returned, or error. Can overwrite previous
// written slices if the write ats overlap.
func (b *WriteAtBuffer) WriteAt(p []byte, pos int64) (n int, err error) {
	pLen := len(p)
	expLen := pos + int64(pLen)
	b.m.Lock()
	defer b.m.Unlock()
	if int64(len(b.buf)) < expLen {
		if int64(cap(b.buf)) < expLen {
			if b.GrowthCoeff < 1 {
				b.GrowthCoeff = 1
			}
			newBuf := make([]byte, expLen, int64(b.GrowthCoeff*float64(expLen)))
			copy(newBuf, b.buf)
			b.buf = newBuf
		}
		b.buf = b.buf[:expLen]
	}
	copy(b.buf[pos:], p)
	return pLen, nil
}

// Bytes returns a slice of bytes written to the buffer.
func (b *WriteAtBuffer) Bytes() []byte {
	b.m.Lock()
	defer b.m.Unlock()
	return b.buf
}

// ChecksumType represents the transfer checksum type
type ChecksumType string

// Enum values for ChecksumType
const (
	ChecksumTypeComposite  ChecksumType = "COMPOSITE"
	ChecksumTypeFullObject ChecksumType = "FULL_OBJECT"
)
