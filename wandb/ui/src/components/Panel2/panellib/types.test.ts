import * as Types from './types';

const handlers = [
  {inputType: 'string' as const, id: 'string1'},
  {inputType: 'number' as const, id: 'number1'},
  {
    inputType: {
      type: 'column' as const,
      objectType: 'number' as const,
    },
    id: 'array-number1',
  },
  {
    inputType: {
      type: 'row' as const,
      objectType: {
        type: 'column' as const,
        objectType: 'number' as const,
      },
    },
    id: 'dict-array-number1',
  },
];

describe('availablePanels', () => {
  it('simple type', () => {
    const result = Types.getTypeHandlerStacks('string', handlers, []);
    expect(result).toEqual([{inputType: 'string', id: 'string1'}]);
  });

  it('nested type', () => {
    const result = Types.getTypeHandlerStacks(
      {type: 'column', objectType: 'number'},
      handlers,
      []
    );
    expect(result).toEqual([
      {
        id: 'array-number1',
        inputType: {
          objectType: 'number',
          type: 'column',
        },
      },
    ]);
  });

  it('double nested', () => {
    const result = Types.getTypeHandlerStacks(
      {
        type: 'row',
        objectType: {type: 'column', objectType: 'number'},
      },
      handlers,
      []
    );
    expect(result).toEqual([
      {
        inputType: {
          type: 'row',
          objectType: {
            type: 'column',
            objectType: 'number',
          },
        },
        id: 'dict-array-number1',
      },
    ]);
  });

  it('query converter', () => {
    const converter = {
      id: 'query-conv1',
      convert: (inputType: Types.Type) =>
        !Types.isSimpleType(inputType) && inputType.type === 'query'
          ? inputType.resultType
          : null,
    };
    const result = Types.getTypeHandlerStacks(
      {
        type: 'query',
        resultType: {
          type: 'row',
          objectType: {type: 'column', objectType: 'number'},
        },
      },
      handlers,
      [converter]
    );
    expect(result).toEqual([
      {
        ...converter,
        inputType: {
          type: 'query',
          resultType: {
            type: 'row',
            objectType: {
              type: 'column',
              objectType: 'number',
            },
          },
        },
        child: {
          inputType: {
            type: 'row',
            objectType: {
              type: 'column',
              objectType: 'number',
            },
          },
          id: 'dict-array-number1',
        },
      },
    ]);
  });
});
