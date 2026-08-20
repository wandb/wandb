use arrow::array::{ArrayRef, Float64Array, Int64Array, RecordBatch, StringArray, StructArray};
use arrow::datatypes::{DataType, Field, Fields, Schema};
use arrow_rs_wrapper::*;
use parquet::arrow::ArrowWriter;
use parquet::file::properties::WriterProperties;
use std::ffi::{CStr, CString};
use std::fs::File;
use std::sync::Arc;
use tempfile::TempDir;

mod common;

const STEP_COLUMN_NAME: &str = "_step";

/// Parsed row from the binary KV wire format.
struct ParsedRow {
    columns: Vec<(String, KvValue)>,
}

#[derive(Debug, PartialEq)]
enum KvValue {
    Null,
    Int64(i64),
    Uint64(u64),
    Float64(f64),
    String(String),
    Bool(bool),
    Binary(Vec<u8>),
    List(Vec<KvValue>),
    Map(Vec<(String, KvValue)>),
}

/// Parse the binary KV wire format returned by reader_scan_step_range.
fn parse_kv_binary(data: &[u8]) -> Vec<ParsedRow> {
    if data.is_empty() {
        return Vec::new();
    }

    let mut offset = 0;

    let num_columns = read_u32(data, &mut offset) as usize;

    let mut column_names = Vec::with_capacity(num_columns);
    for _ in 0..num_columns {
        let name_len = read_u32(data, &mut offset) as usize;
        let name = std::str::from_utf8(&data[offset..offset + name_len])
            .unwrap()
            .to_string();
        offset += name_len;
        column_names.push(name);
    }

    let num_rows = read_u32(data, &mut offset) as usize;

    let mut rows = Vec::with_capacity(num_rows);
    for _ in 0..num_rows {
        let mut columns = Vec::with_capacity(num_columns);
        for col_name in &column_names {
            let value = read_kv_value(data, &mut offset);
            columns.push((col_name.clone(), value));
        }
        rows.push(ParsedRow { columns });
    }

    assert_eq!(offset, data.len(), "Did not consume all bytes");
    rows
}

fn read_u32(data: &[u8], offset: &mut usize) -> u32 {
    let v = u32::from_le_bytes(data[*offset..*offset + 4].try_into().unwrap());
    *offset += 4;
    v
}

fn read_kv_value(data: &[u8], offset: &mut usize) -> KvValue {
    let tag = data[*offset];
    *offset += 1;

    match tag {
        0 => KvValue::Null,
        1 => {
            let v = i64::from_le_bytes(data[*offset..*offset + 8].try_into().unwrap());
            *offset += 8;
            KvValue::Int64(v)
        }
        2 => {
            let v = u64::from_le_bytes(data[*offset..*offset + 8].try_into().unwrap());
            *offset += 8;
            KvValue::Uint64(v)
        }
        3 => {
            let v = f64::from_le_bytes(data[*offset..*offset + 8].try_into().unwrap());
            *offset += 8;
            KvValue::Float64(v)
        }
        4 => {
            let len = read_u32(data, offset) as usize;
            let s = std::str::from_utf8(&data[*offset..*offset + len])
                .unwrap()
                .to_string();
            *offset += len;
            KvValue::String(s)
        }
        5 => {
            let v = data[*offset] != 0;
            *offset += 1;
            KvValue::Bool(v)
        }
        6 => {
            let len = read_u32(data, offset) as usize;
            let v = data[*offset..*offset + len].to_vec();
            *offset += len;
            KvValue::Binary(v)
        }
        7 => {
            let len = read_u32(data, offset) as usize;
            let mut values = Vec::with_capacity(len);
            for _ in 0..len {
                values.push(read_kv_value(data, offset));
            }
            KvValue::List(values)
        }
        8 => {
            let len = read_u32(data, offset) as usize;
            let mut entries = Vec::with_capacity(len);
            for _ in 0..len {
                let key_len = read_u32(data, offset) as usize;
                let key = std::str::from_utf8(&data[*offset..*offset + key_len])
                    .unwrap()
                    .to_string();
                *offset += key_len;
                entries.push((key, read_kv_value(data, offset)));
            }
            KvValue::Map(entries)
        }
        _ => panic!("Unknown tag: {tag}"),
    }
}

