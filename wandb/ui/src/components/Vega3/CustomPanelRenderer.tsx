import * as S from './CustomPanelRenderer.styles';

import React from 'react';
import {useRef} from 'react';
import * as _ from 'lodash';
import * as VegaCommon from '../../util/vegaCommon';
import {transforms, View as VegaView} from 'vega';
import {Vega, VisualizationSpec} from 'react-vega';
import Measure, {BoundingRect} from 'react-measure';
import PanelError from '../elements/PanelError';
import WandbLoader from '../WandbLoader';
import Rasterize from './Rasterize';
import makeComp from '../../util/profiler';

transforms.rasterize = Rasterize as any;

export interface Row {
  [key: string]: any;
}

interface CustomPanelRendererProps {
  spec: VisualizationSpec;
  loading: boolean;
  slow: boolean;
  data: Row[];
  userSettings: VegaCommon.UserSettings;
  customRunColors?: {[key: string]: string};
  setView?(view: VegaView | null): void;
}

const CustomPanelRenderer: React.FC<CustomPanelRendererProps> = makeComp(
  props => {
    const [dimensions, setDimensions] = React.useState<BoundingRect>();
    const [vegaView, setVegaView] = React.useState<VegaView>();
    const [error, setError] = React.useState<Error>();
    const [showBindings, setShowBindings] = React.useState(false);

    const elRef = useRef<Element>();

    const onError = React.useCallback((e: Error) => {
      setError(e);
    }, []);

    const onNewView = React.useCallback(
      (v: VegaView) => {
        (window as any).VIEW = v;
        setError(undefined);
        setVegaView(v);
        props.setView?.(v);
      },
      [props.setView]
    );

    if (_.isEmpty(props.spec)) {
      // TODO(john): More specific parse errors
      return (
        <S.Wrapper>
          <PanelError
            className="severe"
            message="Error: Unable to parse spec"></PanelError>
        </S.Wrapper>
      );
    }

    const hasBindings = VegaCommon.specHasBindings(props.spec);

    const fieldRefs = VegaCommon.parseSpecFields(props.spec);
    const specWithFields = VegaCommon.injectFields(
      props.spec,
      fieldRefs,
      props.userSettings
    );

    let width: number;
    let height: number;

    if (dimensions && vegaView) {
      const padding = vegaView.padding() as any;
      width = dimensions.width - padding.left - padding.right;
      height = dimensions.height - padding.top - padding.bottom;
    }

    specWithFields.autosize = 'fit';

    return (
      <Measure
        bounds
        innerRef={ref => {
          if (ref != null) {
            elRef.current = ref;
          }
        }}
        onResize={contentRect => {
          // Performance hack. Opening the semantic modal may add or remove a
          // scrollbar to the document body. This causes a re-layout, and and
          // all panels to resize. Vega panels can be very expensive to resize,
          // so we skip the resize if we're in the background when a modal is
          // open.
          if (dimensions == null) {
            setDimensions(contentRect.bounds);
          } else {
            setTimeout(() => {
              if (elRef.current != null) {
                if (elRef.current.closest('.dimmer') != null) {
                  setDimensions(contentRect.bounds);
                } else {
                  if (document.querySelector('body.dimmed') == null) {
                    setDimensions(contentRect.bounds);
                  }
                }
              }
            }, 100);
          }
        }}>
        {({measureRef}) => {
          return (
            <S.Wrapper ref={measureRef} showBindings={showBindings}>
              <Vega
                width={width}
                height={height}
                spec={specWithFields}
                data={{wandb: props.data}}
                actions={false}
                onError={onError}
                onNewView={onNewView}
              />
              {props.loading &&
                (props.slow ? (
                  <PanelError
                    message={
                      <>
                        <WandbLoader />
                        <div className="slow-message">
                          This chart is loading very slowly. Change your query
                          to fetch less data.
                        </div>
                      </>
                    }
                  />
                ) : (
                  <WandbLoader />
                ))}
              {!props.loading && props.data.length === 0 && (
                <PanelError message="No data available."></PanelError>
              )}
              {error && (
                <PanelError
                  message={error.name + ': ' + error.message}></PanelError>
              )}
              {hasBindings && (
                <S.ToggleBindingsButton
                  name={showBindings ? 'close' : 'configuration'}
                  onClick={() =>
                    setShowBindings(s => !s)
                  }></S.ToggleBindingsButton>
              )}
            </S.Wrapper>
          );
        }}
      </Measure>
    );
  },
  {id: 'CustomPanelRenderer'}
);

export default CustomPanelRenderer;
