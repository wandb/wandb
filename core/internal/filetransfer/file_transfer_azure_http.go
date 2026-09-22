//go:build cloud_http

package filetransfer

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"sync"

	"github.com/Azure/azure-sdk-for-go/sdk/azidentity"
	"golang.org/x/sync/errgroup"

	"github.com/wandb/wandb/core/internal/observability"
)

const (
	maxAzureWorkers = 500
	// Azure blob storage urls have the following format:
	// https://<storage-account-name>.blob.core.windows.net/<container-name>/<blob-name>
	azureScheme = "https"
)

// AzureBlobProperties is the subset of blob metadata needed for artifact downloads.
type AzureBlobProperties struct {
	ETag          string
	ContentLength int64
}

type AzureBlobItem struct {
	Name      string `xml:"Name"`
	VersionID string `xml:"VersionId"`
}

type AzureBlobPage struct {
	Items      []AzureBlobItem `xml:"Blobs>Blob"`
	NextMarker string          `xml:"NextMarker"`
}

type AzureBlobClient interface {
	DownloadFile(context.Context, *os.File) (int64, error)
	GetProperties(context.Context) (AzureBlobProperties, error)
	WithVersionID(string) (AzureBlobClient, error)
}

type AzureAccountClient interface {
	DownloadFile(context.Context, string, string, *os.File) (int64, error)
	ListBlobs(context.Context, string, string, string, bool) (AzureBlobPage, error)
	NewBlobClient(string, string) AzureBlobClient
}

type AzureBlockBlobClient interface {
	UploadStream(context.Context, io.Reader, http.Header) (*http.Response, error)
}

// AzureClientsMap is a map of account URLs/container names to client objects.
// Azure clients exist at both the container and account level and support different
// blob operations, so we store clients only when necessary and reuse them.
type AzureClientsMap[T any] struct {
	// clients is a map of account URLs/container names to client objects
	clients sync.Map

	// once is a map of account URLs/container names to sync.Once objects to
	// ensure that we only set up each client once
	once sync.Map
}

type azureClientInit struct {
	once sync.Once
	err  error
}

func NewAzureClientsMap[T any]() *AzureClientsMap[T] {
	return &AzureClientsMap[T]{clients: sync.Map{}, once: sync.Map{}}
}

func (am *AzureClientsMap[T]) GetClient(key string) (T, error) {
	var zero T
	client, ok := am.clients.Load(key)
	if !ok {
		return zero, fmt.Errorf("client not found")
	}
	accountClient, ok := client.(T)
	if !ok {
		return zero, fmt.Errorf("client is not an account client")
	}
	return accountClient, nil
}

func setupAccountClient(
	accountUrl string,
	cred *azidentity.DefaultAzureCredential,
) (AzureAccountClient, error) {
	return newAzureAccountHTTPClient(accountUrl, cred, nil)
}

func (am *AzureClientsMap[T]) LoadOrStore(
	key string,
	setup func(key string, cred *azidentity.DefaultAzureCredential) (T, error),
) (T, error) {
	onceVal, _ := am.once.LoadOrStore(key, &azureClientInit{})
	init := onceVal.(*azureClientInit)
	init.once.Do(func() {
		var err error
		defer func() { init.err = err }()
		var cred *azidentity.DefaultAzureCredential
		cred, err = azidentity.NewDefaultAzureCredential(nil)
		if err != nil {
			return
		}
		var client T
		client, err = setup(key, cred)
		if err != nil {
			return
		}
		am.clients.Store(key, client)
	})
	if init.err != nil {
		var zero T
		return zero, init.err
	}
	return am.GetClient(key)
}

// AzureFileTransfer uploads or downloads files to/from Azure.
type AzureFileTransfer struct {
	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context

	// clients caches an authenticated HTTP client for each account URL
	clients *AzureClientsMap[AzureAccountClient]

	// blobClient is a client for a specific blob
	blobClient AzureBlobClient

	// blockBlobClient is a client for a specific blob
	blockBlobClient AzureBlockBlobClient
}

