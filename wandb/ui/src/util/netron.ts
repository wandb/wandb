import * as _ from 'lodash';

export const EXTENSIONS: string[] = [];

function register(id: string, extensions: string[]) {
  for (const e of extensions) {
    EXTENSIONS.push(e);
  }
}

// This code is taken from src/public/netron/view.js
// Note: I commented out common file extensions (json and zip) so we don't try
//   to load them
register('./onnx', ['.onnx', '.pb', '.pbtxt', '.prototxt']);
register('./mxnet', ['.mar', '.model', /* '.json',*/ '.params']);
register('./keras', ['.h5', '.hd5', '.hdf5', '.keras' /*'.json',*/, '.model']);
register('./coreml', ['.mlmodel']);
register('./caffe', ['.caffemodel', '.pbtxt', '.prototxt', '.pt']);
register('./caffe2', ['.pb', '.pbtxt', '.prototxt']);
register('./pytorch', [
  '.pt',
  '.pth',
  '.pt1',
  '.pkl',
  '.h5',
  '.t7',
  '.model',
  '.dms',
  '.pth.tar',
  '.ckpt',
  '.bin',
]);
register('./torch', ['.t7']);
register('./tflite', ['.tflite', '.lite', '.tfl', '.bin']);
register('./tf', [
  '.pb',
  '.meta',
  '.pbtxt',
  '.prototxt',
  // '.json',
  '.index',
  '.ckpt',
]);
register('./sklearn', ['.pkl', '.joblib', '.model']);
register('./cntk', ['.model', '.cntk', '.cmf', '.dnn']);
register('./paddle', ['.paddle', '__model__']);
register('./armnn', ['.armnn']);
register('./bigdl', ['.model', '.bigdl']);
register('./darknet', ['.cfg']);
register('./mnn', ['.mnn']);
register('./ncnn', ['.param', '.bin', '.cfg.ncnn', '.weights.ncnn']);
// register('./openvino', ['.xml', '.bin']);
register('./flux', ['.bson']);
register('./chainer', ['.npz', '.h5', '.hd5', '.hdf5']);
// register('./dl4j', ['.zip']);
// register('./mlnet', ['.zip']);

export function isViewable(fname: string) {
  const extension = '.' + fname.split('.').pop();
  return _.includes(EXTENSIONS, extension);
}
