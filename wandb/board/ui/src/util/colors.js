import Color from 'color';
import {COLORS} from './constants';

export function color(index, alpha = 0.8) {
  return Color(COLORS[index % COLORS.length])
    .alpha(alpha)
    .rgbString();
}
