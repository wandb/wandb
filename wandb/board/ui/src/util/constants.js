export const FRAMEWORKS = [
  'keras',
  'tensorflow',
  'caffe',
  'theano',
  'torch',
  'scikit',
  'other',
];
export const frameworkOptions = e => {
  return FRAMEWORKS.map(e => {
    return {
      text: e[0].toUpperCase() + e.slice(1),
      value: e,
    };
  });
};
export const PERMISSIONS = [];
export const COLORS = [
  '#0074D9', // BLUE
  '#FF851B', // ORANGE
  '#001f3f', // NAVY
  '#FF4136', // RED
  '#3D9970', // OLIVE
  '#FFDC00', // YELLOW
  '#7FDBFF', // AQUA
  '#B10DC9', // PURPLE
  '#39CCCC', // TEAL
  '#85144b', // MAROON
  '#2ECC40', // GREEN
  '#01FF70', // LIME
  '#F012BE', // FUCHSIA
  '#fbbd08', // orange
  '#f2711c', // red
  '#b5cc18', // pukegreen
  '#21ba45', // green
  '#00b5ad', // bluegreen
  '#2185d0', // blue
];

export const MAX_HISTORIES_LOADED = 10;
