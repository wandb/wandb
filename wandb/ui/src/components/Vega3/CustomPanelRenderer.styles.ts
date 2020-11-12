import styled, {css} from 'styled-components';
// import {GLOBAL_COLORS} from '../../util/colors';
import WBIcon from '../elements/WBIcon';
import Color from 'color';

export const GLOBAL_COLORS = {
  primary: Color('#007faf'),
  outline: Color('rgb(219, 219, 219)'),
  linkBlue: Color('#007faf'),
};

export const Wrapper = styled.div<{showBindings?: boolean}>`
  width: 100%;
  height: 100%;
  position: relative;
  .vega-embed {
    display: block;
    canvas {
      display: block;
    }
  }
  .panel-error {
    position: absolute;
    top: 0;
    width: 100%;
    background: rgba(255, 255, 255, 0.85);
    .slow-message {
      margin-top: calc(3.625rem + 2 * 36px);
    }
  }
  .vega-bindings {
    position: absolute;
    top: 0;
    left: 0;
    background: white;
    padding: 8px 12px;
    border: 1px solid ${GLOBAL_COLORS.outline.toString()};
    width: 100%;
    .vega-bind-name {
      display: inline-block;
      width: 120px;
    }
    .vega-bind input[type='range'] {
      width: 120px;
      margin-right: 4px;
      vertical-align: middle;
    }
    .vega-bind input[type='radio'] {
      margin-right: 4px;
    }
    .vega-bind-radio label {
      margin-right: 8px;
    }
    .vega-bind select {
      max-width: 200px;
    }
  }
  ${props =>
    !props.showBindings &&
    css`
      .vega-bindings {
        display: none;
      }
    `}
`;

export const ToggleBindingsButton = styled(WBIcon)`
  position: absolute;
  top: 8px;
  right: 8px;
  z-index: 10;
  color: #666;
  cursor: pointer;
  background: rgba(255, 255, 255, 0.6);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  font-size: 20px;
  &:hover {
    color: ${GLOBAL_COLORS.linkBlue.toString()};
    background: white;
  }
`;
