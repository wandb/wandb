import * as _ from 'lodash';

export interface MediaTable {
  columns: string[];
  data: any[][];
}

export type MediaType = 'string' | 'number' | 'unknown' | 'image-file';

export const detectColumnTypes = (table: MediaTable): MediaType[] => {
  const row0 = table.data[0];
  if (row0 == null) {
    return table.columns.map(() => 'unknown');
  }
  return table.columns.map((c, i) => {
    const val = row0[i];
    if (typeof val === 'string') {
      return 'string';
    } else if (typeof val === 'number') {
      return 'number';
    } else if (_.isArray(val)) {
      // TODO: nested type detection
      return 'unknown';
    } else if (_.isObject(val)) {
      if (
        // We don't use .type, but some old demo code did and I don't
        // want to break it
        (val as any).type === 'image-file' ||
        (val as any)._type === 'image-file'
      ) {
        return 'image-file';
      }
    }
    return 'unknown';
  });
};

// TODO: agg types are duplicated everywhere
export const agg = (
  type: 'concat' | 'max' | 'min' | 'avg' | undefined,
  data: any[]
) => {
  if (type == null || type === 'concat') {
    return data;
  } else if (type === 'max') {
    return _.max(data);
  } else if (type === 'min') {
    return _.min(data);
  } else {
    return _.sum(data) / data.length;
  }
};
