package main

import (
	"compress/gzip"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
)

const (
	APIProxyPort  = 8181
	FileProxyPort = 8182
	WandBAPIBase  = "https://api.wandb.ai"
	FileProxyBase = "http://localhost:8182"
)

var (
	s3URLPattern = regexp.MustCompile(`https?://[^/]*\.s3\.[^/]*\.amazonaws\.com[^"\s']*`)
	gcsURLPattern = regexp.MustCompile(`https?://storage\.googleapis\.com/[^"\s']*`)
	apiFilesURLPattern = regexp.MustCompile(`https://api\.wandb\.ai/files/[^"\s']*`)
	allURLPattern = regexp.MustCompile(`https?://[^\s"']+`)
)

type APIProxy struct {
	client *http.Client
	urlLogger *log.Logger
}

func NewAPIProxy() *APIProxy {
	// Create logs directory if it doesn't exist
	os.MkdirAll("logs", 0755)

	// Create logger for URLs
	file, err := os.OpenFile("logs/api_proxy_url.log", os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
	if err != nil {
		log.Fatalf("Failed to open URL log file: %v", err)
	}
	urlLogger := log.New(file, "", log.LstdFlags)

	return &APIProxy{
		client: &http.Client{
			CheckRedirect: func(req *http.Request, via []*http.Request) error {
				return http.ErrUseLastResponse
			},
		},
		urlLogger: urlLogger,
	}
}

func (p *APIProxy) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	targetURL := WandBAPIBase + r.URL.Path
	if r.URL.RawQuery != "" {
		targetURL += "?" + r.URL.RawQuery
	}

	// Get User-Agent for URL logging
	userAgent := r.Header.Get("User-Agent")

	// Read the request body for logging and reuse
	var bodyBytes []byte
	if r.Body != nil {
		bodyBytes, _ = io.ReadAll(r.Body)
		r.Body.Close()
	}

	// Log request details including body for GraphQL
	log.Printf("%s %s", r.Method, targetURL)
	if len(bodyBytes) > 0 && strings.Contains(r.Header.Get("Content-Type"), "application/json") {
		log.Printf("Request body: %s", string(bodyBytes))
		
		// Extract and log URLs from request
		p.logExtractedURLs(userAgent, "REQUEST", string(bodyBytes))
	}

	// Create new request with the body
	proxyReq, err := http.NewRequest(r.Method, targetURL, io.NopCloser(strings.NewReader(string(bodyBytes))))
	if err != nil {
		log.Printf("Error creating request: %v", err)
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}

	// Copy headers
	for header, values := range r.Header {
		if header != "Host" {
			for _, value := range values {
				proxyReq.Header.Add(header, value)
			}
		}
	}

	resp, err := p.client.Do(proxyReq)
	if err != nil {
		log.Printf("Error making request: %v", err)
		http.Error(w, err.Error(), http.StatusBadGateway)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 300 && resp.StatusCode < 400 {
		location := resp.Header.Get("Location")
		if location != "" {
			modifiedLocation := p.replaceURLs(location)
			if modifiedLocation != location {
				log.Printf("Modifying redirect: %s... -> %s...",
					truncate(location, 100), truncate(modifiedLocation, 100))
				resp.Header.Set("Location", modifiedLocation)
			}
		}
	}

	// Check if response is gzipped
	contentEncoding := resp.Header.Get("Content-Encoding")
	
	// Read response body
	var body []byte
	
	if strings.Contains(contentEncoding, "gzip") {
		// Decompress gzipped response
		reader, err := gzip.NewReader(resp.Body)
		if err != nil {
			log.Printf("Error creating gzip reader: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		defer reader.Close()
		body, err = io.ReadAll(reader)
		if err != nil {
			log.Printf("Error reading gzipped response: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
	} else {
		body, err = io.ReadAll(resp.Body)
		if err != nil {
			log.Printf("Error reading response body: %v", err)
			return
		}
	}

	// Copy headers except for encoding-related ones (we're decompressing)
	for header, values := range resp.Header {
		headerLower := strings.ToLower(header)
		if headerLower != "connection" && headerLower != "transfer-encoding" && headerLower != "content-encoding" && headerLower != "content-length" {
			for _, value := range values {
				w.Header().Add(header, value)
			}
		}
	}

	contentType := resp.Header.Get("Content-Type")
	
	// Log response for debugging
	log.Printf("Response status: %d, Content-Type: %s, Encoding: %s", resp.StatusCode, contentType, contentEncoding)
	if len(body) < 1000 {
		log.Printf("Response body: %s", string(body))
	} else {
		log.Printf("Response body (first 500 chars): %s...", string(body[:500]))
	}

	// Process the response based on content type
	if strings.Contains(contentType, "application/json") || strings.Contains(contentType, "text/") {
		// Extract and log URLs from response before modification
		p.logExtractedURLs(userAgent, "RESPONSE", string(body))
		
		modifiedBody := p.replaceURLs(string(body))
		if modifiedBody != string(body) {
			log.Printf("Modified URLs in response body")
		}
		w.Header().Set("Content-Length", fmt.Sprintf("%d", len(modifiedBody)))
		w.WriteHeader(resp.StatusCode)
		_, err = w.Write([]byte(modifiedBody))
		if err != nil {
			log.Printf("Error writing response: %v", err)
		}
	} else {
		w.Header().Set("Content-Length", fmt.Sprintf("%d", len(body)))
		w.WriteHeader(resp.StatusCode)
		_, err = w.Write(body)
		if err != nil {
			log.Printf("Error writing response: %v", err)
		}
	}
}

func (p *APIProxy) logExtractedURLs(userAgent, direction, content string) {
	urls := allURLPattern.FindAllString(content, -1)
	if len(urls) == 0 {
		return
	}
	
	p.urlLogger.Println("========================================")
	p.urlLogger.Printf("Direction: %s", direction)
	p.urlLogger.Printf("User-Agent: %s", userAgent)
	p.urlLogger.Printf("Timestamp: %s", log.Prefix())
	
	// Log GraphQL query if it's a request
	if direction == "REQUEST" && strings.Contains(content, "query") {
		// Extract first 500 chars of the query for context
		queryPreview := content
		if len(queryPreview) > 500 {
			queryPreview = queryPreview[:500] + "..."
		}
		p.urlLogger.Printf("Query Preview: %s", queryPreview)
	}
	
	p.urlLogger.Println("Extracted URLs:")
	for _, url := range urls {
		p.urlLogger.Printf("  - %s", url)
	}
	p.urlLogger.Println("========================================")
}

func (p *APIProxy) replaceURLs(content string) string {
	// First replace S3 URLs
	content = s3URLPattern.ReplaceAllStringFunc(content, func(match string) string {
		parsedURL, err := url.Parse(match)
		if err != nil {
			log.Printf("Error parsing S3 URL %s: %v", truncate(match, 80), err)
			return match
		}

		newURL := FileProxyBase + parsedURL.Path
		if parsedURL.RawQuery != "" {
			newURL += "?" + parsedURL.RawQuery
		}

		log.Printf("Replacing S3 URL: %s... -> %s...",
			truncate(match, 80), truncate(newURL, 80))
		return newURL
	})

	// Replace GCS URLs
	content = gcsURLPattern.ReplaceAllStringFunc(content, func(match string) string {
		parsedURL, err := url.Parse(match)
		if err != nil {
			log.Printf("Error parsing GCS URL %s: %v", truncate(match, 80), err)
			return match
		}

		newURL := FileProxyBase + parsedURL.Path
		if parsedURL.RawQuery != "" {
			newURL += "?" + parsedURL.RawQuery
		}

		log.Printf("Replacing GCS URL: %s... -> %s...",
			truncate(match, 80), truncate(newURL, 80))
		return newURL
	})

	// Then replace api.wandb.ai/files URLs
	content = apiFilesURLPattern.ReplaceAllStringFunc(content, func(match string) string {
		parsedURL, err := url.Parse(match)
		if err != nil {
			log.Printf("Error parsing API files URL %s: %v", truncate(match, 80), err)
			return match
		}

		// Replace https://api.wandb.ai/files with http://localhost:8181/files
		newURL := "http://localhost:" + fmt.Sprintf("%d", APIProxyPort) + parsedURL.Path
		if parsedURL.RawQuery != "" {
			newURL += "?" + parsedURL.RawQuery
		}

		log.Printf("Replacing API files URL: %s... -> %s...",
			truncate(match, 80), truncate(newURL, 80))
		return newURL
	})

	return content
}

func truncate(s string, length int) string {
	if len(s) <= length {
		return s
	}
	return s[:length]
}

func main() {
	proxy := NewAPIProxy()
	addr := fmt.Sprintf("localhost:%d", APIProxyPort)

	log.Printf("Starting WandB API proxy server on http://%s", addr)
	log.Printf("Proxying to %s", WandBAPIBase)
	log.Printf("Replacing S3 URLs with %s", FileProxyBase)

	if err := http.ListenAndServe(addr, proxy); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
