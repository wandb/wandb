import * as _ from 'lodash';
import {useRef, useState, useEffect} from 'react';

// From https://usehooks.com/useOnScreen/
export function useOnScreen(
  domRef: React.MutableRefObject<Element | null>,
  rootMargin: string = '0px'
) {
  // State and setter for storing whether element is visible
  const [isIntersecting, setIntersecting] = useState(false);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        // Update our state when observer callback fires
        setIntersecting(entry.isIntersecting);
      },
      {
        rootMargin,
      }
    );
    const domRefValue = domRef.current;
    if (domRefValue) {
      observer.observe(domRefValue);
    }
    return () => {
      if (domRefValue) {
        observer.unobserve(domRefValue);
      }
    };
  }, [domRef, rootMargin]); // Empty array ensures that effect is only run on mount and unmount

  return isIntersecting;
}

/* Returns true after a ref is on screen for the first time */
export function useWaitToLoadTilOnScreen(
  domRef: React.MutableRefObject<Element | null>
) {
  const elementPageYOffset = domRef.current
    ? (window.pageYOffset || document.documentElement.scrollTop) +
      domRef.current.getBoundingClientRect().top
    : null;
  // Always load content near the top of the page immediately.
  const isAboveFold =
    elementPageYOffset != null ? elementPageYOffset < 1000 : false;
  const [hasRendered, setHasRendered] = useState(false);
  const onScreenTimer = useRef<ReturnType<typeof setTimeout> | undefined>();
  const isOnScreen = useOnScreen(domRef, '300px');

  useEffect(() => {
    if (hasRendered) {
      return;
    }
    if (isAboveFold) {
      setHasRendered(true);
    }
    if (!onScreenTimer.current && isOnScreen) {
      onScreenTimer.current = setTimeout(() => {
        setHasRendered(true);
      }, 200);
    } else if (onScreenTimer.current && !isOnScreen) {
      clearTimeout(onScreenTimer.current);
      onScreenTimer.current = undefined;
    }
  }, [hasRendered, isAboveFold, isOnScreen]);

  if (hasRendered) {
    return true;
  }

  return false;
}

// From stackoverflow
export const usePrevious = <T extends any>(value: T) => {
  const ref = useRef<T>();
  useEffect(() => {
    ref.current = value;
  });
  return ref.current;
};

// Only return a new value if value changes by deep-comparison
// from one call to the next.
export const useDeepMemo = <T extends any>(value: T) => {
  const ref = useRef<T>();
  const prev = usePrevious(value);
  if (!_.isEqual(value, prev)) {
    ref.current = value;
  }
  return ref.current as T;
};

export const useGatedValue = <T extends any>(
  value: T,
  updateWhen: (val: T) => boolean
) => {
  const ref = useRef<T>(value);
  if (value !== ref.current && updateWhen(value)) {
    ref.current = value;
  }
  return ref.current;
};
