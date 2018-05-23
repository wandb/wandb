import Enzyme, {shallow, render, mount} from 'enzyme';
import Adapter from 'enzyme-adapter-react-16';
import sinon from 'sinon';
import configureStore from 'redux-mock-store';

Enzyme.configure({adapter: new Adapter()});

// TODO: replace it with jest-localstorage-mock
const localStorageMock = {
  getItem: jest.fn(),
  setItem: jest.fn(),
  clear: jest.fn(),
};

global.sinon = sinon;
global.shallow = shallow;
global.render = render;
global.mount = mount;
global.mockStore = configureStore();
global.localStorage = localStorageMock;

///// From react-slick test-setup.js
window.matchMedia =
  window.matchMedia ||
  function() {
    return {
      matches: false,
      addListener: function() {},
      removeListener: function() {},
    };
  };

window.requestAnimationFrame =
  window.requestAnimationFrame ||
  function(callback) {
    setTimeout(callback, 0);
  };

///// End react-slick test-setup.js
