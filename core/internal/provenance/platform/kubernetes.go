package platform

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"
)

func (c Config) read(request *http.Request) ([]byte, Capability) {
	client := *c.Client
	client.Timeout = 500 * time.Millisecond
	client.CheckRedirect = func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }
	response, err := client.Do(request)
	if err != nil {
		if request.Context().Err() != nil {
			return nil, Capability{Status: "timeout", Reason: "request_timeout"}
		}
		return nil, Capability{Status: "unavailable", Reason: "request_failed"}
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusForbidden {
		return nil, Capability{Status: "permission_denied", Reason: "permission_denied"}
	}
	if response.StatusCode != http.StatusOK {
		return nil, Capability{Status: "unavailable", Reason: "not_available"}
	}
	data, err := io.ReadAll(io.LimitReader(response.Body, 64<<10+1))
	if err != nil || len(data) > 64<<10 {
		return nil, Capability{Status: "partial", Reason: "invalid_response"}
	}
	return data, Capability{Status: "available"}
}

func (c Config) nodeLabels(ctx context.Context) (map[string]string, Capability) {
	if c.Labels != nil {
		return c.Labels, Capability{Status: "available"}
	}
	pod, namespace := c.Env["K8S_POD_NAME"], c.Env["K8S_NAMESPACE"]
	if pod == "" || namespace == "" {
		return nil, Capability{Status: "unavailable", Reason: "pod_identity_missing"}
	}
	token, err := os.ReadFile(filepath.Join(c.ServiceAccountDir, "token"))
	if err != nil || len(token) > 16<<10 {
		return nil, Capability{Status: "unavailable", Reason: "credentials_missing"}
	}
	endpoint := c.KubernetesURL
	if endpoint == "" {
		host := c.Env["KUBERNETES_SERVICE_HOST"]
		if host == "" {
			return nil, Capability{Status: "unavailable", Reason: "endpoint_missing"}
		}
		port := c.Env["KUBERNETES_SERVICE_PORT_HTTPS"]
		if port == "" {
			port = "443"
		}
		endpoint = "https://" + net.JoinHostPort(host, port)
		ca, err := os.ReadFile(filepath.Join(c.ServiceAccountDir, "ca.crt"))
		roots := x509.NewCertPool()
		if err != nil || !roots.AppendCertsFromPEM(ca) {
			return nil, Capability{Status: "unavailable", Reason: "credentials_missing"}
		}
		c.Client = &http.Client{
			Transport: &http.Transport{
				TLSClientConfig: &tls.Config{RootCAs: roots, MinVersion: tls.VersionTLS12},
			},
		}
	}
	requestCtx, cancel := context.WithTimeout(ctx, time.Second)
	defer cancel()
	request, err := http.NewRequestWithContext(
		requestCtx,
		http.MethodGet,
		strings.TrimRight(
			endpoint,
			"/",
		)+"/api/v1/namespaces/"+url.PathEscape(
			namespace,
		)+"/pods/"+url.PathEscape(
			pod,
		),
		http.NoBody,
	)
	if err != nil {
		return nil, Capability{Status: "unavailable", Reason: "invalid_endpoint"}
	}
	request.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(token)))
	data, capability := c.read(request)
	if capability.Status != "available" {
		return nil, capability
	}
	var podObject struct {
		Spec struct {
			NodeName string `json:"nodeName"`
		} `json:"spec"`
	}
	if json.Unmarshal(data, &podObject) != nil || podObject.Spec.NodeName == "" {
		return nil, Capability{Status: "partial", Reason: "node_missing"}
	}
	request, err = http.NewRequestWithContext(
		requestCtx,
		http.MethodGet,
		strings.TrimRight(endpoint, "/")+"/api/v1/nodes/"+url.PathEscape(podObject.Spec.NodeName),
		http.NoBody,
	)
	if err != nil {
		return nil, Capability{Status: "unavailable", Reason: "invalid_endpoint"}
	}
	request.Header.Set("Authorization", "Bearer "+strings.TrimSpace(string(token)))
	data, capability = c.read(request)
	if capability.Status != "available" {
		return nil, capability
	}
	var node struct {
		Metadata struct {
			Labels map[string]string `json:"labels"`
		} `json:"metadata"`
	}
	if json.Unmarshal(data, &node) != nil {
		return nil, Capability{Status: "partial", Reason: "invalid_response"}
	}
	return node.Metadata.Labels, capability
}
