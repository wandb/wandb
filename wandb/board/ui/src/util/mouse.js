import _ from 'lodash';

let upListenerId = 0;
let upListeners = {};

export function mouseListenersStart() {
  document.addEventListener('mouseup', e => {
    for (var listener of _.values(upListeners)) {
      listener(e);
    }
  });
}

export function registerMouseUpListener(fn) {
  let id = upListenerId;
  upListenerId++;
  upListeners[id] = fn;
  return id;
}

export function unregisterMouseUpListener(id) {
  if (upListeners[id]) {
    delete upListeners[id];
  }
}
