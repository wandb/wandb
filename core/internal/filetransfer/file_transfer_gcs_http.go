//go:build cloud_http

package filetransfer

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"cloud.google.com/go/auth/credentials"
	"cloud.google.com/go/auth/httptransport"
	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/observability"
)

// GCSClient is the authenticated HTTP transport used for GCS reference reads.
// Authentication remains with Google's credential library, including ADC,
// workload identity federation, impersonation and automatic token refresh.
type GCSClient interface {
	Do(*http.Request) (*http.Response, error)
}

// GCSFileTransfer downloads reference artifacts using the GCS JSON API.
type GCSFileTransfer struct {
	client            GCSClient
	setupErr          error
	authScopes        []string
	endpoint          string
	logger            *observability.CoreLogger
	fileTransferStats FileTransferStats
	ctx               context.Context
	GCSOnce           *sync.Once
}

const (
	maxGSWorkers = 32
	gcsScheme    = "gs"
	gcsEndpoint  = "https://storage.googleapis.com/storage/v1"
)

var ErrObjectIsDirectory = errors.New("object is a directory and cannot be downloaded")
var errGCSObjectNotExist = errors.New("GCS object does not exist")

type gcsObjectAttrs struct {
	Name            string `json:"name"`
	Etag            string `json:"etag"`
	Generation      string `json:"generation"`
	Size            int64  `json:"size,string"`
	CRC32C          string `json:"crc32c"`
	ContentEncoding string `json:"contentEncoding"`
}

func NewGCSFileTransfer(
	client GCSClient,
	logger *observability.CoreLogger,
	stats FileTransferStats,
) *GCSFileTransfer {
	ft := &GCSFileTransfer{
		endpoint: gcsEndpoint,
		authScopes: []string{
			"https://www.googleapis.com/auth/devstorage.full_control",
			"https://www.googleapis.com/auth/cloud-platform",
		},
		logger:            logger,
		fileTransferStats: stats,
		ctx:               context.Background(),
		GCSOnce:           &sync.Once{},
	}
	if client != nil {
		ft.client = &cloudHTTPClient{client: client, maxAttempts: 5}
	}
	return ft
}

// SetupClient creates the auth transport once. The emulator, like the previous
// storage client, skips authentication and accepts a host with or without scheme.
func (ft *GCSFileTransfer) SetupClient() {
	ft.GCSOnce.Do(func() {
		if ft.client != nil {
			return
		}
		if host := os.Getenv("STORAGE_EMULATOR_HOST"); host != "" {
			if !strings.Contains(host, "://") {
				host = "http://" + host
			}
			u, err := url.Parse(host)
			if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
				ft.logger.Error("Unable to set up GCS emulator", "host", host)
				return
			}
			u.Path, u.RawPath, u.RawQuery, u.Fragment = "/storage/v1", "", "", ""
			ft.endpoint = u.String()
			ft.client = &cloudHTTPClient{client: &http.Client{}, maxAttempts: 5}
			return
		}
		// Endpoint discovery remains deliberately limited in this opt-in
		// transport. Never send an alternate-universe credential to the
		// default public service endpoint.
		if universe := os.Getenv(
			"GOOGLE_CLOUD_UNIVERSE_DOMAIN",
		); universe != "" &&
			universe != "googleapis.com" {
			ft.setupErr = fmt.Errorf("cloud_http GCS does not support universe domain %q", universe)
			return
		}
		if mode := os.Getenv("GOOGLE_API_USE_MTLS_ENDPOINT"); mode == "always" {
			ft.setupErr = errors.New(
				"cloud_http GCS does not support mandatory mTLS endpoint selection",
			)
			return
		}
		opts := &httptransport.Options{
			Endpoint:         gcsEndpoint,
			UniverseDomain:   "googleapis.com",
			DisableTelemetry: true,
			// Keep the map non-nil so the auth transport can add ADC's
			// quota-project header to the same map its middleware uses.
			Headers:    http.Header{},
			DetectOpts: &credentials.DetectOptions{Scopes: ft.authScopes},
		}
		client, err := httptransport.NewClient(opts)
		if err != nil {
			ft.setupErr = err
			ft.logger.Error("Unable to set up GCS client", "err", err)
			return
		}
		if opts.ClientCertProvider != nil && os.Getenv("GOOGLE_API_USE_MTLS_ENDPOINT") != "never" {
			ft.setupErr = errors.New(
				"cloud_http GCS does not support automatic mTLS endpoint selection",
			)
			return
		}
		ft.client = &cloudHTTPClient{client: client, maxAttempts: 5}
	})
}

