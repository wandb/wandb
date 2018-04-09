import React from 'react';
import {ScaleUtils, AbstractSeries} from 'react-vis';

export default class Highlight extends AbstractSeries {
  static displayName = 'HighlightOverlay';
  static defaultProps = {
    allow: 'x',
    color: 'rgb(77, 182, 172)',
    opacity: 0.3,
  };
  state = {
    drawing: false,
    drawArea: {top: 0, right: 0, bottom: 0, left: 0},
    startLoc: 0,
  };

  _getDrawArea(loc) {
    const {innerWidth} = this.props;
    const {drawArea, startLoc} = this.state;

    if (loc < startLoc) {
      return {
        ...drawArea,
        left: Math.max(loc, 0),
        right: startLoc,
      };
    }

    return {
      ...drawArea,
      right: Math.min(loc, innerWidth),
      left: startLoc,
    };
  }

  onParentMouseDown(e) {
    const {marginLeft, innerHeight, onBrushStart} = this.props;
    let offsetX = e.nativeEvent.offsetX;
    if (e.nativeEvent.type === 'touchstart') {
      offsetX = e.nativeEvent.pageX;
    }
    const location = offsetX - marginLeft;

    // TODO: Eventually support drawing as a full rectangle, if desired. Currently the code supports 'x' only
    this.setState({
      drawing: true,
      drawArea: {
        top: 0,
        right: location,
        bottom: innerHeight,
        left: location,
      },
      startLoc: location,
    });

    if (onBrushStart) {
      onBrushStart(e);
    }
  }

  onParentTouchStart(e) {
    e.preventDefault();
    this.onParentMouseDown(e);
  }

  stopDrawing() {
    // Quickly short-circuit if the user isn't drawing in our component
    if (!this.state.drawing) {
      return;
    }

    const {onBrushEnd} = this.props;
    const {drawArea} = this.state;
    const xScale = ScaleUtils.getAttributeScale(this.props, 'x');
    const yScale = ScaleUtils.getAttributeScale(this.props, 'y');

    // Clear the draw area
    this.setState({
      drawing: false,
      drawArea: {top: 0, right: 0, bottom: 0, left: 0},
      startLoc: 0,
    });

    // Invoke the callback with null if the selected area was < 5px
    if (Math.abs(drawArea.right - drawArea.left) < 5) {
      onBrushEnd(null);
      return;
    }

    // Compute the corresponding domain drawn
    const domainArea = {
      top: yScale.invert(drawArea.top),
      right: xScale.invert(drawArea.right),
      bottom: yScale.invert(drawArea.bottom),
      left: xScale.invert(drawArea.left),
    };

    if (onBrushEnd) {
      onBrushEnd(domainArea);
    }
  }

  onParentMouseMove(e) {
    const {marginLeft, onBrush} = this.props;
    const {drawing} = this.state;
    let offsetX = e.nativeEvent.offsetX;
    if (e.nativeEvent.type === 'touchmove') {
      offsetX = e.nativeEvent.pageX;
    }
    const loc = offsetX - marginLeft;

    if (drawing) {
      const newDrawArea = this._getDrawArea(loc);
      this.setState({drawArea: newDrawArea});

      if (onBrush) {
        onBrush(e);
      }
    }
  }

  onParentTouchMove(e) {
    e.preventDefault();
    this.onParentMouseMove(e);
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
    const {drawArea: {left, right, top, bottom}} = this.state;

    return (
      <g
        transform={`translate(${marginLeft}, ${marginTop})`}
        className="highlight-container"
        onMouseUp={() => this.stopDrawing()}
        onMouseLeave={() => this.stopDrawing()}
        // preventDefault() so that mouse event emulation does not happen
        onTouchEnd={e => {
          e.preventDefault();
          this.stopDrawing();
        }}
        onTouchCancel={e => {
          e.preventDefault();
          this.stopDrawing();
        }}>
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
          height={bottom}
        />
      </g>
    );
  }
}
