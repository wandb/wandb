// Adapted from Crockford's JSON.parse (see https://github.com/douglascrockford/JSON-js)
// This version adds support for NaN, -Infinity and Infinity.

(function() {
  var at, // The index of the current character
    ch, // The current character
    escapee = {
      '"': '"',
      '\\': '\\',
      '/': '/',
      b: '\b',
      f: '\f',
      n: '\n',
      r: '\r',
      t: '\t',
    },
    text,
    error = function(m) {
      throw new Error({
        name: 'SyntaxError',
        message: m,
        at: at,
        text: text,
      });
    },
    next = function(c) {
      return (ch = text.charAt(at++));
    },
    check = function(c) {
      if (c !== ch) {
        error("Expected '" + c + "' instead of '" + ch + "'");
      }
      ch = text.charAt(at++);
    },
    number = function() {
      var string = '';
      if (ch === '-') {
        string = '-';
        check('-');
      }
      if (ch === 'I') {
        check('I');
        check('n');
        check('f');
        check('i');
        check('n');
        check('i');
        check('t');
        check('y');
        return -Infinity;
      }
      while (ch >= '0' && ch <= '9') {
        string += ch;
        next();
      }
      if (ch === '.') {
        string += '.';
        while (next() && ch >= '0' && ch <= '9') {
          string += ch;
        }
      }
      if (ch === 'e' || ch === 'E') {
        string += ch;
        next();
        if (ch === '-' || ch === '+') {
          string += ch;
          next();
        }
        while (ch >= '0' && ch <= '9') {
          string += ch;
          next();
        }
      }
      return +string;
    },
    string = function() {
      var hex,
        i,
        string = '',
        uffff;
      if (ch === '"') {
        while (next()) {
          if (ch === '"') {
            next();
            return string;
          }
          if (ch === '\\') {
            next();
            if (ch === 'u') {
              uffff = 0;
              for (i = 0; i < 4; i++) {
                hex = parseInt(next(), 16);
                if (!isFinite(hex)) {
                  break;
                }
                uffff = uffff * 16 + hex;
              }
              string += String.fromCharCode(uffff);
            } else if (escapee[ch]) {
              string += escapee[ch];
            } else {
              break;
            }
          } else {
            string += ch;
          }
        }
      }
      error('Bad string');
    },
    white = function() {
      // Skip whitespace.
      while (ch && ch <= ' ') {
        next();
      }
    },
    word = function() {
      switch (ch) {
        case 't':
          check('t');
          check('r');
          check('u');
          check('e');
          return true;
        case 'f':
          check('f');
          check('a');
          check('l');
          check('s');
          check('e');
          return false;
        case 'n':
          check('n');
          check('u');
          check('l');
          check('l');
          return null;
        case 'N':
          check('N');
          check('a');
          check('N');
          return NaN;
        case 'I':
          check('I');
          check('n');
          check('f');
          check('i');
          check('n');
          check('i');
          check('t');
          check('y');
          return Infinity;
        default:
          error("Unexpected '" + ch + "'");
      }
    },
    array = function() {
      var array = [];
      if (ch === '[') {
        check('[');
        white();
        if (ch === ']') {
          check(']');
          return array; // empty array
        }
        while (ch) {
          array.push(value());
          white();
          if (ch === ']') {
            check(']');
            return array;
          }
          check(',');
          white();
        }
      }
      error('Bad array');
    },
    object = function() {
      var key,
        object = {};
      if (ch === '{') {
        check('{');
        white();
        if (ch === '}') {
          check('}');
          return object; // empty object
        }
        while (ch) {
          key = string();
          white();
          check(':');
          if (Object.hasOwnProperty.call(object, key)) {
            error('Duplicate key "' + key + '"');
          }
          object[key] = value();
          white();
          if (ch === '}') {
            check('}');
            return object;
          }
          check(',');
          white();
        }
      }
      error('Bad object');
    };
  var value = function() {
    white();
    switch (ch) {
      case '{':
        return object();
      case '[':
        return array();
      case '"':
        return string();
      case '-':
        return number();
      default:
        return ch >= '0' && ch <= '9' ? number() : word();
    }
  };

  JSON.parseMore = function(source, reviver) {
    var result;
    text = source;
    at = 0;
    ch = ' ';
    result = value();
    white();
    if (ch) {
      error('Syntax error');
    }
    return typeof reviver === 'function'
      ? (function walk(holder, key) {
          var k,
            v,
            value = holder[key];
          if (value && typeof value === 'object') {
            for (k in value) {
              if (Object.prototype.hasOwnProperty.call(value, k)) {
                v = walk(value, k);
                if (v !== undefined) {
                  value[k] = v;
                } else {
                  delete value[k];
                }
              }
            }
          }
          return reviver.call(holder, key, value);
        })({'': result}, '')
      : result;
  };
})();