/// Helper to extract step values from parsed rows.
fn extract_step_values(rows: &[ParsedRow]) -> Vec<i64> {
    rows.iter()
        .map(|row| {
            for (name, val) in &row.columns {
                if name == STEP_COLUMN_NAME {
                    if let KvValue::Int64(v) = val {
                        return *v;
                    }
                }
            }
            panic!("_step column not found");
        })
        .collect()
}

/// Helper to extract all column values from parsed rows.
fn extract_all_columns(rows: &[ParsedRow]) -> (Vec<i64>, Vec<i64>, Vec<String>) {
    let mut step_values = Vec::new();
    let mut int_values = Vec::new();
    let mut string_values = Vec::new();

    for row in rows {
        for (name, val) in &row.columns {
            match name.as_str() {
                "_step" => {
                    if let KvValue::Int64(v) = val {
                        step_values.push(*v);
                    }
                }
                "value" => {
                    if let KvValue::Int64(v) = val {
                        int_values.push(*v);
                    }
                }
                "name" => {
                    if let KvValue::String(s) = val {
                        string_values.push(s.clone());
                    }
                }
                _ => {}
            }
        }
    }

    (step_values, int_values, string_values)
}

/// Helper to parse scan result into rows.
fn parse_result(result: &StepScanResult) -> Vec<ParsedRow> {
    let data_slice = unsafe {
        std::slice::from_raw_parts(result.data_ptr as *const u8, result.data_len as usize)
    };
    parse_kv_binary(data_slice)
}

/// Helper function to create a test parquet file with step column
fn create_test_parquet_file(path: &str, num_rows: usize) -> std::io::Result<()> {
    let schema = Arc::new(Schema::new(vec![
        Field::new(STEP_COLUMN_NAME, DataType::Int64, false),
        Field::new("value", DataType::Int64, false),
        Field::new("name", DataType::Utf8, false),
    ]));

    let file = File::create(path)?;
    let props = WriterProperties::builder().build();
    let mut writer =
        ArrowWriter::try_new(file, schema.clone(), Some(props)).map_err(std::io::Error::other)?;

    let step_values: Vec<i64> = (0..num_rows).map(|i| i as i64).collect();
    let int_values: Vec<i64> = (0..num_rows).map(|i| (i * 10) as i64).collect();
    let string_values: Vec<&str> = (0..num_rows)
        .map(|i| if i % 2 == 0 { "even" } else { "odd" })
        .collect();

    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(Int64Array::from(step_values)),
            Arc::new(Int64Array::from(int_values)),
            Arc::new(StringArray::from(string_values)),
        ],
    )
    .map_err(std::io::Error::other)?;

    writer.write(&batch).map_err(std::io::Error::other)?;
    writer.close().map_err(std::io::Error::other)?;

    Ok(())
}

/// Creates the logical schema that Gorilla writes for selected-key scans.
fn create_gorilla_compatible_parquet_file(path: &str) -> std::io::Result<()> {
    let nested_fields = Fields::from(vec![
        Arc::new(Field::new("score", DataType::Float64, true)),
        Arc::new(Field::new("label", DataType::Utf8, true)),
    ]);
    let schema = Arc::new(Schema::new(vec![
        Field::new(STEP_COLUMN_NAME, DataType::Float64, true),
        Field::new("flat_metric", DataType::Float64, true),
        Field::new("nested", DataType::Struct(nested_fields.clone()), true),
        Field::new("unrelated", DataType::Utf8, true),
    ]));

    let nested = StructArray::new(
        nested_fields,
        vec![
            Arc::new(Float64Array::from(vec![Some(1.5), None, Some(3.5)])) as ArrayRef,
            Arc::new(StringArray::from(vec![Some("first"), Some("second"), None])) as ArrayRef,
        ],
        None,
    );
    let batch = RecordBatch::try_new(
        schema.clone(),
        vec![
            Arc::new(Float64Array::from(vec![Some(7.0), Some(8.0), Some(9.0)])),
            Arc::new(Float64Array::from(vec![Some(10.0), None, Some(30.0)])),
            Arc::new(nested),
            Arc::new(StringArray::from(vec!["omit-a", "omit-b", "omit-c"])),
        ],
    )
    .map_err(std::io::Error::other)?;

    let file = File::create(path)?;
    let props = WriterProperties::builder().build();
    let mut writer =
        ArrowWriter::try_new(file, schema, Some(props)).map_err(std::io::Error::other)?;
    writer.write(&batch).map_err(std::io::Error::other)?;
    writer.close().map_err(std::io::Error::other)?;

    Ok(())
}

