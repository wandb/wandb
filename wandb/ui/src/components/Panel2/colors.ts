/*
Resources on colour palettes

Generates qualitative palettes
http://tools.medialab.sciences-po.fr/iwanthue/

Nice properties for colourmaps to have (from matplotlib).
https://matplotlib.org/users/colormaps.html#colorcet (linear_bgy_10_95_c74_n256)
https://bids.github.io/colormap/

And a palette generator from Google
http://google.github.io/palette.js/
*/

import Color from 'color';

export function colorN(index: number, palette: string[], alpha?: number) {
  /**
   * Given an index and a palette, returns a color.
   */
  const c = Color(palette[index % palette.length]);
  return c
    .alpha(alpha || c.alpha())
    .rgb()
    .string();
}

export function colorFromString(s: string): [number, number, number] {
  return Color(s)
    .rgb()
    .array() as [number, number, number];
}

export const COLORS16 = [
  '#E87B9F', // pink
  '#A12864', // maroon
  '#DA4C4C', // red
  '#F0B899', // peach
  '#E57439', // orange
  '#EDB732', // yellow
  '#A0C75C', // lime
  '#479A5F', // kelly green
  '#87CEBF', // seafoam
  '#229487', // forest
  '#5BC5DB', // cyan
  '#5387DD', // blue
  '#7D54B2', // purple
  '#C565C7', // magenta
  '#A46750', // brown
  '#A1A9AD', // gray
];

const namesOfColors: {[key: string]: string} = {
  '#E87B9F': 'pink',
  '#A12864': 'maroon',
  '#DA4C4C': 'red',
  '#F0B899': 'peach',
  '#E57439': 'orange',
  '#EDB732': 'yellow',
  '#A0C75C': 'lime',
  '#479A5F': 'kelly green',
  '#87CEBF': 'seafoam',
  '#229487': 'forest',
  '#5BC5DB': 'cyan',
  '#5387DD': 'blue',
  '#7D54B2': 'purple',
  '#C565C7': 'magenta',
  '#A46750': 'brown',
  '#A1A9AD': 'gray',
};

// Our bespoke palette. This is in round-robin order.
export const ROBIN16 = [
  11, // blue
  2, // red
  7, // kelly green
  12, // purple
  0, // pink
  4, // orange
  8, // seafoam
  13, // magenta
  5, // yellow
  10, // cyan
  9, // forest
  3, // peach
  6, // lime
  14, // brown
  1, // maroon
  15, // gray
].map(i => COLORS16[i]);