type AzureClientOverrides struct {
	AccountClients  *AzureClientsMap[AzureAccountClient]
	BlobClient      AzureBlobClient
	BlockBlobClient AzureBlockBlobClient
}

// NewAzureFileTransfer creates a new fileTransfer.
func NewAzureFileTransfer(
	clientOverrides *AzureClientOverrides,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *AzureFileTransfer {
	ctx := context.Background()
	fileTransfer := &AzureFileTransfer{
		logger:            logger,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
		clients:           NewAzureClientsMap[AzureAccountClient](),
		blobClient:        nil,
		blockBlobClient:   nil,
	}
	if clientOverrides != nil {
		if clientOverrides.AccountClients != nil {
			fileTransfer.clients = clientOverrides.AccountClients
		}
		fileTransfer.blobClient = clientOverrides.BlobClient
		fileTransfer.blockBlobClient = clientOverrides.BlockBlobClient
	}
	return fileTransfer
}

// setupBlobClient sets up a client for a specific blob.
func setupBlobClient(
	task *ReferenceArtifactDownloadTask,
) (AzureBlobClient, error) {
	cred, err := azidentity.NewDefaultAzureCredential(nil)
	if err != nil {
		return nil, err
	}
	client, err := newAzureBlobHTTPClient(task.Reference, cred, nil)
	if err != nil {
		return nil, err
	}
	versionId, ok := task.VersionIDString()
	if ok {
		return client.WithVersionID(versionId)
	}
	return client, nil
}

// Upload implements ArtifactFileTransfer.Upload
func (ft *AzureFileTransfer) Upload(task *DefaultUploadTask) error {
	ft.logger.Debug("Azure file transfer: uploading file", "path", task.Path, "url", task.Url)

	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError(
				"filetransfer",
				fmt.Errorf(
					"azure file transfer: upload: error closing file %s: %v",
					task.Path,
					err,
				))
		}
	}(file)

	requestBody, err := getUploadRequestBody(task, file, ft.fileTransferStats, ft.logger)
	if err != nil {
		return err
	}

	resp, err := ft.uploadBlob(task, requestBody)
	if err != nil {
		return err
	}
	// The upload result is consumed for its status and headers, as with the SDK.
	if resp.Body != nil {
		resp.Body.Close()
		resp.Body = http.NoBody
	}
	task.Response = resp

	return nil
}

// uploadBlob uploads the given request body to a blob at task.Url.
func (ft *AzureFileTransfer) uploadBlob(
	task *DefaultUploadTask,
	requestBody io.Reader,
) (*http.Response, error) {
	client := ft.blockBlobClient
	if client == nil {
		var err error
		client, err = newAzureBlobHTTPClient(task.Url, nil, nil)
		if err != nil {
			return nil, err
		}
	}
	ctx := task.Context
	if ctx == nil {
		ctx = context.Background()
	}
	return client.UploadStream(ctx, requestBody, task.Headers)
}

type ParsedBlobInfo struct {
	AccountUrl string
	Container  string
	BlobPrefix string
}