fn create_float_step_parquet_file(path: &str, steps: Vec<Option<f64>>) -> std::io::Result<()> {
    let schema = Arc::new(Schema::new(vec![Field::new(
        STEP_COLUMN_NAME,
        DataType::Float64,
        true,
    )]));
    let batch = RecordBatch::try_new(schema.clone(), vec![Arc::new(Float64Array::from(steps))])
        .map_err(std::io::Error::other)?;

    let file = File::create(path)?;
    let mut writer = ArrowWriter::try_new(file, schema, None).map_err(std::io::Error::other)?;
    writer.write(&batch).map_err(std::io::Error::other)?;
    writer.close().map_err(std::io::Error::other)?;

    Ok(())
}

#[test]
fn test_create_reader() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };

    assert!(!reader_ptr.is_null());

    unsafe {
        free_reader(reader_ptr);
    }
}

#[test]
fn test_create_reader_with_columns() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let col1 = CString::new(STEP_COLUMN_NAME).unwrap();
    let col2 = CString::new("value").unwrap();
    let col_ptrs = [col1.as_ptr(), col2.as_ptr()];

    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), col_ptrs.as_ptr(), 2, &mut out_error) };

    assert!(!reader_ptr.is_null());

    unsafe {
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result) };
    assert!(error.is_null());

    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    let (step_values, int_values, string_values) = extract_all_columns(&parse_result(&result));
    assert_eq!(step_values.len(), 10);
    assert_eq!(step_values, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );
    assert_eq!(
        string_values,
        vec!["even", "odd", "even", "odd", "even", "odd", "even", "odd", "even", "odd"]
    );

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_with_columns_subset() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let col1 = CString::new(STEP_COLUMN_NAME).unwrap();
    let col2 = CString::new("value").unwrap();
    let col_ptrs = [col1.as_ptr(), col2.as_ptr()];

    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), col_ptrs.as_ptr(), 2, &mut out_error) };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result) };
    assert!(error.is_null());

    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);

    let rows = parse_result(&result);
    assert_eq!(rows.len(), 10);

    // Verify only 2 columns present
    assert_eq!(rows[0].columns.len(), 2);
    assert_eq!(rows[0].columns[0].0, "_step");
    assert_eq!(rows[0].columns[1].0, "value");

    let step_values = extract_step_values(&rows);
    assert_eq!(step_values, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);

    let int_values: Vec<i64> = rows
        .iter()
        .map(|r| {
            if let KvValue::Int64(v) = &r.columns[1].1 {
                *v
            } else {
                panic!("expected int64")
            }
        })
        .collect();
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_selected_nested_root() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("gorilla-compatible.parquet");
    create_gorilla_compatible_parquet_file(file_path.to_str().unwrap()).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let columns = [
        CString::new(STEP_COLUMN_NAME).unwrap(),
        CString::new("flat_metric").unwrap(),
        CString::new("nested").unwrap(),
    ];
    let column_pointers: Vec<_> = columns.iter().map(|column| column.as_ptr()).collect();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            column_pointers.as_ptr(),
            column_pointers.len(),
            &mut out_error,
        )
    };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error = unsafe { reader_scan_step_range(reader_ptr, 7, 9, &mut result) };
    assert!(error.is_null());

    let rows = parse_result(&result);
    assert_eq!(rows.len(), 2);
    assert_eq!(rows[0].columns.len(), 3);
    assert_eq!(rows[0].columns[0], ("_step".to_string(), KvValue::Int64(7)));
    assert_eq!(
        rows[0].columns[1],
        ("flat_metric".to_string(), KvValue::Float64(10.0))
    );
    assert_eq!(
        rows[0].columns[2],
        (
            "nested".to_string(),
            KvValue::Map(vec![
                ("score".to_string(), KvValue::Float64(1.5)),
                ("label".to_string(), KvValue::String("first".to_string())),
            ]),
        )
    );
    assert_eq!(
        rows[1].columns[2],
        (
            "nested".to_string(),
            KvValue::Map(vec![
                ("score".to_string(), KvValue::Null),
                ("label".to_string(), KvValue::String("second".to_string())),
            ]),
        )
    );
    assert!(rows
        .iter()
        .all(|row| { row.columns.iter().all(|(name, _)| name != "unrelated") }));

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_rejects_invalid_float_steps() {
    let cases = [
        ("null", vec![Some(1.0), None], "null"),
        ("fractional", vec![Some(1.0), Some(1.5)], "fractional"),
        ("negative", vec![Some(1.0), Some(-1.0)], "negative"),
        (
            "not-finite-nan",
            vec![Some(1.0), Some(f64::NAN)],
            "not finite",
        ),
        (
            "not-finite-positive-infinity",
            vec![Some(1.0), Some(f64::INFINITY)],
            "not finite",
        ),
        (
            "not-finite-negative-infinity",
            vec![Some(1.0), Some(f64::NEG_INFINITY)],
            "not finite",
        ),
        (
            "out-of-range",
            vec![Some(1.0), Some(9_223_372_036_854_775_808.0)],
            "outside the int64 range",
        ),
    ];

    for (name, steps, expected_reason) in cases {
        let temp_dir = TempDir::new().unwrap();
        let file_path = temp_dir.path().join(format!("{name}.parquet"));
        create_float_step_parquet_file(file_path.to_str().unwrap(), steps).unwrap();

        let path = CString::new(file_path.to_str().unwrap()).unwrap();
        let mut create_error: *mut libc::c_char = std::ptr::null_mut();
        let reader =
            unsafe { create_reader(path.as_ptr(), std::ptr::null(), 0, &mut create_error) };
        assert!(create_error.is_null(), "{name}: reader creation failed");
        assert!(!reader.is_null(), "{name}: reader creation failed");

        let mut result = StepScanResult {
            vec_ptr: 0,
            data_ptr: 0,
            data_len: 0,
            num_rows_returned: 0,
        };
        let scan_error = unsafe { reader_scan_step_range(reader, 0, 10, &mut result) };
        assert!(!scan_error.is_null(), "{name}: scan unexpectedly succeeded");
        let message = unsafe { CStr::from_ptr(scan_error) }
            .to_string_lossy()
            .into_owned();
        assert!(
            message.contains(&format!(
                "invalid '{STEP_COLUMN_NAME}' at row 1: {expected_reason}"
            )),
            "{name}: unexpected error: {message}"
        );

        unsafe {
            free_string(scan_error as *mut libc::c_char);
            free_reader(reader);
        }
    }
}

