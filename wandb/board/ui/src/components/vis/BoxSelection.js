// Based on https://raw.githubusercontent.com/uber/react-vis/master/showcase/examples/zoomable-chart/highlight.js

import React from 'react';
import {ScaleUtils, AbstractSeries} from 'react-vis';
import _ from 'lodash';
import {
  registerMouseUpListener,
  unregisterMouseUpListener,
} from '../../util/mouse';

export default class BoxSelection extends AbstractSeries {
  static displayName = 'BoxSelection';
  static defaultProps = {
    allow: 'x',
    color: 'rgb(77, 182, 172)',
    opacity: 0.3,
  };
  state = {
    drawing: false,
    drawArea: {top: 0, right: 0, bottom: 0, left: 0},
    startLoc: {x: 0, y: 0},
  };

  _getDrawArea(loc) {
    const {innerWidth, innerHeight} = this.props;
    const {drawArea, startLoc} = this.state;

    let area = {
      top: Math.max(0, Math.min(startLoc.y, loc.y)),
      bottom: Math.min(innerHeight, Math.max(startLoc.y, loc.y)),
      left: Math.max(0, Math.min(startLoc.x, loc.x)),
      right: Math.min(innerWidth, Math.max(startLoc.x, loc.x)),
    };
    return area;
  }

  componentDidMount() {
    this.mouseUpListener = registerMouseUpListener(() => this.stopDrawing());
  }

  componentWillUnmount() {
    unregisterMouseUpListener(this.mouseUpListener);
  }

  onParentMouseDown(e) {
    const {marginLeft, marginTop, onBrushStart} = this.props;
    const locX = e.nativeEvent.offsetX - marginLeft;
    const locY = e.nativeEvent.offsetY - marginTop;

    this.setState({
      drawing: true,
      drawArea: {
        top: locY,
        right: locX,
        bottom: locY,
        left: locX,
      },
      startLoc: {x: locX, y: locY},
    });

    if (onBrushStart) {
      onBrushStart(e);
    }
  }

  stopDrawing() {
    // Quickly short-circuit if the user isn't drawing in our component
    if (!this.state.drawing) {
      return;
    }

    const {marginLeft, marginTop, onSelectChange} = this.props;
    const {drawArea} = this.state;
    const xScale = ScaleUtils.getAttributeScale(this.props, 'x');
    const yScale = ScaleUtils.getAttributeScale(this.props, 'y');

    this.setState({
      drawing: false,
    });

    if (drawArea.right - drawArea.left + drawArea.bottom - drawArea.top < 5) {
      // Clear selection
      onSelectChange({low: null, high: null}, {low: null, high: null});
      return;
    }

    // Compute the corresponding domain drawn
    const domainArea = {
      top: yScale.invert(drawArea.top),
      right: xScale.invert(drawArea.right),
      bottom: yScale.invert(drawArea.bottom),
      left: xScale.invert(drawArea.left),
    };

    if (onSelectChange) {
      const xScale = ScaleUtils.getAttributeScale(this.props, 'x');
      const yScale = ScaleUtils.getAttributeScale(this.props, 'y');
      const xSelect = {
        low: domainArea.left,
        high: domainArea.right,
      };
      const ySelect = {
        high: domainArea.top,
        low: domainArea.bottom,
      };
      onSelectChange(xSelect, ySelect);
    }
  }

  onParentMouseMove(e) {
    const {marginLeft, marginTop, onSelectChange} = this.props;
    const {drawing} = this.state;
    const locX = e.nativeEvent.offsetX - marginLeft;
    const locY = e.nativeEvent.offsetY - marginTop;

    if (drawing) {
      const newDrawArea = this._getDrawArea({x: locX, y: locY});
      this.setState({drawArea: newDrawArea});
    }
  }

  componentWillReceiveProps(nextProps) {
    //console.log('boxselection willreceiveprops', nextProps, nextProps);
    if (
      !nextProps.xSelect.low &&
      !nextProps.xSelect.high &&
      !nextProps.ySelect.low &&
      !nextProps.ySelect.high
    ) {
      // If none of our axes have selections, don't highlight.
      this.setState({
        drawArea: {left: 0, right: 0, top: 0, bottom: 0},
      });
      return;
    }
    const xScale = ScaleUtils.getAttributeScale(nextProps, 'x');
    const yScale = ScaleUtils.getAttributeScale(nextProps, 'y');
    let left = nextProps.xSelect.low ? xScale(nextProps.xSelect.low) : 0;
    let right = nextProps.xSelect.high
      ? xScale(nextProps.xSelect.high)
      : nextProps.innerWidth;
    let top = nextProps.ySelect.high ? yScale(nextProps.ySelect.high) : 0;
    let bottom = nextProps.ySelect.low
      ? yScale(nextProps.ySelect.low)
      : nextProps.innerHeight;
    this.setState({
      drawArea: {left: left, right: right, top: top, bottom: bottom},
    });
  }

  render() {
    const {
      marginLeft,
      marginTop,
      innerWidth,
      innerHeight,
      color,
      opacity,
    } = this.props;
    if (innerWidth < 0 || innerHeight < 0) {
      return null;
    }

    let {left, right, top, bottom} = this.state.drawArea;

    return (
      <g
        transform={`translate(${marginLeft}, ${marginTop})`}
        className="highlight-container"
        onMouseUp={e => this.stopDrawing()}>
        <rect
          className="mouse-target"
          fill="black"
          opacity="0"
          x={0}
          y={0}
          width={innerWidth}
          height={innerHeight}
        />
        <rect
          className="highlight"
          pointerEvents="none"
          opacity={opacity}
          fill={color}
          x={left}
          y={top}
          width={right - left}
          height={bottom - top}
        />
      </g>
    );
  }
}
