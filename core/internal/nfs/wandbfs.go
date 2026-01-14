package nfs

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/smallfz/libnfs-go/fs"
)

// WandBFS implements fs.FS for W&B artifacts.
type WandBFS struct {
	mu          sync.RWMutex
	client      graphql.Client
	projectPath *ProjectPath
	cache       *DataCache
	contentCache *FileContentCache
	auditLog    *AuditLogger

	root     *VirtualNode
	nodeByID map[uint64]*VirtualNode
	nextID   uint64

	creds      fs.Creds
	attributes fs.Attributes
}

// NewWandBFS creates a new W&B filesystem.
func NewWandBFS(client graphql.Client, projectPath *ProjectPath, auditLog *AuditLogger) *WandBFS {
	wfs := &WandBFS{
		client:       client,
		projectPath:  projectPath,
		cache:        NewDataCache(client, projectPath),
		contentCache: NewFileContentCache(),
		auditLog:     auditLog,
		nodeByID:     make(map[uint64]*VirtualNode),
		nextID:       1000,
		attributes: fs.Attributes{
			LinkSupport:     true,
			SymlinkSupport:  true,
			ChownRestricted: true,
			MaxName:         255,
			MaxRead:         1048576,
			MaxWrite:        1048576,
			NoTrunc:         false,
		},
	}

	// Initialize root tree structure
	wfs.initTree()
	return wfs
}

func (wfs *WandBFS) allocID() uint64 {
	wfs.nextID++
	return wfs.nextID
}

func (wfs *WandBFS) registerNode(node *VirtualNode) {
	wfs.nodeByID[node.ID] = node
}

func (wfs *WandBFS) initTree() {
	// Create root node
	wfs.root = NewVirtualNode(wfs.allocID(), "", NodeTypeRoot, true)
	wfs.registerNode(wfs.root)

	// Create /artifacts directory
	artifacts := NewVirtualNode(wfs.allocID(), "artifacts", NodeTypeArtifactsDir, true)
	wfs.root.AddChild(artifacts)
	wfs.registerNode(artifacts)

	// Create /artifacts/types directory
	types := NewVirtualNode(wfs.allocID(), "types", NodeTypeTypesDir, true)
	artifacts.AddChild(types)
	wfs.registerNode(types)

	// Create /artifacts/collections directory
	collections := NewVirtualNode(wfs.allocID(), "collections", NodeTypeCollectionsDir, true)
	artifacts.AddChild(collections)
	wfs.registerNode(collections)

	// Create /runs directory
	runs := NewVirtualNode(wfs.allocID(), "runs", NodeTypeRunsDir, true)
	wfs.root.AddChild(runs)
	wfs.registerNode(runs)

	// Create /sweeps directory
	sweeps := NewVirtualNode(wfs.allocID(), "sweeps", NodeTypeSweepsDir, true)
	wfs.root.AddChild(sweeps)
	wfs.registerNode(sweeps)
}

// SetCreds sets the client credentials.
func (wfs *WandBFS) SetCreds(creds fs.Creds) {
	wfs.mu.Lock()
	wfs.creds = creds
	wfs.mu.Unlock()

	if wfs.auditLog != nil && creds != nil {
		wfs.auditLog.LogConnect(creds.Host(), creds.Uid(), creds.Gid())
	}
}

// getCredInfo returns current credentials info for logging.
func (wfs *WandBFS) getCredInfo() (string, uint32, uint32) {
	wfs.mu.RLock()
	defer wfs.mu.RUnlock()
	if wfs.creds == nil {
		return "", 0, 0
	}
	return wfs.creds.Host(), wfs.creds.Uid(), wfs.creds.Gid()
}

// Open opens a file for reading.
func (wfs *WandBFS) Open(name string) (fs.File, error) {
	return wfs.OpenFile(name, os.O_RDONLY, 0o644)
}