#[test]
fn test_reader_scan_step_range_sequential_calls() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };

    let mut result1 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error1 = unsafe { reader_scan_step_range(reader_ptr, 0, 10, &mut result1) };
    assert!(error1.is_null());
    assert_eq!(result1.num_rows_returned, 10);

    let step_values_1 = extract_step_values(&parse_result(&result1));
    assert_eq!(step_values_1, vec![0, 1, 2, 3, 4, 5, 6, 7, 8, 9]);

    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result2) };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);

    let step_values_2 = extract_step_values(&parse_result(&result2));
    assert_eq!(step_values_2, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);

    unsafe {
        free_buffer(result1.vec_ptr as *mut Vec<u8>);
        free_buffer(result2.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_backwards() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };

    let mut result1 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error1 = unsafe { reader_scan_step_range(reader_ptr, 50, 60, &mut result1) };
    assert!(error1.is_null());
    assert_eq!(result1.num_rows_returned, 10);
    let step_values_1 = extract_step_values(&parse_result(&result1));
    assert_eq!(step_values_1, vec![50, 51, 52, 53, 54, 55, 56, 57, 58, 59]);

    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result2) };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);

    let step_values_2 = extract_step_values(&parse_result(&result2));
    assert_eq!(step_values_2, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);

    unsafe {
        free_buffer(result1.vec_ptr as *mut Vec<u8>);
        free_buffer(result2.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_empty_result() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(reader_ptr, 200, 300, &mut result) };
    assert!(error.is_null());

    assert_eq!(result.num_rows_returned, 0);
    assert_eq!(result.data_len, 0);

    unsafe {
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_null_pointer() {
    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(std::ptr::null_mut(), 0, 10, &mut result) };
    assert!(!error.is_null());

    unsafe {
        free_string(error as *mut libc::c_char);
    }
}

#[test]
fn test_reader_scan_step_range_http() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();
    let (url, _counter) = common::start_http_server(file_path.to_str().unwrap());

    let url_cstring = CString::new(url.clone()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(url_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };
    if reader_ptr.is_null() {
        panic!(
            "Failed to create reader for HTTP URL: {url}. \
             This may indicate an issue with HTTP range request handling."
        );
    }

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(reader_ptr, 25, 35, &mut result) };
    assert!(error.is_null());
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);

    let (step_values, int_values, string_values) = extract_all_columns(&parse_result(&result));
    assert_eq!(step_values.len(), 10);
    assert_eq!(step_values, vec![25, 26, 27, 28, 29, 30, 31, 32, 33, 34]);
    assert_eq!(
        int_values,
        vec![250, 260, 270, 280, 290, 300, 310, 320, 330, 340]
    );
    assert_eq!(
        string_values,
        vec!["odd", "even", "odd", "even", "odd", "even", "odd", "even", "odd", "even"]
    );

    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe { reader_scan_step_range(reader_ptr, 35, 45, &mut result2) };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);
    let step_values_2 = extract_step_values(&parse_result(&result2));
    assert_eq!(step_values_2, vec![35, 36, 37, 38, 39, 40, 41, 42, 43, 44]);

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_buffer(result2.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_http_with_columns_subset() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let (url, _counter) = common::start_http_server(file_path.to_str().unwrap());
    let url_cstring = CString::new(url.clone()).unwrap();
    let col1 = CString::new(STEP_COLUMN_NAME).unwrap();
    let col2 = CString::new("value").unwrap();
    let col_ptrs = [col1.as_ptr(), col2.as_ptr()];

    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(url_cstring.as_ptr(), col_ptrs.as_ptr(), 2, &mut out_error) };
    if reader_ptr.is_null() {
        panic!("Failed to create reader for HTTP URL with columns: {url}.");
    }

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error = unsafe { reader_scan_step_range(reader_ptr, 15, 25, &mut result) };
    assert!(error.is_null());
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);

    let rows = parse_result(&result);
    assert_eq!(rows.len(), 10);
    assert_eq!(rows[0].columns.len(), 2);
    assert_eq!(rows[0].columns[0].0, "_step");
    assert_eq!(rows[0].columns[1].0, "value");

    let step_values = extract_step_values(&rows);
    assert_eq!(step_values, vec![15, 16, 17, 18, 19, 20, 21, 22, 23, 24]);

    let int_values: Vec<i64> = rows
        .iter()
        .map(|r| {
            if let KvValue::Int64(v) = &r.columns[1].1 {
                *v
            } else {
                panic!("expected int64")
            }
        })
        .collect();
    assert_eq!(
        int_values,
        vec![150, 160, 170, 180, 190, 200, 210, 220, 230, 240]
    );

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

