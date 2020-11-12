import { update } from 'lodash';
import {useCallback, useState, useEffect,useMemo} from 'react';
import {useDeepMemo} from '../components/Panel2/hooks'

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

export interface File {
  fullPath: FullFilePath | null;
  loading: boolean;
  contents: string | null;
}

export type FullFilePath = ObjectId & {
  path: string;
};

export interface DirMetadata {
  type: 'dir';
  fullPath: string;
  size: number;

  dirs: {[name: string]: DirMetadata};
  files: {[name: string]: FileMetadata};
}

interface FileEntry {
  size: number;
  ref?: string;
  digest?: string;
  birthArtifactID?: string;
}
export type FileMetadata = {
  type: 'file';
  fullPath: string;
  url: string;
} & FileEntry;
export type MetadataNode = DirMetadata | FileMetadata;
export interface PathMetadata {
  fullPath: FullFilePath;
  loading: boolean;
  node: MetadataNode | null;
}

export interface FileDirectUrl {
  fullPath: FullFilePath;
  refPath: ObjectId | null;
  loading: boolean;
  directUrl: string | null;
}

///// The functions below preserve the current interface that loads files by
// fullPath. We will probably switch to loading by just id.

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

    console.log('PARLLEL ASYNC UPDATE IND', updateIndexes)

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

async function loadFilePathMetadata(
  fullPath: FullFilePath
) {
  const response = await fetch('http://localhost:8000/' + fullPath.path)
  console.log('FETCH RESPONSE', response)
  const text = await response.text();
  const contentType = response.headers.get("content-type");
  console.log('FETCH CONTENT TYPE', contentType)

  if (contentType == null) {
    return null;
  } else if (contentType.indexOf('text/html') !== -1) {
    var parser = new DOMParser();
    var doc = parser.parseFromString(text, 'text/html');
    const liEntries = doc.getElementsByTagName('li');
    const files: {[name: string]: FileMetadata} = {};
    const dirs: {[name: string]: DirMetadata} = {};
    for (let i = 0; i < liEntries.length; i++) {
      const entry = liEntries[i];
      let fileName = entry.children[0].innerHTML;
      if (fileName.endsWith('/')) {
        fileName = fileName.slice(0, fileName.length - 1);
        dirs[fileName] = {
          type: 'dir' as const,
          fullPath: fullPath.path + '/' + fileName,
          size: 0,
          dirs: {},
          files: {}
        }
      } else {
        files[fileName] = {
          type: 'file' as const,
          fullPath: fullPath.path + '/' + fileName,
          url: 'x',
          size: 0,
        }
      }
    }
    console.log('DIRS FILES', files, dirs)
    return {
      type: 'dir' as const,
      fullPath: fullPath.path,
      size: 0,
      dirs,
      files
    };
  } else {
    return {
      type: 'file' as const,
      fullPath: fullPath.path,
      url: 'http://localhost:8000/' + fullPath.path,
      size: 0
    }
  }
}
const metadataCache: {
  [assetPath: string]: ReturnType<typeof loadFilePathMetadata>
} = {};

async function cachedLoadFilePathMetadata(
  fullPath: FullFilePath
) {
  let cachedMetadata = metadataCache[fullPath.path];
  if (cachedMetadata == null) {
    cachedMetadata = loadFilePathMetadata(fullPath);
    metadataCache[fullPath.path] = cachedMetadata;
  }
  return cachedMetadata;
}


async function loadFileContent(
  fullPath: FullFilePath
) {
  const response = await fetch('http://localhost:8000/' + fullPath.path)
  console.log('FETCH RESPONSE', response)
  const text = await response.text();
  const contentType = response.headers.get("content-type");
  console.log('FETCH CONTENT TYPE', contentType)
  return {contents: text}
}

const fileCache: {
  [assetPath: string]: Promise<{
    contents: string;
  }>;
} = {};

async function cachedLoadFileContent(
  fullPath: FullFilePath
) {
  let cachedFile = fileCache[fullPath.path];
  if (cachedFile == null) {
    cachedFile = loadFileContent(fullPath);
    fileCache[fullPath.path] = cachedFile;
  }
  return cachedFile;
}

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

export type UsePathMetadata = (filePaths: FullFilePath[]) => PathMetadata[];

export const usePathMetadata: UsePathMetadata = filePaths => {
  const result = useParallelAsyncMap(
    filePaths,
    {},
    cachedLoadFilePathMetadata,
    fullFilePathEqual
  );
  const finalResult = useMemo(() => {
    return result.results.map((r, i) => ({
      fullPath: {...filePaths[i], artifactTypeName: filePaths[i].path},
      loading: r.loading,
      node: r.result ?? null,
    }));
  }, [filePaths, result.results]);
  return finalResult;
};

let count = 0;
export type UseFileDirectUrl = (filePaths: FullFilePath[]) => FileDirectUrl[];
export const useFileDirectUrl: UseFileDirectUrl = filePaths => {
  count += 1;
  if (count > 1000) {
    throw new Error('invalid')
  }
  console.log('USE FILE DIRECT', filePaths)
  filePaths = useDeepMemo(filePaths);
  return useMemo(() => {
    return filePaths.map((fullPath, i) => {
      const artifactPath = fullPath.artifactTypeName;
      const components = artifactPath.split('/');
      console.log('COMPONENTS', components)
      const artifactsIndex = components.findIndex(c => c === 'artifacts');
      let realFullPath = fullPath.path;
      if (artifactsIndex !== -1) {
        realFullPath = components.slice(0, artifactsIndex + 2).concat(fullPath.path).join('/')
      }
      console.log('REAL FULL PATH', realFullPath)
      return {
        fullPath: filePaths[i],
        refPath: null,
        loading: false,
        directUrl: 'http://localhost:8000/' + realFullPath ?? null,
      }
    });
  }, [filePaths]);
};

export type UseFileContent = (
  filePaths: Array<FullFilePath | null>,
  options?: {skip?: boolean}
) => File[];

export const useFileContent: UseFileContent = (filePaths, options) => {
  filePaths = useDeepMemo(filePaths);
  filePaths = useMemo(() => filePaths.map(fullPath => {
    const artifactPath = fullPath?.artifactTypeName ?? '';
    const components = artifactPath.split('/');
    const artifactsIndex = components.findIndex(c => c === 'artifacts');
    let realFullPath = fullPath?.path ?? '';
    if (artifactsIndex !== -1 && realFullPath.indexOf('artifacts') === -1) {
      realFullPath = components.slice(0, artifactsIndex + 2).concat(
        realFullPath).join('/')
    }
    console.log('CONTENT COMPONENTS', components, realFullPath)
    return fullPath == null ? null : {...fullPath, path: realFullPath}
  }), [filePaths]);
  const result = useParallelAsyncMap(
    filePaths,
    {},
    cachedLoadFileContent,
    fullFilePathEqual
  );
  const finalResult = useMemo(() => {
    return result.results.map((r, i) => ({
      fullPath: filePaths[i],
      loading: r.loading,
      contents: r.result?.contents ?? null,
    }));
  }, [filePaths, result.results]);
  return finalResult;
};