// Download implements ArtifactFileTransfer.Download
func (ft *AzureFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug(
		"Azure file transfer: downloading file",
		"path", task.PathOrPrefix,
		"ref", task.Reference,
	)

	// Parse the reference path to get the account URL and blob path
	accountUrl, fullBlobPath, err := parseCloudReference(task.Reference, azureScheme)
	if err != nil {
		return ft.formatDownloadError("error parsing reference", err)
	}
	pathSplit := strings.SplitN(fullBlobPath, "/", 2)
	if len(pathSplit) != 2 || pathSplit[0] == "" {
		return ft.formatDownloadError(
			"error parsing reference",
			fmt.Errorf("missing container or blob path"),
		)
	}
	fullAccountUrl := fmt.Sprintf("%s://%s", azureScheme, accountUrl)
	blobInfo := ParsedBlobInfo{
		AccountUrl: fullAccountUrl,
		Container:  pathSplit[0],
		BlobPrefix: pathSplit[1],
	}

	// Setup the client if it is not already set up
	_, err = ft.clients.LoadOrStore(fullAccountUrl, setupAccountClient)
	if err != nil {
		return ft.formatDownloadError(
			"error setting up Azure account client",
			err,
		)
	}

	var blobNames []string
	if task.HasSingleFile() {
		blobName, versionId, err := ft.getBlob(blobInfo, task)
		if err != nil {
			return ft.formatDownloadError(
				"error getting correct blob name and version",
				err,
			)
		}
		if versionId != "" {
			err = task.SetVersionID(versionId)
			if err != nil {
				return ft.formatDownloadError(
					"error setting version ID",
					err,
				)
			}
		}
		blobNames = []string{blobName}
	} else {
		blobNames, err = ft.listBlobsWithPrefix(blobInfo)
		if err != nil {
			return ft.formatDownloadError(
				fmt.Sprintf("error finding blobs with prefix %s", blobInfo.BlobPrefix),
				err,
			)
		}
	}

	err = ft.downloadFiles(blobInfo, blobNames, task)
	if err != nil {
		return ft.formatDownloadError(
			fmt.Sprintf("error downloading reference %s", task.Reference),
			err,
		)
	}
	return nil
}

// getBlob tries to get the blob name and version ID that matches the
// expected digest for the given task.
func (ft *AzureFileTransfer) getBlob(
	blobInfo ParsedBlobInfo,
	task *ReferenceArtifactDownloadTask,
) (blobName, versionId string, err error) {
	blobClient := ft.blobClient
	if ft.blobClient == nil {
		client, err := setupBlobClient(task)
		if err != nil {
			return "", "", err
		}
		blobClient = client
	}
	matches, err := ft.checkVersionIDMatches(blobClient, task.Digest)
	if err != nil {
		return "", "", err
	}

	if matches {
		return blobInfo.BlobPrefix, "", nil
	}

	// If the version ID is specified but the etag does not match, return an error
	if task.VersionId != nil {
		return "", "", fmt.Errorf(
			"digest/etag mismatch: etag does not match expected digest %s",
			task.Digest,
		)
	}

	// Otherwise, find the correct blob version
	blobName, versionId, err = ft.getCorrectBlobVersion(blobInfo, task)
	if err != nil {
		return "", "", err
	}
	return blobName, versionId, nil
}

// getCorrectBlobVersion finds the correct blob version that matches the
// expected digest.
func (ft *AzureFileTransfer) getCorrectBlobVersion(
	blobInfo ParsedBlobInfo,
	task *ReferenceArtifactDownloadTask,
) (blobName, versionId string, err error) {
	client, err := ft.clients.GetClient(blobInfo.AccountUrl)
	if err != nil {
		return "", "", err
	}
	marker := ""
	seenMarkers := map[string]bool{}
	for {
		page, err := client.ListBlobs(ft.ctx, blobInfo.Container, blobInfo.BlobPrefix, marker, true)
		if err != nil {
			return "", "", err
		}
		for _, item := range page.Items {
			if item.Name != blobInfo.BlobPrefix || item.VersionID == "" {
				continue
			}
			blobClient, err := client.NewBlobClient(blobInfo.Container, item.Name).
				WithVersionID(item.VersionID)
			if err != nil {
				return "", "", err
			}
			matches, err := ft.checkVersionIDMatches(blobClient, task.Digest)
			if err != nil {
				return "", "", err
			}
			if matches {
				return item.Name, item.VersionID, nil
			}
		}
		if page.NextMarker == "" {
			break
		}
		if seenMarkers[page.NextMarker] {
			return "", "", fmt.Errorf("azure returned a repeated listing marker")
		}
		seenMarkers[page.NextMarker] = true
		marker = page.NextMarker
	}

	return "", "", fmt.Errorf(
		"digest/etag mismatch: unable to find version with expected digest %s for reference %s",
		task.Digest,
		task.Reference,
	)
}

