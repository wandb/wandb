import * as _ from 'lodash';
import React, {useRef} from 'react';
import * as File from './files';
import * as Color from './colors';
import * as Controls from './controlsImage';

import {useState, useEffect} from 'react';
import {BoundingBox2D} from './mediaImage';
import makeComp from '../../util/profiler';

export const clearCanvas = (canvas: HTMLCanvasElement) => {
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Tried to clear canvas without context');
  }
  ctx.clearRect(0, 0, canvas.width, canvas.height);
};

export const lineDashArray = (dashStyle: Controls.LineStyle) => {
  const mapping = {
    line: [],
    dotted: [2, 2],
    dashed: [12, 6],
  };

  return mapping[dashStyle];
};

export const boxColor = (id: number) => {
  return Color.colorN(id, Color.ROBIN16);
};

// Copied from media.tsx, for some reason importing media.tsx
// doesn't work with storybook, at least at the moment I'm doing
// this on the plane with no wifi (and therefore no ability to
// update yarn packages).
export const DEFAULT_ALL_MASK_CONTROL: Controls.OverlayClassState = {
  disabled: false,
  opacity: 0.6,
};

export const DEFAULT_CLASS_MASK_CONTROL: Controls.OverlayClassState = {
  disabled: false,
  opacity: 1,
};

interface CardImageProps {
  image: {
    path: File.FullFilePath;
    width: number;
    height: number;
  };
  masks?: File.FullFilePath[];
  boundingBoxes?: BoundingBox2D[][];
  classSets?: Controls.ClassSetControls;
  maskControls: Controls.MaskControlState[];
  boxControls: Controls.BoxControlState[];
}

export const CardImage: React.FC<CardImageProps> = makeComp(
  props => {
    const {
      image,
      masks,
      boundingBoxes,
      classSets,
      boxControls,
      maskControls,
    } = props;

    const imageFile = File.useFileDirectUrl([image.path])[0];

    return (
      <div
        style={{
          position: 'relative',
          width: '100%',
          /* paddingTop percent trick to maintain image aspect ratio while
             loading */
          paddingTop: `${(image.height / image.width) * 100}%`,
        }}>
        {imageFile.loading ? (
          <div />
        ) : (
          <>
            <img
              style={{
                position: 'absolute',
                left: 0,
                top: 0,
                maxHeight: '100%',
                maxWidth: '100%',
              }}
              alt={imageFile.fullPath.path}
              // TODO: (no !)
              src={imageFile.directUrl!}
            />
            {masks != null &&
              _.map(maskControls, (maskControl, i) => {
                const mask = masks[i];
                const classSet = (classSets || {})[maskControl.classSetID];
                if (maskControl != null) {
                  return (
                    <SegmentationMask
                      key={i}
                      style={{
                        position: 'absolute',
                        left: 0,
                        top: 0,
                      }}
                      filePath={mask}
                      mediaSize={{width: image.width, height: image.height}}
                      maskControls={maskControl as Controls.MaskControlState}
                      classSet={classSet}
                    />
                  );
                }
                return undefined;
              })}

            {boundingBoxes != null &&
              _.map(boxControls, (boxControl, i) => {
                const classSet = classSets?.[boxControl.classSetID];
                return (
                  <BoundingBoxes
                    key={i}
                    style={{
                      position: 'absolute',
                      left: 0,
                      top: 0,
                    }}
                    bboxControls={boxControl as Controls.BoxControlState}
                    boxData={boundingBoxes[i]}
                    mediaSize={{width: image.width, height: image.height}}
                    classSet={classSet}
                  />
                );
              })}
          </>
        )}
      </div>
    );
  },
  {id: 'CardImage'}
);

