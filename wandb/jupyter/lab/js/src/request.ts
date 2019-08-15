/**
 * This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/.
 */
export interface IRequestOptions {
  ignoreCache?: boolean;
  headers?: {[key: string]: string};
  // 0 (or negative) to wait forever
  timeout?: number;
}

export const DEFAULT_REQUEST_OPTIONS = {
  headers: {
    Accept: "application/json, text/javascript, text/plain",
  },
  ignoreCache: false,
  // default max duration for a request
  timeout: 5000,
};

export interface IRequestResult {
  ok: boolean;
  status: number;
  statusText: string;
  data: string;
  json: <T>() => T;
  headers: string;
  url: string;
}

function queryParams(params: any = {}) {
  return Object.keys(params)
      .map((k) => encodeURIComponent(k) + "=" + encodeURIComponent(params[k]))
      .join("&");
}

function withQuery(url: string, params: any = {}) {
  const queryString = queryParams(params);
  return queryString ? url + (url.indexOf("?") === -1 ? "?" : "&") + queryString : url;
}

function parseXHRResult(xhr: XMLHttpRequest): IRequestResult {
  return {
    data: xhr.responseText,
    headers: xhr.getAllResponseHeaders(),
    json: <T>() => JSON.parse(xhr.responseText) as T,
    ok: xhr.status >= 200 && xhr.status < 300,
    status: xhr.status,
    statusText: xhr.statusText,
    url: xhr.responseURL,
  };
}

function errorResponse(xhr: XMLHttpRequest, message: string | null = null): IRequestResult {
  return {
    data: message || xhr.statusText,
    headers: xhr.getAllResponseHeaders(),
    json: <T>() => JSON.parse(message || xhr.statusText) as T,
    ok: false,
    status: xhr.status,
    statusText: xhr.statusText,
    url: xhr.responseURL,
  };
}

export function request(method: "get" | "post",
                        url: string,
                        queryParamsOther: any = {},
                        body: any = null,
                        options: IRequestOptions = DEFAULT_REQUEST_OPTIONS) {
    const ignoreCache = options.ignoreCache || DEFAULT_REQUEST_OPTIONS.ignoreCache;
    const headers = options.headers || DEFAULT_REQUEST_OPTIONS.headers;
    const timeout = options.timeout || DEFAULT_REQUEST_OPTIONS.timeout;

    return new Promise<IRequestResult>((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(method, withQuery(url, queryParamsOther));

    if (headers) {
      Object.keys(headers).forEach((key) => xhr.setRequestHeader(key, headers[key]));
    }

    if (ignoreCache) {
      xhr.setRequestHeader("Cache-Control", "no-cache");
    }

    xhr.timeout = timeout;

    xhr.onload = (evt) => {
      resolve(parseXHRResult(xhr));
    };

    xhr.onerror = (evt) => {
      resolve(errorResponse(xhr, "Failed to make request."));
    };

    xhr.ontimeout = (evt) => {
      resolve(errorResponse(xhr, "Request took longer than expected."));
    };

    if (method === "post" && body) {
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(JSON.stringify(body));
    } else {
      xhr.send();
    }
  });
}