// OpenFile opens a file with flags.
func (wfs *WandBFS) OpenFile(name string, flag int, perm os.FileMode) (fs.File, error) {
	wfs.mu.Lock()
	defer wfs.mu.Unlock()

	// Check for write-only flags (O_RDWR is allowed since it includes read)
	if flag&(os.O_WRONLY|os.O_CREATE|os.O_APPEND|os.O_TRUNC) != 0 {
		return nil, os.ErrPermission
	}

	node, remaining := wfs.root.FindByPath(name)
	if len(remaining) > 0 {
		// Need to load more nodes
		if err := wfs.ensureLoadedLocked(node); err != nil {
			return nil, err
		}
		node, remaining = wfs.root.FindByPath(name)
		if len(remaining) > 0 {
			return nil, os.ErrNotExist
		}
	}

	// Get file data for metadata.json files
	var data []byte
	if node.Type == NodeTypeMetadataJSON {
		slog.Debug("OpenFile: loading artifact metadata.json",
			"name", name,
			"artifactID", node.ArtifactID)
		metadata, err := wfs.cache.GetMetadata(context.Background(), node.ArtifactID)
		if err != nil {
			slog.Error("OpenFile: failed to get metadata",
				"name", name,
				"error", err)
			return nil, fmt.Errorf("getting metadata for %s: %w", name, err)
		}
		data, err = metadata.ToJSON()
		if err != nil {
			slog.Error("OpenFile: failed to serialize metadata",
				"name", name,
				"error", err)
			return nil, fmt.Errorf("serializing metadata for %s: %w", name, err)
		}
		node.FileSize = int64(len(data))
		slog.Debug("OpenFile: artifact metadata.json loaded",
			"name", name,
			"dataLen", len(data))
	} else if node.Type == NodeTypeRunMetadataJSON {
		slog.Debug("OpenFile: loading run metadata.json",
			"name", name,
			"runName", node.RunName)
		runs, err := wfs.cache.GetRuns(context.Background())
		if err != nil {
			slog.Error("OpenFile: failed to get runs",
				"name", name,
				"error", err)
			return nil, fmt.Errorf("getting runs for %s: %w", name, err)
		}

		// Find the run with matching name
		for _, run := range runs {
			if run.Name == node.RunName {
				runMetadata := map[string]interface{}{
					"id":          run.ID,
					"name":        run.Name,
					"displayName": run.DisplayName,
					"state":       run.State,
					"createdAt":   run.CreatedAt,
					"sweepName":   run.SweepName,
					"username":    run.Username,
				}

				// Parse config from JSON string
				if run.Config != "" {
					var config interface{}
					if err := json.Unmarshal([]byte(run.Config), &config); err == nil {
						runMetadata["config"] = config
					}
				}

				// Parse summary from JSON string
				if run.SummaryMetrics != "" {
					var summary interface{}
					if err := json.Unmarshal([]byte(run.SummaryMetrics), &summary); err == nil {
						runMetadata["summary"] = summary
					}
				}

				if run.HeartbeatAt != nil {
					runMetadata["heartbeatAt"] = run.HeartbeatAt
				}

				data, err = json.MarshalIndent(runMetadata, "", "  ")
				if err != nil {
					slog.Error("OpenFile: failed to serialize run metadata",
						"name", name,
						"error", err)
					return nil, fmt.Errorf("serializing run metadata for %s: %w", name, err)
				}
				node.FileSize = int64(len(data))
				break
			}
		}
		slog.Debug("OpenFile: run metadata.json loaded",
			"name", name,
			"dataLen", len(data))
	}

	slog.Info("OpenFile: creating file handle",
		"name", name,
		"nodeType", node.Type,
		"hasData", data != nil,
		"dataLen", len(data))

	if wfs.auditLog != nil {
		host, uid, gid := wfs.getCredInfoLocked()
		wfs.auditLog.LogOpen(host, uid, gid, name, nil)
	}

	return newWandBFile(wfs, node, data), nil
}

func (wfs *WandBFS) getCredInfoLocked() (string, uint32, uint32) {
	if wfs.creds == nil {
		return "", 0, 0
	}
	return wfs.creds.Host(), wfs.creds.Uid(), wfs.creds.Gid()
}