const SegmentationMask = makeComp(
  (props: {
    filePath: File.FullFilePath;
    style?: React.CSSProperties;
    mediaSize: {
      width: number;
      height: number;
    };
    maskControls: Controls.MaskControlState;
    classSet: Controls.ClassSetState;
  }) => {
    const {filePath, classSet, maskControls} = props;
    const canvasRef = useRef<HTMLCanvasElement>(null);
    // Tooltip is currently disabled due to poor behavior with multiple masks
    // const tooltipRef = React.useRef<HTMLDivElement>(null);

    const [classIDImageData, setClassIDImageData] = useState<ImageData>();
    const [maskImageData, setMaskImageData] = useState<ImageData>();

    // On file load pull image data into memory
    const loadSuccess = React.useCallback(
      (directUrl: string) => {
        const tempCanvas = document.createElement('canvas');
        tempCanvas.width = props.mediaSize.width;
        tempCanvas.height = props.mediaSize.height;
        const ctx = tempCanvas.getContext('2d');
        if (ctx == null) {
          throw new Error("Can't get context in Segmentation Mask");
        }

        const img = new Image(props.mediaSize.width, props.mediaSize.height);
        // Load Results into image data so we can read the values
        // in memory
        img.onload = () => {
          ctx?.drawImage(img, 0, 0);
          const imageData = ctx.getImageData(
            0,
            0,
            props.mediaSize.width,
            props.mediaSize.height
          );
          setClassIDImageData(imageData);
        };
        img.crossOrigin = 'Anonymous';
        img.src = directUrl;
      },
      [props.mediaSize.width, props.mediaSize.height]
    );

    // Use effect compares objects by reference, so when only a subset of the object
    // changes the effect won't fire
    const classStates = maskControls.classStates;

    // Transform file data into a mask image
    useEffect(() => {
      if (classIDImageData == null) {
        // Do nothing because data is not loaded
        return;
      }
      const newImageData = new ImageData(
        props.mediaSize.width,
        props.mediaSize.height
      );

      const allToggle = classStates.all ?? DEFAULT_ALL_MASK_CONTROL;

      const classColors = _.fromPairs(
        _.map(classSet.classes, (colorInfo, classID) => {
          const classToggle =
            classStates[classID] ?? DEFAULT_CLASS_MASK_CONTROL;
          const a =
            allToggle.disabled || classToggle.disabled
              ? 0
              : allToggle.opacity * classToggle.opacity * 255;
          return [classID, [...Color.colorFromString(colorInfo.color), a]];
        })
      );

      console.time('mask render');
      // Transform class ids to a map of colors
      // Note: this is loop is slow, so minimize work here.
      for (let x = 0; x < props.mediaSize.width; x++) {
        for (let y = 0; y < props.mediaSize.height; y++) {
          const index = x * 4 + y * 4 * props.mediaSize.width;
          const classID = classIDImageData.data[index];
          const color = classColors[classID] || [128, 128, 128, 128];
          const [r, g, b, a] = color;

          newImageData.data[index] = r;
          newImageData.data[index + 1] = g;
          newImageData.data[index + 2] = b;
          newImageData.data[index + 3] = a;
        }
      }
      console.timeEnd('mask render');

      setMaskImageData(newImageData);
    }, [
      classSet.classes,
      props.mediaSize.width,
      props.mediaSize.height,
      classIDImageData,
      classStates,
    ]);

    // Draw image data
    useEffect(() => {
      if (canvasRef.current == null || maskImageData == null) {
        return;
      }
      const canvas = canvasRef.current;
      const ctx = canvas.getContext('2d');
      if (ctx == null) {
        throw new Error("Can't get context in image render");
      }
      ctx.putImageData(maskImageData, 0, 0);
    }, [maskImageData]);

    const query = File.useFileDirectUrl([filePath])[0];
    const url = query.directUrl;

    useEffect(() => {
      if (url != null) {
        loadSuccess(url);
      }
    }, [url, loadSuccess]);

    if (query.loading) {
      return <div />;
    }
    if (url == null) {
      return <div>missing</div>;
    }

    return (
      <div style={{...props.style}}>
        <canvas
          width={props.mediaSize.width}
          height={props.mediaSize.height}
          ref={canvasRef}
          style={{
            width: '100%',
            height: '100%',
          }}
        />
      </div>
    );
  },
  {id: 'SegmentationMask'}
);