func (ft *GCSFileTransfer) Upload(task *DefaultUploadTask) error {
	return fmt.Errorf("not implemented yet")
}

func (ft *GCSFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	bucket, root, err := parseCloudReference(task.Reference, gcsScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	if bucket == "" {
		return ft.formatDownloadError("error parsing reference", errors.New("missing bucket"))
	}
	ft.SetupClient()
	if ft.client == nil {
		if ft.setupErr != nil {
			return ft.formatDownloadError("unable to set up client", ft.setupErr)
		}
		return fmt.Errorf("GCSFileTransfer: Download: Unable to set up GCS Client")
	}
	ctx, cancel := context.WithCancel(ft.ctx)
	defer cancel()
	g, ctx := errgroup.WithContext(ctx)
	g.SetLimit(maxGSWorkers)
	queue := func(name string) {
		g.Go(func() error {
			return ft.downloadObject(ctx, bucket, root, name, task)
		})
	}
	if task.HasSingleFile() {
		queue(root)
	} else {
		// Queue one page at a time; concurrency is bounded without retaining an
		// entire bucket listing in memory.
		pageToken := ""
		for {
			var page struct {
				Items         []gcsObjectAttrs `json:"items"`
				NextPageToken string           `json:"nextPageToken"`
			}
			q := url.Values{
				"prefix":     {root},
				"maxResults": {"1000"},
				"fields":     {"items(name),nextPageToken"},
			}
			if pageToken != "" {
				q.Set("pageToken", pageToken)
			}
			if err := ft.getJSON(ctx, ft.objectURL(bucket, "", q), &page); err != nil {
				cancel()
				if transferErr := g.Wait(); transferErr != nil {
					return transferErr
				}
				return ft.formatDownloadError("error listing objects", err)
			}
			for _, item := range page.Items {
				if ctx.Err() != nil {
					break
				}
				queue(item.Name)
			}
			if page.NextPageToken == "" || ctx.Err() != nil {
				break
			}
			if page.NextPageToken == pageToken {
				cancel()
				_ = g.Wait()
				return errors.New("GCS listing repeated its page token")
			}
			pageToken = page.NextPageToken
		}
	}
	return g.Wait()
}

// downloadObject validates metadata and selects the local destination for one
// item in either a single-object download or a prefix listing.
func (ft *GCSFileTransfer) downloadObject(
	ctx context.Context,
	bucket, root, name string,
	task *ReferenceArtifactDownloadTask,
) error {
	attrs, err := ft.getObjectAndAttrs(ctx, bucket, task, name)
	if errors.Is(err, ErrObjectIsDirectory) {
		return nil
	}
	if err != nil {
		return ft.formatDownloadError("error getting object "+name, err)
	}
	if task.ShouldCheckDigest() && attrs.Etag != task.Digest {
		return ft.formatDownloadError(
			"",
			fmt.Errorf(
				"digest/etag mismatch: etag %s does not match expected digest %s",
				attrs.Etag,
				task.Digest,
			),
		)
	}
	localPath := task.PathOrPrefix
	if !task.HasSingleFile() {
		rel, ok := strings.CutPrefix(name, root)
		if !ok {
			return fmt.Errorf("GCS object %q is outside prefix %q", name, root)
		}
		rel = strings.TrimPrefix(rel, "/")
		if rel != "" && !filepath.IsLocal(filepath.FromSlash(rel)) {
			return fmt.Errorf("invalid GCS relative object path %q", rel)
		}
		localPath = filepath.Join(localPath, filepath.FromSlash(rel))
	}
	return ft.downloadFile(ctx, bucket, name, attrs, localPath)
}

// objectURL encodes the entire object name as one API path parameter, including
// slashes, percent signs, question marks and Unicode.
func (ft *GCSFileTransfer) objectURL(bucket, object string, q url.Values) string {
	u := strings.TrimRight(ft.endpoint, "/") + "/b/" + url.PathEscape(bucket) + "/o"
	if object != "" {
		u += "/" + url.PathEscape(object)
	}
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	return u
}

func (ft *GCSFileTransfer) getJSON(ctx context.Context, endpoint string, result any) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, http.NoBody)
	if err != nil {
		return err
	}
	resp, err := ft.client.Do(req)
	if err != nil {
		return err
	}
	if resp.StatusCode == http.StatusNotFound {
		_ = resp.Body.Close()
		return errGCSObjectNotExist
	}
	if resp.StatusCode != http.StatusOK {
		return cloudResponseError(resp)
	}
	defer resp.Body.Close()
	return json.NewDecoder(io.LimitReader(resp.Body, 16<<20)).Decode(result)
}

