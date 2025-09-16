package main

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
)

const FileProxyPort = 8182

type FileProxy struct {
	client *http.Client
	missingHeaderLogger *log.Logger
}

func NewFileProxy() *FileProxy {
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
	}
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
	log.Printf("Headers received:")
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
	baseURL := "https://pinglei-byob-us-west-2.s3.us-west-2.amazonaws.com"

	s3URL := baseURL + path
	if rawQuery != "" {
		s3URL += "?" + rawQuery
	}

	return s3URL
}

func main() {
	proxy := NewFileProxy()
	addr := fmt.Sprintf("localhost:%d", FileProxyPort)

	log.Printf("Starting S3 file proxy server on http://%s", addr)
	log.Printf("Will print all HTTP headers received")
	log.Printf("Proxying to S3 with original presigned URLs")

	if err := http.ListenAndServe(addr, proxy); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
