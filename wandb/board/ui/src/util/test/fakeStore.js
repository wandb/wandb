const fakeStore = state => {
  return {
    default: () => {},
    subscribe: () => {},
    dispatch: jest.fn(),
    getState: () => {
      return {...state};
    },
  };
};
export default fakeStore;
