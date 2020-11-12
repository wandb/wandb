import React, {useCallback, useMemo} from 'react';
import {CardImage} from './ImageWithOverlays';
import {ControlsImageOverlays} from './ControlImageOverlays';
import * as Masks from './mediaImage';
import * as Controls from './controlsImage';
import * as Panel2 from './panel';

const inputType = 'image-file' as const;

export interface PanelImageConfig {
  overlayControls?: Controls.OverlayControls;
}
type PanelImageProps = Panel2.PanelProps<typeof inputType, PanelImageConfig>;

const PanelImageConfig: React.FC<PanelImageProps> = props => {
  const {context, config, updateConfig} = props;

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

const PanelImage: React.FC<PanelImageProps> = props => {
  const {context, updateContext, config, updateConfig} = props;
  const {obj, val} = props.input;
  const image: Masks.WBImage = val;

  const overlayControls = useMemo(() => config.overlayControls ?? {}, [
    config.overlayControls,
  ]);
  const classSets = context.classSets;

  const setMaskControls = useCallback(
    (controlId: string, control: Controls.OverlayState) => {
      updateConfig({
        overlayControls: {...overlayControls, [controlId]: control},
      });
    },
    [overlayControls, updateConfig]
  );
  const setClassSet = useCallback(
    (classSetId: string, classSet: Controls.ClassSetState) => {
      updateContext({
        classSets: {...classSets, [classSetId]: classSet},
      });
    },
    [classSets, updateContext]
  );
  const loadedImages = useMemo(() => {
    return [{loadedFrom: obj, image}];
  }, [image, obj]);
  const {maskControlsIDs, boxControlsIDs} = Controls.useWBImageControls(
    loadedImages,
    overlayControls,
    classSets,
    setMaskControls,
    setClassSet,
    false
  );

  return image != null ? (
    <div style={{width: 240}}>
      <CardImage
        image={{
          path: {...obj, path: image.path},
          width: image.width,
          height: image.height,
        }}
        boundingBoxes={
          image.boxes != null ? Object.values(image.boxes) : undefined
        }
        masks={
          image.masks != null
            ? Object.values(image.masks).map(m => ({...obj, path: m.path}))
            : undefined
        }
        classSets={classSets}
        maskControls={maskControlsIDs[0].map(id => overlayControls[id]) as any}
        boxControls={boxControlsIDs[0].map(id => overlayControls[id]) as any}
      />
    </div>
  ) : (
    <div>empty panelimage</div>
  );
};

export const Spec: Panel2.PanelSpec = {
  id: 'image',
  ConfigComponent: PanelImageConfig,
  Component: PanelImage,
  inputType,
};

// export const MultiImageSpec = makeMultiContainer(Spec);