fn create_test_parquet_file_with_int64_step(path: &str, num_rows: usize) -> std::io::Result<()> {
    let schema = Arc::new(Schema::new(vec![
        Field::new(STEP_COLUMN_NAME, DataType::Int64, false),
        Field::new("value", DataType::Int64, false),
        Field::new("name", DataType::Utf8, false),
    ]));

    let file = File::create(path)?;
    let props = WriterProperties::builder().build();
    let mut writer =
        ArrowWriter::try_new(file, schema.clone(), Some(props)).map_err(std::io::Error::other)?;

    let step_values: Vec<i64> = (0..num_rows).map(|i| i as i64).collect();
    let int_values: Vec<i64> = (0..num_rows).map(|i| (i * 10) as i64).collect();
    let string_values: Vec<&str> = (0..num_rows)
        .map(|i| if i % 2 == 0 { "even" } else { "odd" })
        .collect();

    let batch = RecordBatch::try_new(
        schema,
        vec![
            Arc::new(Int64Array::from(step_values)),
            Arc::new(Int64Array::from(int_values)),
            Arc::new(StringArray::from(string_values)),
        ],
    )
    .map_err(std::io::Error::other)?;

    writer.write(&batch).map_err(std::io::Error::other)?;
    writer.close().map_err(std::io::Error::other)?;

    Ok(())
}

#[test]
fn test_reader_scan_with_int64_step_column() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test_int64.parquet");
    create_test_parquet_file_with_int64_step(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let mut out_error: *mut libc::c_char = std::ptr::null_mut();
    let reader_ptr =
        unsafe { create_reader(path_cstring.as_ptr(), std::ptr::null(), 0, &mut out_error) };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result) };
    assert!(error.is_null());

    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);

    let (step_values, int_values, string_values) = extract_all_columns(&parse_result(&result));
    assert_eq!(step_values.len(), 10);
    assert_eq!(step_values, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );
    assert_eq!(
        string_values,
        vec!["even", "odd", "even", "odd", "even", "odd", "even", "odd", "even", "odd"]
    );

    unsafe {
        free_buffer(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}
