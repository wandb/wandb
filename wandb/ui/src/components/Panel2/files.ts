import * as _ from 'lodash';
import {useDeepMemo} from './hooks';
import {useEffect, useMemo, useState, useCallback} from 'react';
import * as Path from '../../util/path';
import {backendHost} from '../../config';
import {b64ToHex} from '../../util/digest';
import * as Types from './types';

import * as FilesBackend from '../../backend/files';

export interface ObjectId {
  entityName: string;
  projectName: string;
  artifactTypeName: string;
  artifactSequenceName: string;
  artifactCommitHash: string;
}

interface ArtifactFileId {
  artifactId: string;
  path: string;
}

export type FullFilePath = ObjectId & {
  path: string;
};

function fullFilePathEqual(p1: FullFilePath, p2: FullFilePath) {
  return (
    p1.entityName === p2.entityName &&
    p1.projectName === p2.projectName &&
    p1.artifactTypeName === p2.artifactTypeName &&
    p1.artifactSequenceName === p2.artifactSequenceName &&
    p1.artifactCommitHash === p2.artifactCommitHash &&
    p1.path === p2.path
  );
}

interface ArtifactPathInfo {
  entityName: string;
  projectName: string;
  artifactTypeName: string;
  artifactSequenceName: string;
  artifactCommitHash: string;
  artifactVersionIndex: number;
}

type ArtifactFileIdWithPathInfo = ArtifactFileId & ArtifactPathInfo;

interface ReadyManifest {
  manifest: Manifest;
  layout: 'V1' | 'V2';
  rootMetadata: DirMetadata;
}

export interface File {
  fullPath: FullFilePath | null;
  loading: boolean;
  contents: string | null;
}

export interface FileDirectUrl {
  fullPath: FullFilePath;
  refPath: ObjectId | null;
  loading: boolean;
  directUrl: string | null;
}
export interface DirMetadata {
  type: 'dir';
  fullPath: string;
  size: number;

  dirs: {[name: string]: DirMetadata};
  files: {[name: string]: FileMetadata};
}

export type FileMetadata = {
  type: 'file';
  fullPath: string;
  url: string;
} & FileEntry;
export type MetadataNode = DirMetadata | FileMetadata;

export interface FilePathWithMetadata {
  path: FullFilePath;
  metadata: MetadataNode | null;
}

export interface PathMetadata {
  fullPath: FullFilePath;
  loading: boolean;
  node: MetadataNode | null;
}

export interface LoadedPathMetadata {
  _type: 'loaded-path';
  fullPath: FullFilePath;
  node: MetadataNode | null;
}

export const isLoadedPathMetadata = (o: any): o is LoadedPathMetadata => {
  return o._type === 'loaded-path';
};

export interface FilePathMetadata {
  fullPath: FullFilePath;
  loading: boolean;
  node: FileMetadata;
}

interface FileEntry {
  size: number;
  ref?: string;
  digest?: string;
  birthArtifactID?: string;
}

interface Manifest {
  storagePolicy: string;
  storagePolicyConfig: {[key: string]: any};
  contents: {[name: string]: FileEntry};
}

// Global caches! Currently never cleaned up!
function artifactFileUrl(
  storagePolicy: string,
  storagePolicyConfig: {
    storageRegion?: string;
    storageLayout?: string;
  },
  defaultCloudRegion: string,
  entityName: string,
  entry: FileEntry
) {
  if (storagePolicy !== 'wandb-storage-policy-v1') {
    console.warn('unhandled storage policy');
    // Return a string for URL in this case. Clicking a download
    // link will be a no-op.
    return '';
  }
  const bucketRegion = storagePolicyConfig.storageRegion || defaultCloudRegion;
  const storageLayout = storagePolicyConfig.storageLayout || 'V1';

  if (entry.digest == null) {
    throw new Error('invalid');
  }
  switch (storageLayout) {
    case 'V1':
      return `${backendHost()}/artifacts/${entityName}/${b64ToHex(
        entry.digest
      )}`;
    case 'V2':
      return `${backendHost()}/artifactsV2/${bucketRegion}/${entityName}/${encodeURI(
        entry.birthArtifactID!
      )}/${b64ToHex(entry.digest)}`;
    default:
      console.warn(`unhandled storage layout: ${storageLayout}`);
      return '';
  }
}

function makeFileTree(
  entityName: string,
  defaultCloudRegion: string,
  manifest: Manifest
): DirMetadata {
  const fileEntries = manifest.contents;
  const fileTree: DirMetadata = {
    type: 'dir',
    fullPath: '',
    size: 0,
    dirs: {},
    files: {},
  };
  _.map(fileEntries, (entry, name) => {
    let currentFolder = fileTree;
    // 'media/images/image01.jpg' => ['media','images','image01.jpg']
    const path = name.split('/');
    while (path.length > 1) {
      // The following is safe to do because we made sure path had elems in the loop condition.
      const folderName = path.shift() as string;
      // create subfolder if it doesn't already exist
      if (!currentFolder.dirs[folderName]) {
        currentFolder.dirs[folderName] = {
          type: 'dir',
          fullPath:
            currentFolder.fullPath === ''
              ? folderName
              : currentFolder.fullPath + '/' + folderName,
          size: 0,
          dirs: {},
          files: {},
        };
      }
      currentFolder.dirs[folderName].size += entry.size;
      currentFolder = currentFolder.dirs[folderName];
    }
    // if we've come to the last item in the path, add this file object to the current folder
    currentFolder.files[path[0]] = {
      type: 'file',
      fullPath: name,
      url: entry.ref
        ? entry.ref
        : artifactFileUrl(
            manifest.storagePolicy,
            manifest.storagePolicyConfig,
            defaultCloudRegion,
            entityName,
            entry
          ),
      ...entry,
    };
  });
  return fileTree;
}

