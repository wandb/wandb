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

/*
@primaryColor : #007FAF;  // blue
@secondaryColor: #7A7B7E; // gray
@yellow: #ECBB33;
@red: #C1433C;
@green: #3D9E3E;
@blue: #007FAF;
@darkgray: #55565B;
@gray: #7A7B7E;
@lightgray: #B3B3B0;
@verylightgray: #DDDDDA;
*/

// Got this list from a cool site http://tools.medialab.sciences-po.fr/iwanthue/
// First five are locked from demian
// Try to make them lighter towards the end so they fade a little into white background
export const COLORS10 = [
  '#df672a',
  '#007faf',
  '#c1433c',
  '#3d9e3e',
  '#c99d06',
  '#926ccb',
  '#6bb59b',
  '#ad825c',
  '#c66b9e',
  '#a7b756',
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
