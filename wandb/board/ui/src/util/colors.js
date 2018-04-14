import Color from 'color';
import {COLORS10, COLORS20} from './constants';

export function color(index, alpha = 0.8) {
  return Color(COLORS10[index % COLORS10.length])
    .alpha(alpha)
    .rgbString();
}

export function color20(index, alpha = 0.8) {
  return Color(COLORS20[index % COLORS20.length])
    .alpha(alpha)
    .rgbString();
}
