use arrow::array::{Int64Array, RecordBatch, StringArray};
use arrow::datatypes::{DataType, Field, Schema};
use arrow::ipc::reader::StreamReader;
use arrow_rs_wrapper::*;
use parquet::arrow::ArrowWriter;
use parquet::file::properties::WriterProperties;
use std::ffi::CString;
use std::fs::File;
use std::sync::Arc;
use tempfile::TempDir;

mod common;

const STEP_COLUMN_NAME: &str = "_step";

/// Helper function to read IPC stream and extract step values
fn read_step_values_from_result(result: &StepScanResult) -> Vec<i64> {
    let data_slice = unsafe {
        std::slice::from_raw_parts(
            result.data_ptr as *const u8,
            result.data_len as usize,
        )
    };

    let cursor = std::io::Cursor::new(data_slice);
    let mut stream_reader = StreamReader::try_new(cursor, None).unwrap();

    let mut step_values = Vec::new();
    while let Some(Ok(batch)) = stream_reader.next() {
        let step_col = batch
            .column(batch.schema().index_of(STEP_COLUMN_NAME).unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        for i in 0..batch.num_rows() {
            step_values.push(step_col.value(i));
        }
    }

    step_values
}

/// Helper function to read IPC stream and extract all column values
fn read_all_columns_from_result(result: &StepScanResult) -> (Vec<i64>, Vec<i64>, Vec<String>) {
    let data_slice = unsafe {
        std::slice::from_raw_parts(
            result.data_ptr as *const u8,
            result.data_len as usize,
        )
    };

    let cursor = std::io::Cursor::new(data_slice);
    let mut stream_reader = StreamReader::try_new(cursor, None).unwrap();

    let mut step_values = Vec::new();
    let mut int_values = Vec::new();
    let mut string_values = Vec::new();

    while let Some(Ok(batch)) = stream_reader.next() {
        let step_col = batch
            .column(batch.schema().index_of("_step").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        let value_col = batch
            .column(batch.schema().index_of("value").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        let name_col = batch
            .column(batch.schema().index_of("name").unwrap())
            .as_any()
            .downcast_ref::<StringArray>()
            .unwrap();

        for i in 0..batch.num_rows() {
            step_values.push(step_col.value(i));
            int_values.push(value_col.value(i));
            string_values.push(name_col.value(i).to_string());
        }
    }

    (step_values, int_values, string_values)
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
    let mut writer = ArrowWriter::try_new(file, schema.clone(), Some(props))
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    // Create a batch with sequential step values
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
    .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    writer
        .write(&batch)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
    writer
        .close()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    Ok(())
}

#[test]
fn test_create_reader() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };

    assert!(!reader_ptr.is_null());

    // Cleanup
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
    let col_ptrs = vec![col1.as_ptr(), col2.as_ptr()];

    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            col_ptrs.as_ptr(),
            2,
        )
    };

    assert!(!reader_ptr.is_null());

    // Cleanup
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
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    // Scan steps 10-20 (exclusive)
    let error = unsafe {
        reader_scan_step_range(
            reader_ptr,
            10, // min step
            20, // max step
            &mut result,
        )
    };
    assert!(error.is_null());

    // Should return 10 rows (steps 10-19)
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    // Verify the response data
    let (
        step_values,
        int_values,
        string_values
    ) = read_all_columns_from_result(&result);
    assert_eq!(step_values.len(), 10);
    assert_eq!(
        step_values,
        vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    );
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );
    assert_eq!(
        string_values,
        vec![
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd"
        ]
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_with_columns_subset() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    // Create reader with only _step and value columns (no name column)
    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let col1 = CString::new(STEP_COLUMN_NAME).unwrap();
    let col2 = CString::new("value").unwrap();
    let col_ptrs = vec![col1.as_ptr(), col2.as_ptr()];

    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            col_ptrs.as_ptr(),
            2,
        )
    };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe {
        reader_scan_step_range(
            reader_ptr,
            10, // min step
            20, // max step
            &mut result,
        )
    };
    assert!(error.is_null());

    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    let data_slice = unsafe {
        std::slice::from_raw_parts(
            result.data_ptr as *const u8,
            result.data_len as usize,
        )
    };

    let cursor = std::io::Cursor::new(data_slice);
    let mut stream_reader = StreamReader::try_new(cursor, None).unwrap();
    let mut step_values = Vec::new();
    let mut int_values = Vec::new();

    while let Some(Ok(batch)) = stream_reader.next() {
        assert_eq!(batch.schema().fields().len(), 2);
        assert!(batch.schema().index_of("_step").is_ok());
        assert!(batch.schema().index_of("value").is_ok());
        // Verify name column is NOT present
        assert!(batch.schema().index_of("name").is_err());

        let step_col = batch
            .column(batch.schema().index_of("_step").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        let value_col = batch
            .column(batch.schema().index_of("value").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        for i in 0..batch.num_rows() {
            step_values.push(step_col.value(i));
            int_values.push(value_col.value(i));
        }
    }
    assert_eq!(step_values.len(), 10);
    assert_eq!(
        step_values,
        vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    );
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_sequential_calls() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };

    // First call: scan steps 0-10
    let mut result1 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error1 = unsafe { reader_scan_step_range(reader_ptr, 0, 10, &mut result1) };
    assert!(error1.is_null());
    assert_eq!(result1.num_rows_returned, 10);

    // Verify first result contains steps 0-9
    let step_values_1 = read_step_values_from_result(&result1);
    assert_eq!(
        step_values_1,
        vec![0, 1, 2, 3, 4, 5, 6, 7, 8, 9],
    );

    // Second call: scan steps 10-20 (should continue from where we left off)
    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result2) };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);

    // Verify second result contains steps 10-19
    let step_values_2 = read_step_values_from_result(&result2);
    assert_eq!(
        step_values_2,
        vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19],
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result1.vec_ptr as *mut Vec<u8>);
        free_ipc_stream(result2.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_backwards() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };

    let mut result1 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error1 = unsafe { reader_scan_step_range(reader_ptr, 50, 60, &mut result1) };
    assert!(error1.is_null());
    assert_eq!(result1.num_rows_returned, 10);
    let step_values_1 = read_step_values_from_result(&result1);
    assert_eq!(
        step_values_1,
        vec![50, 51, 52, 53, 54, 55, 56, 57, 58, 59],
    );

    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe { reader_scan_step_range(reader_ptr, 10, 20, &mut result2) };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);

    // Verify we got the correct steps after going backwards
    let step_values_2 = read_step_values_from_result(&result2);
    assert_eq!(step_values_2, vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]);

    // Cleanup
    unsafe {
        free_ipc_stream(result1.vec_ptr as *mut Vec<u8>);
        free_ipc_stream(result2.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

#[test]
fn test_reader_scan_step_range_empty_result() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    // Scan beyond available data
    let error = unsafe { reader_scan_step_range(reader_ptr, 200, 300, &mut result) };
    assert!(error.is_null());

    // Should return 0 rows
    assert_eq!(result.num_rows_returned, 0);
    assert_eq!(result.data_len, 0);

    // Cleanup
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

    // Cleanup error string
    unsafe {
        free_string(error as *mut libc::c_char);
    }
}

// Integration test for reading Parquet files over HTTP
#[test]
fn test_reader_scan_step_range_http() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test.parquet");
    create_test_parquet_file(file_path.to_str().unwrap(), 100).unwrap();
    let (url, _counter) = common::start_http_server(file_path.to_str().unwrap());

    let url_cstring = CString::new(url.clone()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            url_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };
    if reader_ptr.is_null() {
        panic!("Failed to create reader for HTTP URL: {}. \
                This may indicate an issue with HTTP range request handling.", url);
    }

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    let error = unsafe {
        reader_scan_step_range(
            reader_ptr,
            25,
            35,
            &mut result,
        )
    };
    assert!(error.is_null());
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    let (step_values, int_values, string_values) = read_all_columns_from_result(&result);
    assert_eq!(step_values.len(), 10);
    assert_eq!(
        step_values,
        vec![25, 26, 27, 28, 29, 30, 31, 32, 33, 34]
    );
    assert_eq!(
        int_values,
        vec![250, 260, 270, 280, 290, 300, 310, 320, 330, 340]
    );
    assert_eq!(
        string_values,
        vec![
            "odd", "even", "odd", "even", "odd",
            "even", "odd", "even", "odd", "even"
        ]
    );

    let mut result2 = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error2 = unsafe {
        reader_scan_step_range(
            reader_ptr,
            35,
            45,
            &mut result2,
        )
    };
    assert!(error2.is_null());
    assert_eq!(result2.num_rows_returned, 10);
    let step_values_2 = read_step_values_from_result(&result2);
    assert_eq!(
        step_values_2,
        vec![35, 36, 37, 38, 39, 40, 41, 42, 43, 44]
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result.vec_ptr as *mut Vec<u8>);
        free_ipc_stream(result2.vec_ptr as *mut Vec<u8>);
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
    let col_ptrs = vec![col1.as_ptr(), col2.as_ptr()];

    let reader_ptr = unsafe {
        create_reader(
            url_cstring.as_ptr(),
            col_ptrs.as_ptr(),
            2,
        )
    };
    if reader_ptr.is_null() {
        panic!("Failed to create reader for HTTP URL with columns: {}. \
                This may indicate an issue with HTTP range request handling.", url);
    }

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };
    let error = unsafe {
        reader_scan_step_range(
            reader_ptr,
            15,
            25,
            &mut result,
        )
    };
    assert!(error.is_null());
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    let data_slice = unsafe {
        std::slice::from_raw_parts(
            result.data_ptr as *const u8,
            result.data_len as usize,
        )
    };
    let cursor = std::io::Cursor::new(data_slice);
    let mut stream_reader = StreamReader::try_new(cursor, None).unwrap();
    let mut step_values = Vec::new();
    let mut int_values = Vec::new();

    while let Some(Ok(batch)) = stream_reader.next() {
        assert_eq!(batch.schema().fields().len(), 2);
        assert!(batch.schema().index_of("_step").is_ok());
        assert!(batch.schema().index_of("value").is_ok());
        // Verify name column is NOT present
        assert!(batch.schema().index_of("name").is_err());

        let step_col = batch
            .column(batch.schema().index_of("_step").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        let value_col = batch
            .column(batch.schema().index_of("value").unwrap())
            .as_any()
            .downcast_ref::<Int64Array>()
            .unwrap();

        for i in 0..batch.num_rows() {
            step_values.push(step_col.value(i));
            int_values.push(value_col.value(i));
        }
    }

    assert_eq!(step_values.len(), 10);
    assert_eq!(
        step_values,
        vec![15, 16, 17, 18, 19, 20, 21, 22, 23, 24]
    );
    assert_eq!(
        int_values,
        vec![150, 160, 170, 180, 190, 200, 210, 220, 230, 240]
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}

/// Helper function to create a test parquet file with Int64 step column
fn create_test_parquet_file_with_int64_step(path: &str, num_rows: usize) -> std::io::Result<()> {
    let schema = Arc::new(Schema::new(vec![
        Field::new(STEP_COLUMN_NAME, DataType::Int64, false),
        Field::new("value", DataType::Int64, false),
        Field::new("name", DataType::Utf8, false),
    ]));

    let file = File::create(path)?;
    let props = WriterProperties::builder().build();
    let mut writer = ArrowWriter::try_new(file, schema.clone(), Some(props))
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    // Create a batch with sequential step values as Int64
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
    .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    writer
        .write(&batch)
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;
    writer
        .close()
        .map_err(|e| std::io::Error::new(std::io::ErrorKind::Other, e))?;

    Ok(())
}

#[test]
fn test_reader_scan_with_int64_step_column() {
    let temp_dir = TempDir::new().unwrap();
    let file_path = temp_dir.path().join("test_int64.parquet");
    create_test_parquet_file_with_int64_step(file_path.to_str().unwrap(), 100).unwrap();

    let path_cstring = CString::new(file_path.to_str().unwrap()).unwrap();
    let reader_ptr = unsafe {
        create_reader(
            path_cstring.as_ptr(),
            std::ptr::null(),
            0,
        )
    };
    assert!(!reader_ptr.is_null());

    let mut result = StepScanResult {
        vec_ptr: 0,
        data_ptr: 0,
        data_len: 0,
        num_rows_returned: 0,
    };

    // Scan steps 10-20 (exclusive)
    let error = unsafe {
        reader_scan_step_range(
            reader_ptr,
            10, // min step
            20, // max step
            &mut result,
        )
    };
    assert!(error.is_null());

    // Should return 10 rows (steps 10-19)
    assert_eq!(result.num_rows_returned, 10);
    assert!(result.data_len > 0);
    assert!(result.vec_ptr != 0);

    // Verify the response data
    let (
        step_values,
        int_values,
        string_values
    ) = read_all_columns_from_result(&result);
    assert_eq!(step_values.len(), 10);
    assert_eq!(
        step_values,
        vec![10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
    );
    assert_eq!(
        int_values,
        vec![100, 110, 120, 130, 140, 150, 160, 170, 180, 190]
    );
    assert_eq!(
        string_values,
        vec![
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd",
            "even",
            "odd"
        ]
    );

    // Cleanup
    unsafe {
        free_ipc_stream(result.vec_ptr as *mut Vec<u8>);
        free_reader(reader_ptr);
    }
}
