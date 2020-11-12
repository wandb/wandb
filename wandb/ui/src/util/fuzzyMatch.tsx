/*
Very commonly used things for fuzzy searching

"Fuzzy" usually means the results have to have all the letters from the query
in the same order but might have other characters interspersed among them.

There's also stuff in here for highlighting results of such searches.
*/

import React from 'react';
import _ from 'lodash';

export function fuzzyMatchRegex(matchStr: string): RegExp {
  let regexpStr = '';
  for (let i = 0; i < matchStr.length; i++) {
    /**
     * The search string can contain characters regexes treat specially, so
     * escape each character before adding it to the fuzzy regex.
     */
    regexpStr += escapeRegExp(matchStr.substring(i, i + 1));
    regexpStr += '.*';
  }
  return new RegExp(regexpStr, 'i');
}

export function unfuzzRegex(regex: string): string {
  return regex
    .replace(/\.\*/g, '')
    .replace(/\\([-[\]{}()*+?.,\\^$|#\s])/g, '$1');
}

function escapeRegExp(text: string) {
  return text.replace(/[-[\]{}()*+?.,\\^$|#\s]/g, '\\$&');
}

function indexMap(list: string): {[id: string]: number[]} {
  /**
   *  For longestCommonSubstring, from
   * From https://github.com/mirkokiefer/longest-common-substring/blob/master/index.js
   */
  const map: {[id: string]: number[]} = {};
  _.forEach(list, (each, i) => {
    map[each] = map[each] || [];
    map[each].push(i);
  });
  return map;
}

interface LongestCommonSubstringReturn {
  startString1: number;
  startString2: number;
  length: number;
}

function longestCommonSubstring(
  seq1: string,
  seq2: string
): LongestCommonSubstringReturn {
  const result = {startString1: 0, startString2: 0, length: 0};
  const indexMapBefore = indexMap(seq1);
  let previousOverlap: any[] = [];
  _.forEach(seq2, (eachAfter, indexAfter: any) => {
    let overlapLength;
    const overlap: any[] = [];
    const indexesBefore = indexMapBefore[eachAfter] || [];
    indexesBefore.forEach((indexBefore: any) => {
      overlapLength =
        ((indexBefore && previousOverlap[indexBefore - 1]) || 0) + 1;
      if (overlapLength > result.length) {
        result.length = overlapLength;
        result.startString1 = indexBefore - overlapLength + 1;
        result.startString2 = indexAfter - overlapLength + 1;
      }
      overlap[indexBefore] = overlapLength;
    });
    previousOverlap = overlap;
  });
  return result;
}

export function fuzzyMatchScore(str: string, matchStr: string): number {
  return longestCommonSubstring(str, matchStr).length;
}

export function fuzzyMatchWithMapping<T>(
  objs: T[],
  matchStr: string | null,
  strFunc: (o: T) => string
): T[] {
  if (!matchStr) {
    return objs;
  }
  const matchedStrs = objs.filter(o =>
    strFunc(o).match(fuzzyMatchRegex(matchStr))
  );
  const scoredObjs = matchedStrs.map(o => {
    return {
      obj: o,
      score: -1 * fuzzyMatchScore(strFunc(o), matchStr),
    };
  });
  const sortedScores = _.sortBy(scoredObjs, ['score']);
  return preferExactMatch(
    sortedScores.map(ss => ss.obj),
    matchStr,
    strFunc
  );
}

export function fuzzyMatch(strs: string[], matchStr: string | null): string[] {
  return fuzzyMatchWithMapping(strs, matchStr, o => o);
}

/**
 * Splits a fuzzy search result for highlighting
 *
 * Splits `str` into pieces. Even-numbered indices don't match the query.
 * Odd-numbered indices are part of the matching subsequence.
 *
 * This function assumes that there is a (non-contiguous) match for `query`
 * in `str`.
 *
 * str: the string in which to perform the search
 * query: the query string to highlight within str
 */
export function fuzzyMatchSplit(str: string, query: string): string[] {
  const strLower = str.toLowerCase();
  const queryLower = query.toLowerCase();
  const pieces = [];
  let strI = 0;
  for (let queryI = 0; strI < str.length && queryI < query.length; ) {
    const nonMatchStartI = strI;
    for (; strI < str.length; strI++) {
      if (queryLower[queryI] === strLower[strI]) {
        break;
      }
    }
    pieces.push(str.substring(nonMatchStartI, strI));

    const matchStartI = strI;
    for (; strI < str.length; strI++, queryI++) {
      if (queryLower[queryI] !== strLower[strI]) {
        break;
      }
    }

    pieces.push(str.substring(matchStartI, strI));
  }

  // there may be another non-matching piece at the end
  if (strI < str.length) {
    pieces.push(str.substring(strI));
  }

  return pieces;
}

/*
Fuzzy match for two fields at once
*/
export function fuzzyComponentSplit(
  [a, b]: [string, string],
  query: string
): [string[], string[]] {
  // we subdivide pieces into the parts that come from `a` and `b`
  const pieces = fuzzyMatchSplit(a + b, query);
  const aPieces = [];
  const bPieces = [];

  let accLength = 0; // length of pieces we've accumulated so far
  let piecesI = 0;
  for (; accLength < a.length; ) {
    const piece = pieces[piecesI];

    if (accLength + piece.length <= a.length) {
      piecesI += 1;
      accLength += piece.length;
      aPieces.push(piece);
    } else {
      aPieces.push(piece.substring(0, a.length - accLength));
      break; // we must have reached the end of `a`
    }
  }

  if (piecesI % 2) {
    // pieces[piecesI] should be highlighted, so add an empty unhighlighted piece at the beginning
    bPieces.push('');
  }
  bPieces.push(pieces[piecesI].substring(a.length - accLength));
  for (piecesI++; piecesI < pieces.length; piecesI++) {
    bPieces.push(pieces[piecesI]);
  }

  return [aPieces, bPieces];
}

export function fuzzyMatchHighlightPieces(
  strPieces: string[],
  matchStyle: {[key: string]: string} = {fontWeight: 'bold'}
): React.ReactFragment {
  if (strPieces.length === 1) {
    return strPieces[0];
  } else {
    return (
      <>
        {strPieces.map((s, i) => {
          if (i % 2) {
            return (
              <span key={i} className="fuzzy-match" style={matchStyle}>
                {s}
              </span>
            );
          } else {
            return <span key={i}>{s}</span>;
          }
        })}
      </>
    );
  }
}

/**
 * fuzzyMatchHighlight works with fuzzyMatch to highlight the earliest matching subsequence
 * str: the string to highlight
 * matchStr: the query string to highlight within str
 */
export function fuzzyMatchHighlight(
  str: string,
  query: string,
  matchStyle: {[key: string]: string} = {fontWeight: 'bold'}
): React.ReactFragment {
  return fuzzyMatchHighlightPieces(fuzzyMatchSplit(str, query), matchStyle);
}

export function preferExactMatch<T>(
  objs: T[],
  matchStr: string,
  strFn = (o: T) => (typeof o === 'string' ? o : JSON.stringify(o))
) {
  return _.sortBy(objs, o =>
    strFn(o).toLowerCase() === matchStr.toLowerCase() ? 0 : 1
  );
}