// checkVersionIDMatches checks if the etag of the given blob matches the expected digest.
func (ft *AzureFileTransfer) checkVersionIDMatches(
	client AzureBlobClient,
	digest string,
) (bool, error) {
	properties, err := client.GetProperties(ft.ctx)
	if err != nil {
		return false, err
	}
	if properties.ETag != "" &&
		strings.Trim(properties.ETag, "\"") == digest {
		return true, nil
	}
	return false, nil
}

// listBlobsWithPrefix lists all the blobs in the container with the given prefix.
func (ft *AzureFileTransfer) listBlobsWithPrefix(
	blobInfo ParsedBlobInfo,
) ([]string, error) {
	client, err := ft.clients.GetClient(blobInfo.AccountUrl)
	if err != nil {
		return nil, err
	}

	blobNames := []string{}
	marker := ""
	seenMarkers := map[string]bool{}
	for {
		page, err := client.ListBlobs(
			ft.ctx,
			blobInfo.Container,
			blobInfo.BlobPrefix,
			marker,
			false,
		)
		if err != nil {
			return nil, err
		}
		for _, item := range page.Items {
			blobNames = append(blobNames, item.Name)
		}
		if page.NextMarker == "" {
			break
		}
		if seenMarkers[page.NextMarker] {
			return nil, fmt.Errorf("azure returned a repeated listing marker")
		}
		seenMarkers[page.NextMarker] = true
		marker = page.NextMarker
	}

	return blobNames, nil
}

// downloadFiles downloads all of the blobs with the given names.
func (ft *AzureFileTransfer) downloadFiles(
	blobInfo ParsedBlobInfo,
	blobNames []string,
	task *ReferenceArtifactDownloadTask,
) error {
	g := new(errgroup.Group)
	g.SetLimit(maxAzureWorkers)
	for _, blobName := range blobNames {
		g.Go(func() error {
			objectRelativePath, found := strings.CutPrefix(blobName, blobInfo.BlobPrefix)
			if !found {
				return fmt.Errorf("azure returned blob outside requested prefix: %q", blobName)
			}
			objectRelativePath = strings.TrimPrefix(objectRelativePath, "/")
			relativePath := filepath.FromSlash(objectRelativePath)
			if relativePath != "" && !filepath.IsLocal(relativePath) {
				return fmt.Errorf("azure blob path escapes download directory: %q", blobName)
			}
			localPath := filepath.Join(task.PathOrPrefix, relativePath)
			return ft.downloadBlobToFile(blobInfo, blobName, task, localPath)
		})
	}

	return g.Wait()
}

// downloadBlobToFile downloads a blob to a file at the given local path.
func (ft *AzureFileTransfer) downloadBlobToFile(
	blobInfo ParsedBlobInfo,
	blobName string,
	task *ReferenceArtifactDownloadTask,
	localPath string,
) error {
	// Create or open a local file where we can download the blob
	if err := os.MkdirAll(filepath.Dir(localPath), 0o755); err != nil {
		return fmt.Errorf(
			"unable to create destination directory %s: %w",
			filepath.Dir(localPath),
			err,
		)
	}

	destination, err := os.Create(localPath)
	if err != nil {
		return fmt.Errorf("unable to create destination file %s: %w", localPath, err)
	}

	defer destination.Close()

	// If version ID is specified, use the blob client to download the blob
	_, ok := task.VersionIDString()
	if ok {
		blobClient := ft.blobClient
		if blobClient == nil {
			client, err := setupBlobClient(task)
			if err != nil {
				return err
			}
			blobClient = client
		}
		_, err = blobClient.DownloadFile(ft.ctx, destination)
		return err
	} else {
		client, err := ft.clients.GetClient(blobInfo.AccountUrl)
		if err != nil {
			return err
		}
		_, err = client.DownloadFile(ft.ctx, blobInfo.Container, blobName, destination)
		return err
	}
}

func (ft *AzureFileTransfer) formatDownloadError(message string, err error) error {
	return fmt.Errorf("AzureFileTransfer: Download: %s: %w", message, err)
}
