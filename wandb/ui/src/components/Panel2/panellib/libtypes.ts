export interface TypedInputHandler<T> {
  inputType: T;
}

export interface TypedInputConverter<T> {
  // TODO: This is a combination of type filter and converter. We could
  // have an inputType for the filtering part (we need more generic types
  // since inputType isn't concrete for these)
  convert(inputType: T): T | null;
}

export type TypedInputHandlerStack<
  T,
  H extends TypedInputHandler<T>,
  C extends TypedInputConverter<T>
> = H | (C & {inputType: T; child: TypedInputHandlerStack<T, H, C>});

export function _getTypeHandlerStacks<
  T,
  H extends TypedInputHandler<T>,
  C extends TypedInputConverter<T>
>(
  currentType: T,
  handlers: H[],
  converters: C[],
  typesMatch: (type: T, fitType: T) => boolean
) {
  let result: Array<TypedInputHandlerStack<T, H, C>> = handlers.filter(ps =>
    typesMatch(currentType, ps.inputType)
  );

  for (const converter of converters) {
    const convertedType = converter.convert(currentType);
    if (convertedType != null) {
      result = result.concat(
        _getTypeHandlerStacks(
          convertedType,
          handlers,
          converters,
          typesMatch
        ).map(handler => ({
          ...converter,
          inputType: currentType,
          child: handler,
        }))
      );
    }
  }

  return result;
}