export function lookupNode(
  dir: DirMetadata,
  path: string
): MetadataNode | null {
  if (path === '') {
    return dir;
  }
  const pathItems = path.split('/');
  for (const pathItem of pathItems.slice(0, pathItems.length - 1)) {
    dir = dir.dirs[pathItem];
    if (dir == null) {
      return null;
    }
  }
  const lastItem = pathItems[pathItems.length - 1];
  return dir.dirs[lastItem] || dir.files[lastItem] || null;
}

function useParallelAsyncMap<T, R>(
  items: Array<T | null>,
  options: {skip?: boolean} | undefined,
  getResult: (item: T) => Promise<R>,
  itemsEqual: (i1: T, i2: T) => boolean
) {
  const nullableItemsEqual = useCallback(
    (i1: T | null, i2: T | null) => {
      if (i1 == null || i2 == null) {
        return i1 == null && i2 == null;
      }
      return itemsEqual(i1, i2);
    },
    [itemsEqual]
  );

  // DeepMemo this so the caller doesn't have to worry about ref-equality
  items = useDeepMemo(items);
  options = useDeepMemo(options);

  const [result, setResult] = useState<
    Array<{item: T | null; loading: boolean; result: R | null}>
  >([]);

  // Fetch new fileIds
  useEffect(() => {
    if (options?.skip) {
      return;
    }

    const updateIndexes: number[] = [];
    for (let i = 0; i < items.length; i++) {
      if (result[i] == null || !nullableItemsEqual(result[i].item, items[i])) {
        updateIndexes.push(i);
      }
    }
    if (updateIndexes.length === 0) {
      return;
    }

    const newResult: typeof result = [...result];
    // Always set result fileIds to the passed in fileIds, before
    // anything asynchronous happens. This guarantees that result
    // has the latest fileIds
    for (const updateIndex of updateIndexes) {
      newResult[updateIndex] = {
        item: items[updateIndex],
        loading: true,
        result: null,
      };
    }
    setResult(newResult);

    const updateItems = updateIndexes.map(i => items[i]);
    const proms = updateItems.map(item =>
      item != null ? getResult(item) : null
    );
    Promise.all(proms).then(itemResults => {
      setResult(latestResult => {
        const newPromiseResult: typeof result = [...latestResult];
        for (let i = 0; i < updateItems.length; i++) {
          const resultIndex = updateIndexes[i];
          const curResult = latestResult[resultIndex];
          const curItem = items[resultIndex];
          // Only update if fileId still matches our target result slot
          if (
            curResult == null ||
            nullableItemsEqual(curResult.item, curItem)
          ) {
            newPromiseResult[resultIndex] = {
              item: curItem,
              loading: false,
              result: itemResults[i],
            };
          }
        }
        return newPromiseResult;
      });
    });
  }, [items, result, getResult, nullableItemsEqual, options]);

  // Clean up glitches: ensure that output fileIds always exactly match
  // incoming fileIds
  const finalResult = useMemo(() => {
    const itemResults = items.map((item, i) => {
      if (result[i] == null || !nullableItemsEqual(result[i].item, item)) {
        return {
          item,
          loading: true,
          result: null,
        };
      } else {
        return result[i];
      }
    });
    return {
      loading: itemResults.some(r => r.loading),
      results: itemResults,
    };
  }, [items, result, nullableItemsEqual]);

  return finalResult;
}

///// The functions below preserve the current interface that loads files by
// fullPath. We will probably switch to loading by just id.

export type UsePathMetadata = (filePaths: FullFilePath[]) => PathMetadata[];

export const usePathMetadata: UsePathMetadata = FilesBackend.usePathMetadata;

export type UseFileDirectUrl = (filePaths: FullFilePath[]) => FileDirectUrl[];
export const useFileDirectUrl: UseFileDirectUrl = FilesBackend.useFileDirectUrl;

export type UseFileContent = (
  filePaths: Array<FullFilePath | null>,
  options?: {skip?: boolean}
) => File[];

export const useFileContent: UseFileContent = FilesBackend.useFileContent;

export const getPathType = (pm: LoadedPathMetadata): Types.Type => {
  if (pm.node == null) {
    return null;
  } else if (pm.node?.type === 'dir') {
    return {type: 'dir' as const};
  } else {
    const filePath = pm.fullPath.path;
    if (filePath.endsWith('.json')) {
      const components = filePath.split('.');
      // TODO: this is hard-coded right now
      if (components.length >= 3) {
        if (components[components.length - 2] === 'image-file') {
          return {
            type: 'wb-object-file' as const,
            mediaType: 'image-file' as const,
          };
        } else if (components[components.length - 2] === 'table') {
          return {
            type: 'wb-object-file' as const,
            mediaType: 'table' as const,
          };
        } else if (components[components.length - 2] === 'joined-table') {
          return {
            type: 'wb-object-file' as const,
            mediaType: 'joined-table' as const,
          };
        }
      }
    }
    return {
      type: 'file' as const,
      extension: Path.extension(filePath),
    };
  }
};

export const getPathsType = (paths: LoadedPathMetadata[]): Types.Type => {
  const pathTypes = paths.map(getPathType);
  if (pathTypes.length === 1) {
    return pathTypes[0];
  }
  const pathType0 = pathTypes[0];
  if (pathTypes.slice(1).some(pt => !_.isEqual(pt, pathType0))) {
    return {type: 'row' as const, objectType: 'any' as const};
  }
  return {
    type: 'row' as const,
    objectType: pathType0,
  };
};
