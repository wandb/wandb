interface MaskFile {
  type: 'mask-file';
  digest: string;
  path: string;
}

interface ClassesFile {
  type: 'classes-file';
  digest: string;
  path: string;
}

interface PositionMiddleBase {
  middle: [number, number];
  width: number;
  height: number;
}

interface PositionMinMax {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
}

export interface BoundingBox2D {
  position: PositionMiddleBase | PositionMinMax;
  class_id: number;
  box_caption?: string;
  scores?: {
    [key: string]: number;
  };
  domain?: 'pixel';
}

export interface WBImage {
  type: 'image-file';
  digest: string;
  path: string;
  width: number;
  height: number;
  boxes?: {
    [boxGroup: string]: BoundingBox2D[];
  };
  masks?: {
    [maskName: string]: MaskFile;
  };
  classes?: ClassesFile;
}

export interface ClassSet {
  type: 'class-set';
  class_set: Array<{name: string; id: number; color: string}>;
}
