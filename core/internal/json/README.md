This package is based on `github.com/segmentio/encoding@v0.4.0` with a patched `parse.go` file.

Diff:

```
298a299,311
>       // Check for NaN and ±Inf
>       if len(b) >= 3 {
>               switch string(b[:3]) {
>               case "NaN":
>                       return []byte("\"NaN\""), b[3:], String, nil
>               case "Inf":
>                       return []byte("\"Infinity\""), b[8:], String, nil
>               }
>       }
>       if len(b) >= 4 && string(b[:4]) == "-Inf" {
>               return []byte("\"-Infinity\""), b[9:], String, nil
>       }
>
721c734
<       case '-', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9':
---
>       case '-', '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', 'N', 'I':
```