func (ft *GCSFileTransfer) getObjectAndAttrs(
	ctx context.Context,
	bucket string,
	task *ReferenceArtifactDownloadTask,
	key string,
) (*gcsObjectAttrs, error) {
	if strings.HasSuffix(key, "/") {
		return nil, ErrObjectIsDirectory
	}
	q := url.Values{}
	if version, ok := task.VersionIDNumber(); ok {
		q.Set("generation", strconv.FormatInt(version, 10))
	}
	if version, ok := task.VersionIDString(); ok {
		if _, err := strconv.ParseInt(version, 10, 64); err != nil {
			return nil, fmt.Errorf("invalid GCS generation %q", version)
		}
		q.Set("generation", version)
	}
	var attrs gcsObjectAttrs
	err := ft.getJSON(ctx, ft.objectURL(bucket, key, q), &attrs)
	if errors.Is(err, errGCSObjectNotExist) && path.Ext(key) == "" && task.Size == 0 {
		if err := ft.getJSON(ctx, ft.objectURL(bucket, key+"/", q), &attrs); err != nil {
			return nil, err
		}
		return nil, ErrObjectIsDirectory
	}
	if err != nil {
		return nil, err
	}
	if attrs.Generation == "" {
		attrs.Generation = q.Get("generation")
	}
	if attrs.Generation == "" {
		return nil, errors.New("GCS metadata response is missing generation")
	}
	if generation, err := strconv.ParseInt(attrs.Generation, 10, 64); err != nil || generation < 0 {
		return nil, fmt.Errorf("invalid GCS generation %q", attrs.Generation)
	}
	if expected := q.Get("generation"); expected != "" && expected != attrs.Generation {
		return nil, fmt.Errorf(
			"GCS metadata generation changed: got %s, want %s",
			attrs.Generation,
			expected,
		)
	}
	if attrs.Size < 0 {
		return nil, errors.New("negative GCS object size")
	}
	return &attrs, nil
}

func (ft *GCSFileTransfer) downloadFile(
	ctx context.Context,
	bucket, name string,
	attrs *gcsObjectAttrs,
	localPath string,
) error {
	r, err := ft.openGCSReader(ctx, bucket, name, attrs)
	if err != nil {
		return ft.formatDownloadError("error creating reader", err)
	}
	defer r.Close()
	if err := os.MkdirAll(filepath.Dir(localPath), os.ModePerm); err != nil {
		return err
	}
	file, err := createGCSTemporaryFile(localPath)
	if err != nil {
		return err
	}
	defer func() { _ = file.Close(); _ = os.Remove(file.Name()) }()
	if _, err := io.Copy(file, r); err != nil {
		return ft.formatDownloadError("error copying file "+localPath, err)
	}
	if err := file.Close(); err != nil {
		return err
	}
	return os.Rename(file.Name(), localPath)
}

// createGCSTemporaryFile preserves the permissions os.Create used for downloads:
// an existing destination keeps its permission bits, while a new file is created
// with 0o666 filtered through the process umask. O_EXCL reserves the random path
// atomically without unlinking a reservation or changing the process-wide umask.
func createGCSTemporaryFile(destination string) (*os.File, error) {
	var mode os.FileMode
	existing := false
	if info, err := os.Stat(destination); err == nil {
		mode, existing = info.Mode().Perm(), true
	} else if !os.IsNotExist(err) {
		return nil, err
	}
	for range 10 {
		name := filepath.Join(filepath.Dir(destination), ".wandb-gcs-"+rand.Text())
		file, err := os.OpenFile(name, os.O_RDWR|os.O_CREATE|os.O_EXCL, 0o666)
		if os.IsExist(err) {
			continue
		}
		if err != nil {
			return nil, err
		}
		if existing {
			if err := file.Chmod(mode); err != nil {
				_ = file.Close()
				_ = os.Remove(name)
				return nil, err
			}
		}
		return file, nil
	}
	return nil, fmt.Errorf("could not create a unique GCS download temporary file")
}

func (ft *GCSFileTransfer) formatDownloadError(ctx string, err error) error {
	return fmt.Errorf("GCSFileTransfer: Download: %s: %w", ctx, err)
}
