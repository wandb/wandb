package main

import (
	"bytes"
	"context"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
	"github.com/aws/aws-sdk-go-v2/service/s3/types"
)

const FileProxyPort = 8182

type FileProxy struct {
	client              *http.Client
	missingHeaderLogger *log.Logger
	storagePrefix       string
	s3Client            *s3.Client
	bucketName          string
}

func NewFileProxy() *FileProxy {
	// Check for required environment variable
	storagePrefix := os.Getenv("WANDB_OBJECT_STORAGE_PREFIX")
	if storagePrefix == "" {
		log.Fatal("WANDB_OBJECT_STORAGE_PREFIX environment variable is not set.\n" +
			"For S3: Set to full bucket URL (e.g., https://bucket-name.s3.region.amazonaws.com)\n" +
			"For GCS: Set to domain only (e.g., https://storage.googleapis.com)")
	}

	// Remove trailing slash if present
	storagePrefix = strings.TrimRight(storagePrefix, "/")

	// Initialize AWS S3 client
	cfg, err := config.LoadDefaultConfig(context.TODO())
	if err != nil {
		log.Fatalf("Failed to load AWS config: %v", err)
	}

	// Override region if AWS_REGION is set
	if region := os.Getenv("AWS_REGION"); region != "" {
		cfg.Region = region
	}

	// Extract bucket name from storage prefix
	bucketName := extractBucketFromURL(storagePrefix)
	if bucketName == "" {
		log.Fatalf("Could not extract bucket name from storage prefix: %s", storagePrefix)
	}

	s3Client := s3.NewFromConfig(cfg)

	// Create logs directory if it doesn't exist
	os.MkdirAll("logs", 0755)

	// Create logger for missing headers
	file, err := os.OpenFile("logs/file_proxy_missing_header.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err != nil {
		log.Fatalf("Failed to open missing header log file: %v", err)
	}
	missingHeaderLogger := log.New(file, "", log.LstdFlags)

	return &FileProxy{
		client: &http.Client{
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		missingHeaderLogger: missingHeaderLogger,
		storagePrefix:       storagePrefix,
		s3Client:            s3Client,
		bucketName:          bucketName,
	}
}

// extractBucketFromURL extracts bucket name from S3 URL
func extractBucketFromURL(storagePrefix string) string {
	parsedURL, err := url.Parse(storagePrefix)
	if err != nil {
		return ""
	}

	// For URLs like https://bucket.s3.region.amazonaws.com
	if strings.Contains(parsedURL.Host, ".s3.") {
		parts := strings.Split(parsedURL.Host, ".")
		if len(parts) > 0 {
			return parts[0]
		}
	}

	// For path-style URLs like https://s3.region.amazonaws.com/bucket
	if strings.HasPrefix(parsedURL.Path, "/") {
		pathParts := strings.Split(strings.TrimPrefix(parsedURL.Path, "/"), "/")
		if len(pathParts) > 0 {
			return pathParts[0]
		}
	}

	return ""
}

func (p *FileProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	queryParams := r.URL.Query()

	s3URL := p.reconstructS3URL(r.URL.Path, r.URL.RawQuery)

	log.Printf("Incoming request: %s %s", r.Method, r.URL.String())
	log.Printf("Reconstructed S3 URL: %s", s3URL)

	// Check if any custom X-My-Header-* headers are present
	hasCustomHeader := false
	for header := range r.Header {
		if strings.HasPrefix(header, "X-My-Header-") {
			hasCustomHeader = true
			break
		}
	}

	// Log headers to main log
	// Check if this is an AWS SDK request (has Amz-Sdk-Invocation-Id header)
	isAWSSDKRequest := r.Header.Get("Amz-Sdk-Invocation-Id") != ""

	log.Printf("Headers received (AWS SDK: %v):", isAWSSDKRequest)
	for header, values := range r.Header {
		for _, value := range values {
			// Redact Authorization header for security
			if strings.ToLower(header) == "authorization" {
				if len(value) > 20 {
					log.Printf("  %s: %s...%s", header, value[:10], value[len(value)-4:])
				} else {
					log.Printf("  %s: [REDACTED]", header)
				}
			} else {
				log.Printf("  %s: %s", header, value)
			}
		}
	}

	// Handle AWS SDK requests with Go SDK instead of proxying
	if isAWSSDKRequest {
		p.handleAWSSDKRequest(w, r)
		return
	}

	// If custom headers are missing, also log to missing header file
	if !hasCustomHeader {
		p.missingHeaderLogger.Printf("Request: %s %s", r.Method, r.URL.Path)
		p.missingHeaderLogger.Printf("Headers:")
		for header, values := range r.Header {
			for _, value := range values {
				// Redact Authorization header for security
				if strings.ToLower(header) == "authorization" {
					if len(value) > 20 {
						p.missingHeaderLogger.Printf("  %s: %s...%s", header, value[:10], value[len(value)-4:])
					} else {
						p.missingHeaderLogger.Printf("  %s: [REDACTED]", header)
					}
				} else {
					p.missingHeaderLogger.Printf("  %s: %s", header, value)
				}
			}
		}
		p.missingHeaderLogger.Println("---")
	}

	if xUser := queryParams.Get("X-User"); xUser != "" {
		log.Printf("X-User from query params: %s", xUser)
	}

	proxyReq, err := http.NewRequest(r.Method, s3URL, r.Body)
	if err != nil {
		log.Printf("Error creating request: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	// Set the content length to avoid getting 501 not implemented error
	proxyReq.ContentLength = r.ContentLength

	// Don't forward certain headers to S3 that might interfere with presigned URLs
	for header, values := range r.Header {
		headerLower := strings.ToLower(header)
		// Skip headers that shouldn't be sent to S3
		// Transfer-Encoding is not supported by S3 and causes "NotImplemented" error
		// TODO: We need to that because both api proxy and file proxy runs on localhost
		if headerLower != "host" &&
			headerLower != "authorization" &&
			headerLower != "cookie" &&
			headerLower != "transfer-encoding" &&
			headerLower != "connection" {
			for _, value := range values {
				proxyReq.Header.Add(header, value)
			}
		}
	}

	log.Printf("Making request to S3: %s", s3URL)

	resp, err := p.client.Do(proxyReq)
	if err != nil {
		log.Printf("Error making S3 request: %v", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	log.Printf("S3 response status: %d (%s)", resp.StatusCode, http.StatusText(resp.StatusCode))

	// If 5xx error, read and log the response body
	var bodyBytes []byte
	if resp.StatusCode >= 500 && resp.StatusCode < 600 {
		bodyBytes, err = io.ReadAll(resp.Body)
		if err != nil {
			log.Printf("Error reading 5xx response body: %v", err)
		} else {
			log.Printf("5xx Error Response Body: %s", string(bodyBytes))
		}
		resp.Body.Close()
	}

	for header, values := range resp.Header {
		headerLower := strings.ToLower(header)
		if headerLower != "connection" && headerLower != "transfer-encoding" {
			for _, value := range values {
				w.Header().Add(header, value)
			}
		}
	}

	w.WriteHeader(resp.StatusCode)

	// Write the response body
	if len(bodyBytes) > 0 {
		// We already read the body for 5xx errors
		written, err := w.Write(bodyBytes)
		if err != nil {
			log.Printf("Error writing response: %v", err)
		} else {
			log.Printf("Response sent: %d bytes", written)
		}
	} else {
		// Normal case - stream the body
		written, err := io.Copy(w, resp.Body)
		if err != nil {
			log.Printf("Error copying response: %v", err)
		} else {
			log.Printf("Response sent: %d bytes", written)
		}
	}
}

func (p *FileProxy) reconstructS3URL(path string, rawQuery string) string {
	// For GCS, the storage prefix should just be the domain (https://storage.googleapis.com)
	// and the path already includes the bucket name
	// For S3, the storage prefix includes the bucket in the domain (https://bucket.s3.region.amazonaws.com)

	s3URL := p.storagePrefix + path
	if rawQuery != "" {
		s3URL += "?" + rawQuery
	}

	return s3URL
}

// handleAWSSDKRequest handles AWS SDK requests using Go AWS SDK v2
func (p *FileProxy) handleAWSSDKRequest(w http.ResponseWriter, r *http.Request) {
	ctx := context.Background()

	// Extract object key from path (remove leading slash and bucket name)
	path := strings.TrimPrefix(r.URL.Path, "/")

	// For virtual-hosted style, the bucket is in the hostname, object key is the full path
	// For path-style, need to extract bucket from path
	objectKey := path
	bucketName := p.bucketName

	// If the path starts with bucket name, extract the actual object key
	if strings.HasPrefix(path, bucketName+"/") {
		objectKey = strings.TrimPrefix(path, bucketName+"/")
	}

	log.Printf("Handling AWS SDK request: %s %s (bucket: %s, key: %s)", r.Method, r.URL.Path, bucketName, objectKey)

	// Add custom headers from the original request
	metadata := make(map[string]string)
	for header, values := range r.Header {
		if strings.HasPrefix(header, "X-My-Header-") {
			// Convert to metadata key (remove prefix and lowercase)
			metaKey := strings.ToLower(strings.TrimPrefix(header, "X-My-Header-"))
			if len(values) > 0 {
				metadata[metaKey] = values[0]
			}
		}
	}

	switch r.Method {
	case "HEAD":
		p.handleHeadObject(ctx, w, bucketName, objectKey)
	case "GET":
		p.handleGetObject(ctx, w, r, bucketName, objectKey)
	case "PUT":
		p.handlePutObject(ctx, w, r, bucketName, objectKey, metadata)
	default:
		log.Printf("Unsupported method for AWS SDK request: %s", r.Method)
		http.Error(w, "Method not supported", http.StatusMethodNotAllowed)
	}
}

// handleHeadObject handles HEAD requests (metadata queries)
func (p *FileProxy) handleHeadObject(ctx context.Context, w http.ResponseWriter, bucket, key string) {
	input := &s3.HeadObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	}

	result, err := p.s3Client.HeadObject(ctx, input)
	if err != nil {
		log.Printf("HeadObject error: %v", err)
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}

	// Set response headers from S3 metadata
	if result.ETag != nil {
		w.Header().Set("ETag", *result.ETag)
	}
	if result.ContentLength != nil {
		w.Header().Set("Content-Length", fmt.Sprintf("%d", *result.ContentLength))
	}
	if result.ContentType != nil {
		w.Header().Set("Content-Type", *result.ContentType)
	}
	if result.LastModified != nil {
		w.Header().Set("Last-Modified", result.LastModified.Format(http.TimeFormat))
	}

	// Add any custom metadata headers
	for key, value := range result.Metadata {
		w.Header().Set("X-Amz-Meta-"+key, value)
	}

	w.WriteHeader(http.StatusOK)
	log.Printf("HeadObject succeeded for %s/%s", bucket, key)
}

// handleGetObject handles GET requests (downloads)
func (p *FileProxy) handleGetObject(ctx context.Context, w http.ResponseWriter, r *http.Request, bucket, key string) {
	input := &s3.GetObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
	}

	result, err := p.s3Client.GetObject(ctx, input)
	if err != nil {
		log.Printf("GetObject error: %v", err)
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	defer result.Body.Close()

	// Set response headers
	if result.ETag != nil {
		w.Header().Set("ETag", *result.ETag)
	}
	if result.ContentLength != nil {
		w.Header().Set("Content-Length", fmt.Sprintf("%d", *result.ContentLength))
	}
	if result.ContentType != nil {
		w.Header().Set("Content-Type", *result.ContentType)
	}
	if result.LastModified != nil {
		w.Header().Set("Last-Modified", result.LastModified.Format(http.TimeFormat))
	}

	// Copy object content to response
	written, err := io.Copy(w, result.Body)
	if err != nil {
		log.Printf("Error copying GetObject response: %v", err)
		return
	}

	log.Printf("GetObject succeeded for %s/%s (%d bytes)", bucket, key, written)
}

// handlePutObject handles PUT requests (uploads)
func (p *FileProxy) handlePutObject(ctx context.Context, w http.ResponseWriter, r *http.Request, bucket, key string, metadata map[string]string) {
	// Read the request body
	body, err := io.ReadAll(r.Body)
	if err != nil {
		log.Printf("Error reading PUT body: %v", err)
		http.Error(w, "Error reading request body", http.StatusBadRequest)
		return
	}

	input := &s3.PutObjectInput{
		Bucket: aws.String(bucket),
		Key:    aws.String(key),
		Body:   bytes.NewReader(body),
	}

	// Add content type if specified
	if contentType := r.Header.Get("Content-Type"); contentType != "" {
		input.ContentType = aws.String(contentType)
	}

	// Add custom metadata
	if len(metadata) > 0 {
		input.Metadata = metadata
	}

	// Add server-side encryption if specified
	if sse := r.Header.Get("X-Amz-Server-Side-Encryption"); sse != "" {
		input.ServerSideEncryption = types.ServerSideEncryption(sse)
	}
	if kmsKeyId := r.Header.Get("X-Amz-Server-Side-Encryption-Aws-Kms-Key-Id"); kmsKeyId != "" {
		input.SSEKMSKeyId = aws.String(kmsKeyId)
	}

	result, err := p.s3Client.PutObject(ctx, input)
	if err != nil {
		log.Printf("PutObject error: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Set response headers
	if result.ETag != nil {
		w.Header().Set("ETag", *result.ETag)
	}

	w.WriteHeader(http.StatusOK)
	log.Printf("PutObject succeeded for %s/%s", bucket, key)
}

func main() {
	proxy := NewFileProxy()
	addr := fmt.Sprintf("localhost:%d", FileProxyPort)

	log.Printf("Starting S3 file proxy server on http://%s", addr)
	log.Printf("Will print all HTTP headers received")
	log.Printf("Proxying to: %s", proxy.storagePrefix)

	if err := http.ListenAndServe(addr, proxy); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
