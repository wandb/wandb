import {rgb} from 'd3-color';
import {Transform} from 'vega-dataflow';
import {inherits} from 'vega-util';
import {canvas} from 'vega-canvas';

/**
 * Converts pixel data into a canvas bitmap.
 */
export default function Rasterize(params) {
  Transform.call(this, [], params);
}

Rasterize.Definition = {
  type: 'Rasterize',
  metadata: {generates: true},
  params: [
    {name: 'x', type: 'field', required: true},
    {name: 'y', type: 'field', required: true},
    {name: 'color', type: 'expr', required: true},
    {name: 'width', type: 'number'},
    {name: 'height', type: 'number'},
    {name: 'as', type: 'string'},
  ],
};

var prototype = inherits(Rasterize, Transform);

prototype.transform = function(_, pulse) {
  if (!pulse.source.length) {
    return pulse;
  }
  var out = pulse.fork(pulse.NO_SOURCE),
    x = _.x,
    y = _.y,
    color = _.color,
    as = _.as || 'image',
    width = _.width,
    height = _.height;

  // remove any previous results
  out.rem = this.value;

  const arr = [];
  let maxX = 0;
  let maxY = 0;

  // generate canvas
  pulse.visit(pulse.SOURCE, function(t) {
    const tx = x(t),
      ty = y(t);
    if (tx > maxX) {
      maxX = tx;
    }
    if (ty > maxY) {
      maxY = ty;
    }
    arr.push(t);
  });
  const cw = width || maxX + 1;
  const ch = height || maxY + 1;
  const can = canvas(cw, ch);
  const ctx = can.getContext('2d');
  const img = ctx.getImageData(0, 0, cw, ch);
  const pix = img.data;
  pix[0] = 255;
  pix[1] = 0;
  pix[2] = 0;
  pix[3] = 255;
  arr.forEach(t => {
    const col = rgb(color(t, _));
    const i = (y(t) * cw + x(t)) * 4;
    pix[i] = col.r;
    pix[i + 1] = col.g;
    pix[i + 2] = col.b;
    pix[i + 3] = 255;
  });
  ctx.putImageData(img, 0, 0);

  out.add.push({[as]: can});

  this.value = out.source = out.add;
  return out.modifies(as);
};
