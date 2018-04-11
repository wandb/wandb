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

// Got this list from a cool site http://tools.medialab.sciences-po.fr/iwanthue/
// First five are locked from demian
export const COLORS10 = [
  '#ecbb33',
  '#55565b',
  '#007faf',
  '#c1433c',
  '#3d9e3e',
  '#936ccb',
  '#b08342',
  '#65cca6',
  '#cb5b95',
  '#b2ce63',
];

// If we wanted to use 20 colors...

export const COLORS20 = [
  '#ecbb33',
  '#55565b',
  '#007faf',
  '#c1433c',
  '#3d9e3e',
  '#825fd3',
  '#9ad858',
  '#d23f74',
  '#6adbb5',
  '#c44bad',
  '#478955',
  '#d68fd3',
  '#de7333',
  '#6e8ddc',
  '#a16234',
  '#7e599e',
  '#c0ce73',
  '#c86c7e',
  '#807f2e',
  '#daa865',
];

export const MAX_HISTORIES_LOADED = 10;