const BoundingBoxes = (props: {
  style?: React.CSSProperties;
  mediaSize: {
    width: number;
    height: number;
  };
  boxData: BoundingBox2D[];
  bboxControls: Controls.BoxControlState;
  boxStyle?: React.CSSProperties;
  classSet?: {classes: {[classID: string]: {color: string; name: string}}};
}) => {
  const {mediaSize, boxData, bboxControls, classSet} = props;
  const {lineStyle, classStates} = bboxControls;
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const disabled =
    classStates.all?.disabled ?? DEFAULT_ALL_MASK_CONTROL.disabled;

  useEffect(() => {
    if (canvasRef.current) {
      const canvas = canvasRef.current;
      clearCanvas(canvas);
      for (const box of boxData) {
        const {class_id: classId} = box;
        const classState = classStates?.[classId];
        const className = classSet?.classes[classId].name;

        if (!disabled && !classState?.disabled) {
          const color = boxColor(classId);
          drawBox(
            canvas,
            box,
            className ?? `ID: ${box.class_id}`,
            mediaSize,
            color,
            {
              boxStyle: {lineStyle},
            }
          );
        }
      }
    }
  }, [
    classStates,
    classSet,
    lineStyle,
    disabled,
    boxData,
    bboxControls,
    mediaSize,
  ]);

  return (
    <div style={{...props.style}}>
      <canvas
        width={mediaSize.width}
        height={mediaSize.height}
        style={{
          width: '100%',
          height: '100%',
        }}
        ref={canvasRef}
      />
    </div>
  );
};

/**
 * Extracted and modified from ImageCard.tsx/renderBoxes
 */
export const drawBox = (
  c: HTMLCanvasElement,
  box: BoundingBox2D,
  className: string,
  mediaSize: {width: number; height: number},
  color: string,
  opts?: {boxStyle: {lineStyle: Controls.LineStyle} | undefined}
) => {
  const ctx = c.getContext('2d');

  if (ctx == null) {
    throw new Error('Canvas context not valid');
  }

  let w: number;
  let h: number;
  let x: number;
  let y: number;
  if ('minX' in box.position) {
    w = box.position.maxX - box.position.minX;
    h = box.position.maxY - box.position.minY;
    x = box.position.minX;
    y = box.position.minY;
  } else {
    w = box.position.width;
    h = box.position.height;
    x = box.position.middle[0] - w / 2;
    y = box.position.middle[1] - h / 2;
  }

  const domain = box.domain;
  if (domain === 'pixel') {
    // Do nothing
  } else {
    const {width, height} = mediaSize;
    x *= width;
    y *= height;
    w *= width;
    h *= height;
  }

  // Draw the 2D Box
  const lineWidth = 3;
  ctx.lineWidth = lineWidth;
  if (opts?.boxStyle?.lineStyle != null) {
    ctx.setLineDash(lineDashArray(opts.boxStyle.lineStyle));
  }
  ctx.strokeStyle = color;
  ctx.strokeRect(x, y, w, h);

  // Draw the label
  const {box_caption} = box;
  const labelHeight = 14;
  ctx.font = '14px Arial';
  const labelPad = 4;

  const text = box_caption ?? className;
  const tm = ctx.measureText(text);
  // If label doesn't fit draw from right edge instead of left
  const labelShift = tm.width + x > c.width ? w - tm.width - labelPad : 0;
  // Label background
  ctx.fillStyle = color;
  ctx.fillRect(
    x - lineWidth / 2 + labelShift,
    y - labelHeight - 2 * labelPad,
    tm.width + labelPad * 2,
    labelHeight + 2 * labelPad
  );

  // Text
  ctx.fillStyle = 'white';
  ctx.fillText(text, x + labelPad + labelShift, y - labelPad);
};
