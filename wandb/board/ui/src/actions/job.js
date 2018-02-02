export const UPDATE_JOB = 'UPDATE_JOB';

export const updateJob = id => {
  return {
    type: UPDATE_JOB,
    id,
  };
};