// Stat returns file info for the given path.
func (wfs *WandBFS) Stat(name string) (fs.FileInfo, error) {
	wfs.mu.Lock()
	defer wfs.mu.Unlock()

	node, remaining := wfs.root.FindByPath(name)
	if len(remaining) > 0 {
		// Need to load more nodes
		if err := wfs.ensureLoadedLocked(node); err != nil {
			if wfs.auditLog != nil {
				host, uid, gid := wfs.getCredInfoLocked()
				wfs.auditLog.LogStat(host, uid, gid, name, err)
			}
			return nil, err
		}
		node, remaining = wfs.root.FindByPath(name)
		if len(remaining) > 0 {
			err := os.ErrNotExist
			if wfs.auditLog != nil {
				host, uid, gid := wfs.getCredInfoLocked()
				wfs.auditLog.LogStat(host, uid, gid, name, err)
			}
			return nil, err
		}
	}

	// Update file size for artifact metadata.json
	if node.Type == NodeTypeMetadataJSON && node.FileSize == 0 {
		metadata, err := wfs.cache.GetMetadata(context.Background(), node.ArtifactID)
		if err == nil {
			data, _ := metadata.ToJSON()
			node.FileSize = int64(len(data))
		}
	}

	// Update file size for run metadata.json
	if node.Type == NodeTypeRunMetadataJSON && node.FileSize == 0 {
		runs, err := wfs.cache.GetRuns(context.Background())
		if err == nil {
			for _, run := range runs {
				if run.Name == node.RunName {
					runMetadata := map[string]interface{}{
						"id":          run.ID,
						"name":        run.Name,
						"displayName": run.DisplayName,
						"state":       run.State,
						"createdAt":   run.CreatedAt,
						"sweepName":   run.SweepName,
						"username":    run.Username,
					}
					if run.Config != "" {
						var config interface{}
						if json.Unmarshal([]byte(run.Config), &config) == nil {
							runMetadata["config"] = config
						}
					}
					if run.SummaryMetrics != "" {
						var summary interface{}
						if json.Unmarshal([]byte(run.SummaryMetrics), &summary) == nil {
							runMetadata["summary"] = summary
						}
					}
					if run.HeartbeatAt != nil {
						runMetadata["heartbeatAt"] = run.HeartbeatAt
					}
					data, _ := json.MarshalIndent(runMetadata, "", "  ")
					node.FileSize = int64(len(data))
					break
				}
			}
		}
	}

	if wfs.auditLog != nil {
		host, uid, gid := wfs.getCredInfoLocked()
		wfs.auditLog.LogStat(host, uid, gid, name, nil)
	}

	return node.GetFileInfo(), nil
}

// ensureLoaded ensures a node's children are loaded (thread-safe).
func (wfs *WandBFS) ensureLoaded(node *VirtualNode) error {
	wfs.mu.Lock()
	defer wfs.mu.Unlock()
	return wfs.ensureLoadedLocked(node)
}

