import React, {useCallback, useMemo} from 'react';
import {CardImage} from './ImageWithOverlays';
import {ControlsImageOverlays} from './ControlImageOverlays';
import * as Obj from '../../util/obj';
import * as Controls from './controlsImage';
import * as Masks from './mediaImage';
import * as Panel2 from './panel';
import * as Table from './table';

const inputType = {
  type: 'row' as const,
  objectType: 'image-file' as const,
};

export interface PanelImageCompareConfig {
  overlayControls?: Controls.OverlayControls;
}

type PanelImageCompareProps = Panel2.PanelProps<
  typeof inputType,
  PanelImageCompareConfig
>;

const PanelImageCompareConfig: React.FC<PanelImageCompareProps> = props => {
  const {context, config, updateConfig} = props;

  if (context.classSets == null) {
    throw new Error('invalid');
  }

  return (
    <ControlsImageOverlays
      maskControls={config.overlayControls}
      classSets={context.classSets}
      setMaskControls={(controlId, newControl) =>
        updateConfig({
          overlayControls: {
            ...config.overlayControls,
            [controlId]: newControl,
          },
        })
      }
    />
  );
};

const PanelImageCompare: React.FC<PanelImageCompareProps> = props => {
  const {context, updateContext, config, updateConfig} = props;
  const input = props.input as Table.ResultTable;
  const images = input.data[0] as Masks.WBImage[];

  const overlayControls = useMemo(() => config.overlayControls ?? {}, [
    config.overlayControls,
  ]);
  const setMaskControls = useCallback(
    (controlId: string, control: Controls.OverlayState) =>
      updateConfig({
        overlayControls: {...overlayControls, [controlId]: control},
      }),
    [overlayControls, updateConfig]
  );
  const setClassSet = useCallback(
    (classSetId: string, classSet: Controls.ClassSetState) =>
      updateContext({
        classSets: {...context.classSets, [classSetId]: classSet},
      }),
    [context.classSets, updateContext]
  );
  const loadedImages = useMemo(() => {
    return images.map((image, i) => ({loadedFrom: input.context[i], image}));
  }, [images, input.context]);
  const {
    loading: controlsLoading,
    maskControlsIDs,
    boxControlsIDs,
  } = Controls.useWBImageControls(
    loadedImages,
    overlayControls,
    context.classSets,
    setMaskControls,
    setClassSet,
    false
  );

  if (controlsLoading) {
    return <div>loading</div>;
  }

  const anyNull = images.filter(i => i == null).length > 0;
  const nonNull = images.filter(Obj.notEmpty);

  const cantOverlay =
    anyNull ||
    nonNull.filter(
      p =>
        p.digest !== nonNull[0].digest ||
        p.classes?.digest !== nonNull[0].classes?.digest
    ).length > 0;

  console.log('OVERLAY CONTROLS', overlayControls);

  if (cantOverlay) {
    return (
      <div>
        {images.map((image, i) =>
          image == null ? (
            <div>{input.columns[i]}: null</div>
          ) : (
            <div style={{width: 240}}>
              {input.columns[i]}
              <CardImage
                image={{
                  path: {...input.context[i], path: image.path},
                  width: image.width,
                  height: image.height,
                }}
                boundingBoxes={
                  image.boxes != null ? Object.values(image.boxes) : undefined
                }
                masks={
                  image.masks != null
                    ? Object.values(image.masks).map(m => ({
                        ...input.context[i],
                        path: m.path,
                      }))
                    : undefined
                }
                classSets={context.classSets}
                maskControls={
                  maskControlsIDs[i].map(id => overlayControls[id]) as any
                }
                boxControls={
                  boxControlsIDs[i].map(id => overlayControls[id]) as any
                }
              />
            </div>
          )
        )}
      </div>
    );
  }

  const image0 = images[0];

  return image0 != null ? (
    <div style={{width: 240}}>
      <div>
        {input.columns.map((col, i) => (
          <span>
            {col}
            {i !== input.columns.length - 1 ? ', ' : ''}
          </span>
        ))}
      </div>
      <CardImage
        image={{
          path: {...input.context[0], path: image0.path},
          width: image0.width,
          height: image0.height,
        }}
        boundingBoxes={images.flatMap(image =>
          image?.boxes != null ? Object.values(image.boxes) : []
        )}
        masks={images.flatMap((image, i) =>
          image?.masks != null
            ? Object.values(image.masks).map(m => ({
                ...input.context[i],
                path: m.path,
              }))
            : []
        )}
        classSets={context.classSets}
        maskControls={
          (config.overlayControls != null
            ? maskControlsIDs.flatMap(ids => ids.map(id => overlayControls[id]))
            : []) as any
        }
        boxControls={
          (config.overlayControls != null
            ? boxControlsIDs.flatMap(ids => ids.map(id => overlayControls[id]))
            : []) as any
        }
      />
    </div>
  ) : (
    <div>null</div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'image-compare',
  displayName: 'Image Compare',
  ConfigComponent: PanelImageCompareConfig,
  Component: PanelImageCompare,
  inputType,
};

// export const MultiImageSpec = makeMultiContainer(Spec);
