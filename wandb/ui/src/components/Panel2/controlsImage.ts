import * as _ from 'lodash';
import {useEffect, useState} from 'react';
import * as File from './files';
import * as MediaImage from './mediaImage';
import * as Color from './colors';

export type LineStyle = 'line' | 'dotted' | 'dashed';

export interface ClassSetState {
  classes: {
    [classID: string]: {
      color: string;
      name: string;
    };
  };
}

export interface ClassSetControls {
  [classSetID: string]: ClassSetState;
}

export interface OverlayControls {
  [overlayID: string]: OverlayState;
}

export interface OverlayClassState {
  opacity: number;
  disabled: boolean;
}

export interface BaseOverlayState {
  type: ControlType;
  name: string;
  disabled: boolean;
  loadedFrom: File.ObjectId;
  classSearch: string;
  classSetID: string;
  classStates: {
    [classID: string]: OverlayClassState;
  };
}

export interface BoxControlState extends BaseOverlayState {
  type: 'box';
  lineStyle: LineStyle;
}

export interface MaskControlState extends BaseOverlayState {
  type: 'mask';
}

export type OverlayState = BoxControlState | MaskControlState;
export type ControlType = OverlayState['type'];

export type UpdateControl = <T extends BaseOverlayState>(
  newControl: Partial<T>
) => void;

export function useControlHelpers(
  control: BaseOverlayState,
  updateControl: UpdateControl
) {
  return {
    toggleControlVisibility: () => updateControl({disabled: !control.disabled}),
  };
}

function createBaseControls(
  name: string,
  loadedFrom: File.ObjectId,
  classSetID: string,
  classSet: ClassSetState
): Omit<BaseOverlayState, 'type'> {
  const classStates = Object.fromEntries(
    Object.keys(classSet.classes).map(classID => [
      classID,
      {opacity: 1, disabled: false},
    ])
  );
  return {
    name,
    loadedFrom,
    classSetID,
    classStates,
    classSearch: '',
    disabled: false,
  };
}

export function createMaskControls(
  ...args: Parameters<typeof createBaseControls>
) {
  return {...createBaseControls(...args), type: 'mask'};
}

export function createBoxControls(
  ...args: Parameters<typeof createBaseControls>
): BoxControlState {
  return {
    ...createBaseControls(...args),
    type: 'box',
    lineStyle: 'line',
  };
}

interface LoadedWBImage {
  loadedFrom: File.ObjectId;
  image: MediaImage.WBImage | null;
}

// Well, this turned out huge and ugly. But it works.
// It's probably doing way too much work right now.

/**
 * Adds path property to loaded images.
 * @note Adds warning to array if path doesn't exist.
 */
const getClassFilePaths = (
  loadedImages: LoadedWBImage[],
  warnings: string[] = [],
  options?: {skip?: boolean}
) => {
  const logMissingWarning = (li: LoadedWBImage) =>
    warnings.push(
      `WBImage from ${li.loadedFrom.artifactCommitHash} is missing classes.`
    );

  return options?.skip
    ? []
    : loadedImages.map(li => {
        const contents = li.image?.classes;
        if (contents == null) {
          logMissingWarning(li);
          return null;
        }
        return {...li.loadedFrom, path: contents.path};
      });
};

/**
 * Given an wandb image object, make sure we have populated the right defaults
 * in the context.
 */
export const useWBImageControls = (
  loadedImages: LoadedWBImage[],
  maskControls: OverlayControls | undefined,
  classSets: ClassSetControls | undefined,
  setMaskControls: (controlId: string, control: OverlayState) => void,
  setClassSet: (classSetId: string, classSet: ClassSetState) => void,
  skip: boolean
): {
  loading: boolean;
  controlIDs: string[][];
  maskControlsIDs: string[][];
  boxControlsIDs: string[][];
  warnings: string[];
} => {
  const warnings: string[] = [];
  const classFilePaths = getClassFilePaths(loadedImages, warnings, {
    skip,
  });
  const classFileContents = File.useFileContent(classFilePaths, {skip});
  const loading = skip || classFileContents.some(fc => fc.loading);

  const [controlIDs, setControlsIDs] = useState<string[][]>([]);

  useEffect(() => {
    if (loading) {
      return;
    }
    console.log('IN MASK HOOK');
    const nextControlsIDs = loadedImages.map((loadedImage, index) => {
      if (loadedImage.image == null) {
        return [];
      }

      const classFile = classFileContents[index];

      const classSetID = loadedImage.image.classes?.digest;
      if (classSetID == null) {
        return [];
      }

      let classSet = classSets?.[classSetID]!;
      if (classSet == null) {
        // Watch out, we're assuming user-input is valid here, parsing straight
        // from JSON into type data.
        // TODO: fix me with warning system
        let parsed: MediaImage.ClassSet = {
          type: 'class-set',
          class_set: [],
        };

        try {
          parsed = JSON.parse(classFile.contents!);
        } catch {
          // pass
        }

        classSet = {
          classes: _.fromPairs(
            parsed.class_set.map(classInfo => [
              classInfo.id,
              {
                color:
                  classInfo.color || Color.colorN(classInfo.id, Color.ROBIN16),
                name: classInfo.name,
              },
            ])
          ),
        };
        setClassSet(classSetID, classSet);
      }

      const setDefaultControlsState = (
        type: ControlType,
        maskControlsID: string,
        maskName: string
      ) => {
        if (maskControls?.[maskControlsID] != null) {
          return;
        }

        const createFn =
          type === 'box' ? createBoxControls : createMaskControls;
        const controls = createFn(
          maskName,
          loadedImage.loadedFrom,
          classSetID,
          classSet
        ) as OverlayState;
        setMaskControls(maskControlsID, controls);
      };

      const createControls = (type: ControlType, maskName: string) => {
        const controlsID = `${type}-${index}-${classSetID}-${maskName}`;
        setDefaultControlsState(type, controlsID, maskName);
        return controlsID;
      };

      const {boxes, masks} = loadedImage.image;
      const boxKeys = Object.keys(boxes ?? {});
      const maskKeys = Object.keys(masks ?? {});

      const imageBoundingBoxControlsIDs: string[] = boxKeys.map(k =>
        createControls('box', k)
      );
      const imageMaskControlsIDs: string[] = maskKeys.map(k =>
        createControls('mask', k)
      );

      return [...imageBoundingBoxControlsIDs, ...imageMaskControlsIDs];
    });
    setControlsIDs(nextControlsIDs);
  }, [
    classFileContents,
    classSets,
    loadedImages,
    loading,
    maskControls,
    setClassSet,
    setMaskControls,
  ]);

  const maskControlsIDs = controlIDs.map(mc =>
    mc.filter(id => id.startsWith('mask-'))
  );
  const boxControlsIDs = controlIDs.map(mc =>
    mc.filter(id => id.startsWith('box-'))
  );

  // We ensure that output length always matches input length, but its
  // possible to get glitches where old controls are returned for a given
  // input. We can use something like useParallelAsyncMap in files.ts to
  // fix this.
  if (loading || controlIDs.length !== loadedImages.length) {
    return {
      loading,
      controlIDs: loadedImages.map(li => []),
      maskControlsIDs: loadedImages.map(li => []),
      boxControlsIDs: loadedImages.map(li => []),
      warnings,
    };
  }

  return {
    loading,
    controlIDs,
    maskControlsIDs,
    boxControlsIDs,
    warnings,
  };
};