// ensureLoadedLocked ensures a node's children are loaded (must hold lock).
func (wfs *WandBFS) ensureLoadedLocked(node *VirtualNode) error {
	if node.Loaded {
		return node.LoadErr
	}

	ctx := context.Background()

	switch node.Type {
	case NodeTypeTypesDir:
		// Load artifact types
		types, err := wfs.cache.GetTypes(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, typeName := range types {
			typeNode := NewVirtualNode(wfs.allocID(), typeName, NodeTypeArtifactType, true)
			node.AddChild(typeNode)
			wfs.registerNode(typeNode)
		}

	case NodeTypeArtifactType:
		// Load collections for this type and create symlinks
		collections, err := wfs.cache.GetCollections(ctx, node.Name)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, coll := range collections {
			// Create symlink to ../../collections/{name}
			target := fmt.Sprintf("../../collections/%s", coll.Name)
			symlinkNode := NewSymlinkNode(wfs.allocID(), coll.Name, target)
			symlinkNode.CollectionName = coll.Name
			symlinkNode.ArtifactType = node.Name
			node.AddChild(symlinkNode)
			wfs.registerNode(symlinkNode)
		}

	case NodeTypeCollectionsDir:
		// Load all collections
		collections, err := wfs.cache.GetAllCollections(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}
		// Group by collection name (multiple types might have same collection)
		seen := make(map[string]bool)
		for _, coll := range collections {
			if seen[coll.Name] {
				continue
			}
			seen[coll.Name] = true

			collNode := NewVirtualNode(wfs.allocID(), coll.Name, NodeTypeCollection, true)
			collNode.CollectionName = coll.Name
			collNode.ArtifactType = coll.TypeName
			node.AddChild(collNode)
			wfs.registerNode(collNode)

			// Add versions under the collection
			for _, ver := range coll.Versions {
				verNode := NewVirtualNode(wfs.allocID(), fmt.Sprintf("v%d", ver.Index), NodeTypeVersion, true)
				verNode.ArtifactID = ver.ID
				verNode.VersionIndex = ver.Index
				verNode.CollectionName = coll.Name
				verNode.ArtifactType = coll.TypeName
				collNode.AddChild(verNode)
				wfs.registerNode(verNode)
			}
		}

	case NodeTypeCollection:
		// Load versions for this collection
		// First find the type for this collection
		types, err := wfs.cache.GetTypes(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, typeName := range types {
			collections, err := wfs.cache.GetCollections(ctx, typeName)
			if err != nil {
				continue
			}
			for _, coll := range collections {
				if coll.Name == node.CollectionName {
					for _, ver := range coll.Versions {
						if _, exists := node.Children[fmt.Sprintf("v%d", ver.Index)]; exists {
							continue
						}
						verNode := NewVirtualNode(wfs.allocID(), fmt.Sprintf("v%d", ver.Index), NodeTypeVersion, true)
						verNode.ArtifactID = ver.ID
						verNode.VersionIndex = ver.Index
						verNode.CollectionName = coll.Name
						verNode.ArtifactType = typeName
						node.AddChild(verNode)
						wfs.registerNode(verNode)
					}
				}
			}
		}

	case NodeTypeVersion:
		// Load version contents: metadata.json and files/
		metaNode := NewVirtualNode(wfs.allocID(), "metadata.json", NodeTypeMetadataJSON, false)
		metaNode.ArtifactID = node.ArtifactID
		metaNode.VersionIndex = node.VersionIndex
		node.AddChild(metaNode)
		wfs.registerNode(metaNode)

		filesNode := NewVirtualNode(wfs.allocID(), "files", NodeTypeFilesDir, true)
		filesNode.ArtifactID = node.ArtifactID
		node.AddChild(filesNode)
		wfs.registerNode(filesNode)

	case NodeTypeFilesDir:
		// Load files for this artifact
		files, err := wfs.cache.GetFiles(ctx, node.ArtifactID)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, f := range files {
			fileNode := NewVirtualNode(wfs.allocID(), f.Name, NodeTypeFile, false)
			fileNode.FileSize = f.SizeBytes
			fileNode.DirectURL = f.DirectURL
			fileNode.MD5 = f.MD5
			fileNode.ArtifactID = node.ArtifactID
			node.AddChild(fileNode)
			wfs.registerNode(fileNode)
		}

	// Run types
	case NodeTypeRunsDir:
		// Load all runs
		runs, err := wfs.cache.GetRuns(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, run := range runs {
			runNode := NewVirtualNode(wfs.allocID(), run.Name, NodeTypeRun, true)
			runNode.RunID = run.ID
			runNode.RunName = run.Name
			runNode.RunState = run.State
			runNode.SweepName = run.SweepName
			node.AddChild(runNode)
			wfs.registerNode(runNode)
		}

	case NodeTypeRun:
		// Add metadata.json and files/ directory
		metaNode := NewVirtualNode(wfs.allocID(), "metadata.json", NodeTypeRunMetadataJSON, false)
		metaNode.RunID = node.RunID
		metaNode.RunName = node.RunName
		node.AddChild(metaNode)
		wfs.registerNode(metaNode)

		filesNode := NewVirtualNode(wfs.allocID(), "files", NodeTypeRunFilesDir, true)
		filesNode.RunID = node.RunID
		filesNode.RunName = node.RunName
		node.AddChild(filesNode)
		wfs.registerNode(filesNode)

	case NodeTypeRunFilesDir:
		// Load run files
		files, err := wfs.cache.GetRunFiles(ctx, node.RunName)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, f := range files {
			fileNode := NewVirtualNode(wfs.allocID(), f.Name, NodeTypeRunFile, false)
			fileNode.FileSize = f.SizeBytes
			fileNode.DirectURL = f.DirectURL
			fileNode.MD5 = f.MD5
			fileNode.RunID = node.RunID
			fileNode.RunName = node.RunName
			node.AddChild(fileNode)
			wfs.registerNode(fileNode)
		}

	// Sweep types
	case NodeTypeSweepsDir:
		// Load all sweeps
		sweeps, err := wfs.cache.GetSweeps(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}
		for _, sweep := range sweeps {
			sweepNode := NewVirtualNode(wfs.allocID(), sweep.Name, NodeTypeSweep, true)
			sweepNode.SweepID = sweep.ID
			node.AddChild(sweepNode)
			wfs.registerNode(sweepNode)
		}

	case NodeTypeSweep:
		// Add runs/ subdirectory for this sweep
		runsNode := NewVirtualNode(wfs.allocID(), "runs", NodeTypeSweepRunsDir, true)
		runsNode.SweepID = node.SweepID
		node.AddChild(runsNode)
		wfs.registerNode(runsNode)

	case NodeTypeSweepRunsDir:
		// Load runs and create symlinks for runs in this sweep
		runs, err := wfs.cache.GetRuns(ctx)
		if err != nil {
			node.LoadErr = err
			return err
		}

		// Get sweep name from parent
		sweepName := node.Parent.Name

		for _, run := range runs {
			if run.SweepName == sweepName {
				// Create symlink to ../../../runs/{run_name}
				// Need 3 levels up: /sweeps/{sweep}/runs/ -> /sweeps/{sweep}/ -> /sweeps/ -> /
				target := fmt.Sprintf("../../../runs/%s", run.Name)
				symlinkNode := NewSymlinkNode(wfs.allocID(), run.Name, target)
				symlinkNode.RunID = run.ID
				symlinkNode.RunName = run.Name
				node.AddChild(symlinkNode)
				wfs.registerNode(symlinkNode)
			}
		}
	}

	node.Loaded = true
	node.ModTime = time.Now()
	return nil
}

// Chmod is not supported (read-only filesystem).
func (wfs *WandBFS) Chmod(name string, perm os.FileMode) error {
	return os.ErrPermission
}

// Chown is not supported (read-only filesystem).
func (wfs *WandBFS) Chown(name string, uid, gid int) error {
	return os.ErrPermission
}

// Symlink is not supported (read-only filesystem).
func (wfs *WandBFS) Symlink(oldName, newName string) error {
	return os.ErrPermission
}

// Readlink returns the target of a symlink.
func (wfs *WandBFS) Readlink(name string) (string, error) {
	wfs.mu.Lock()
	defer wfs.mu.Unlock()

	node, remaining := wfs.root.FindByPath(name)
	if len(remaining) > 0 {
		if err := wfs.ensureLoadedLocked(node); err != nil {
			return "", err
		}
		node, remaining = wfs.root.FindByPath(name)
		if len(remaining) > 0 {
			return "", os.ErrNotExist
		}
	}

	if !node.IsSymlink {
		return "", os.ErrInvalid
	}

	if wfs.auditLog != nil {
		host, uid, gid := wfs.getCredInfoLocked()
		wfs.auditLog.LogReadlink(host, uid, gid, name, nil)
	}

	return node.SymlinkTarget, nil
}

// Link is not supported (read-only filesystem).
func (wfs *WandBFS) Link(oldName, newName string) error {
	return os.ErrPermission
}

// Rename is not supported (read-only filesystem).
func (wfs *WandBFS) Rename(oldName, newName string) error {
	return os.ErrPermission
}

// Remove is not supported (read-only filesystem).
func (wfs *WandBFS) Remove(name string) error {
	return os.ErrPermission
}

// MkdirAll is not supported (read-only filesystem).
func (wfs *WandBFS) MkdirAll(name string, perm os.FileMode) error {
	return os.ErrPermission
}

// GetFileId returns the unique ID for a file.
func (wfs *WandBFS) GetFileId(fi fs.FileInfo) uint64 {
	if wfi, ok := fi.(*WandBFileInfo); ok {
		return wfi.id
	}
	return 0xffffffffffffffff
}

// GetRootHandle returns the handle for the root directory.
func (wfs *WandBFS) GetRootHandle() []byte {
	buf := make([]byte, 8)
	binary.BigEndian.PutUint64(buf, wfs.root.ID)
	return buf
}

// GetHandle returns the handle for a file.
func (wfs *WandBFS) GetHandle(fi fs.FileInfo) ([]byte, error) {
	id := wfs.GetFileId(fi)
	if id == 0xffffffffffffffff {
		return nil, os.ErrNotExist
	}
	buf := make([]byte, 8)
	binary.BigEndian.PutUint64(buf, id)
	return buf, nil
}

// ResolveHandle resolves a handle to a path.
func (wfs *WandBFS) ResolveHandle(fh []byte) (string, error) {
	if len(fh) < 8 {
		return "", os.ErrNotExist
	}

	id := binary.BigEndian.Uint64(fh[:8])

	wfs.mu.RLock()
	node, ok := wfs.nodeByID[id]
	wfs.mu.RUnlock()

	if !ok {
		return "", os.ErrNotExist
	}

	return node.FullPath(), nil
}

// Attributes returns the filesystem attributes.
func (wfs *WandBFS) Attributes() *fs.Attributes {
	return &wfs.attributes
}
