import * as Files from './files';
import * as Table from './table';
import * as PanelRegistry2 from './PanelRegistry';
import * as Masks from './mediaImage';
import * as LibTypes from './panellib/libtypes';

export type BasicType = 'any' | 'string' | 'number' | 'boolean' | null;

export type MediaType = 'image-file' | 'table' | 'joined-table';

export type SimpleType = BasicType | MediaType;

export function isSimpleType(t: Type): t is SimpleType {
  return typeof t === 'string' || t === null;
}

export interface RowType {
  type: 'row';
  objectType: Type;
}

export interface ColumnType {
  type: 'column';
  objectType: Type;
}

export interface TableType {
  type: 'table';
  objectType: Type;
}

// Unused
export interface Query {
  type: 'query';
  resultType: Type;
}

export interface File {
  type: 'file';
  extension: string;
}

export interface Artifact {
  type: 'artifact';
}

export interface Dir {
  type: 'dir';
}

export interface WBObjectFile {
  type: 'wb-object-file';
  mediaType: MediaType;
}

export interface TableInfo {
  type: 'table-info';
}

export interface Union {
  type: 'union';
  members: Type[];
}

export type Type =
  | RowType
  | ColumnType
  | TableType
  | SimpleType
  | MediaType
  | Query
  | Dir
  | File
  | Artifact
  | WBObjectFile
  | TableInfo
  | Union;

interface ObjType<T> {
  name: string;
  obj: Files.ObjectId;
  val: T;
}

export interface ResultTable<T> {
  columns: string[];
  context: Files.FullFilePath[];
  data: T[][];
}

export function inputIsSingle<T>(
  input: ObjType<T> | ResultTable<T>
): input is ObjType<T> {
  return (input as any).name != null;
}

// TODO: reduce the duplication between SingleValueTypeToTSType
// and TypeToTSType
type SingleValueTypeToTSType<T> = T extends 'string'
  ? string
  : T extends 'number'
  ? number
  : T extends 'boolean'
  ? boolean
  : T extends 'image-file'
  ? Masks.WBImage
  : T extends 'any'
  ? any
  : T extends Artifact
  ? Files.ObjectId
  : T extends File
  ? Files.LoadedPathMetadata
  : T extends WBObjectFile
  ? Files.LoadedPathMetadata
  : T extends TableInfo
  ? Table.Table
  : never;

export type TypeToTSType<T> = T extends 'string'
  ? ObjType<string>
  : T extends 'number'
  ? ObjType<number>
  : T extends 'boolean'
  ? ObjType<boolean>
  : T extends 'image-file'
  ? ObjType<Masks.WBImage>
  : T extends File
  ? ObjType<Files.LoadedPathMetadata>
  : T extends Artifact
  ? ObjType<Files.ObjectId>
  : T extends Dir
  ? ObjType<Files.LoadedPathMetadata>
  : T extends WBObjectFile
  ? ObjType<Files.LoadedPathMetadata>
  : T extends RowType
  ? ResultTable<SingleValueTypeToTSType<T['objectType']>>
  : T extends ColumnType
  ? ResultTable<SingleValueTypeToTSType<T['objectType']>>
  : T extends TableType
  ? ResultTable<SingleValueTypeToTSType<T['objectType']>>
  : T extends Union // Use a mapped type to distribute TypeToTSType over the members array, // then use [number] lookup on the array to get a union, which produces // a union of the array's members. (this basically says "give me the type // that would result from indexing the array with any number").
  ? {[K in keyof T['members']]: TypeToTSType<T['members'][K]>}[number]
  : never;

function typesMatch(type: Type, fitType: Type): boolean {
  console.log('TYPES MATCH', type, fitType);
  if (fitType === 'any') {
    return true;
  } else if (isSimpleType(type) && isSimpleType(fitType)) {
    return type === fitType;
  } else if (!isSimpleType(type) && !isSimpleType(fitType)) {
    if (type.type === 'row' && fitType.type === 'row') {
      return typesMatch(type.objectType, fitType.objectType);
    } else if (type.type === 'column' && fitType.type === 'column') {
      return typesMatch(type.objectType, fitType.objectType);
    } else if (type.type === 'table' && fitType.type === 'table') {
      return typesMatch(type.objectType, fitType.objectType);
    } else if (type.type === 'file' && fitType.type === 'file') {
      return type.extension === fitType.extension;
    } else if (type.type === 'dir' && fitType.type === 'dir') {
      return true;
    } else if (
      type.type === 'wb-object-file' &&
      fitType.type === 'wb-object-file'
    ) {
      return type.mediaType === fitType.mediaType;
    } else if (fitType.type === 'union') {
      // Note, this doesn't match union of unions
      return fitType.members.some(fitMemberType =>
        typesMatch(type, fitMemberType)
      );
    }
  }
  return false;
}

const getTypeHandlerStacksInternal = (currentType: Type) => {
  return LibTypes._getTypeHandlerStacks(
    currentType,
    PanelRegistry2.PanelSpecs,
    PanelRegistry2.ConverterSpecs,
    typesMatch
  );
};

// We memoize this, because its currently called a lot and is pretty
// expensive.
const typeHandlerCache: {
  [type: string]: ReturnType<typeof getTypeHandlerStacksInternal>;
} = {};
export const getTypeHandlerStacks = (currentType: Type) => {
  const typeId = JSON.stringify(currentType);
  let handler = typeHandlerCache[typeId];
  if (handler != null) {
    return handler;
  }
  handler = getTypeHandlerStacksInternal(currentType);
  typeHandlerCache[typeId] = handler;
  return handler;
};
