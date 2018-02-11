export const UPDATE_LOCATION_PARAMS = 'UPDATE_LOCATION_PARAMS';

export const updateLocationParams = params => {
  return {
    type: UPDATE_LOCATION_PARAMS,
    params,
  };
};
