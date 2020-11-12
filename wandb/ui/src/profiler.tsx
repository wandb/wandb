import { PropsWithChildren, ReactElement } from 'react';

// This is copied straight from React.FC but excludes the additional properties like displayName.
// We need to isolate the function call signature because otherwise TypeScript higher-order type inference breaks.
// See https://github.com/microsoft/TypeScript/pull/30215#issue-258109340
// Specifically, this is one of the requirements for it to work:
// "the called function is a generic function that returns a function type with a single call signature"
type FC<P = {}> = (
  props: PropsWithChildren<P>,
  context?: any
) => ReactElement<any, any> | null;

type PropsAreEqual<T> = (
  prevProps: Readonly<PropsWithChildren<T>>,
  nextProps: Readonly<PropsWithChildren<T>>
) => boolean;

interface MakeCompOpts<T> {
  id: string;
  memo?: true | PropsAreEqual<T>;
  disableProfiler?: true;
}

const makeComp = <T,>(
  Comp: FC<T>,
  {id, memo, disableProfiler}: MakeCompOpts<T>
): FC<T> => {

  return Comp;
};

export default makeComp;
