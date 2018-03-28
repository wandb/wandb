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
