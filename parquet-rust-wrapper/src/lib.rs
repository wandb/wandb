use arrow::ipc::writer::StreamWriter;
use std::ffi::{CStr, CString};
use std::fs::File;
use parquet::arrow::arrow_reader::{ParquetRecordBatchReader, ParquetRecordBatchReaderBuilder};
use parquet::arrow::ProjectionMask;
use arrow::array::{Array, Float64Array, Int64Array, RecordBatch};

mod httpfile;
pub use httpfile::HttpFileReader;  // Export for testing

const STEP_COLUMN_NAME: &str = "_step";

/// ReaderHandles is used to maintain the state of a parquet reader.
pub struct ReaderHandle {
    reader: ParquetRecordBatchReader, // The arrow reader of the parquet file

    column_names: Option<Vec<String>>, // The column names to read from the parquet file
    current_batch_row_offset: usize, // The row offset within the current batch
    current_batch: Option<RecordBatch>, // The current record batch being read
    file_path: String,            // The file path of the parquet file
    last_step_returned: f64,      // Track the last step value we returned
    reader_exhausted: bool,       // Track if reader reached end of file
}

/// Create a new parquet reader with optional column selection
///
/// Returns a pointer to a ReaderHandle on success, or null on failure.
/// Use `get_last_error()` to retrieve error message if null is returned.
///
/// # Safety
///
/// This function is unsafe because it dereferences raw pointers
#[no_mangle]
pub unsafe extern "C" fn create_reader(
    file_path_or_url: *const libc::c_char,
    column_names: *const *const libc::c_char,
    num_columns: usize,
) -> *mut ReaderHandle {
    // Convert the file path from C string to Rust string
    let file_path_cstr = unsafe { CStr::from_ptr(file_path_or_url) };
    let file_path_str = match file_path_cstr.to_str() {
        Ok(s) => s,
        Err(_) => {
            return std::ptr::null_mut();
        }
    };

    // Convert column names from C strings to Rust strings
    let col_names = if num_columns > 0 && !column_names.is_null() {
        let mut names = Vec::with_capacity(num_columns);
        for i in 0..num_columns {
            let col_name_ptr = unsafe { *column_names.add(i) };
            if col_name_ptr.is_null() {
                return std::ptr::null_mut();
            }
            let col_name_cstr = unsafe { CStr::from_ptr(col_name_ptr) };
            match col_name_cstr.to_str() {
                Ok(s) => names.push(s.to_string()),
                Err(_) => {
                    return std::ptr::null_mut();
                }
            }
        }
        Some(names)
    } else {
        None
    };

    // Create the reader
    match create_reader_internal(file_path_str, col_names.as_deref()) {
        Ok(handle) => Box::into_raw(Box::new(handle)),
        Err(_) => {
            std::ptr::null_mut()
        }
    }
}

fn create_reader_internal(
    file_path: &str,
    column_names: Option<&[String]>,
) -> Result<ReaderHandle, String> {
    // Check if it's a URL or local file
    let is_url = file_path.starts_with("http://") || file_path.starts_with("https://");

    let reader = if is_url {
        // HTTP reader
        let http_reader = HttpFileReader::new(file_path.to_string())
            .map_err(|e| format!("Failed to create HTTP reader: {}", e))?;

        let builder = ParquetRecordBatchReaderBuilder::try_new(http_reader)
            .map_err(|e| format!("Failed to create parquet reader builder: {}", e))?;

        // Log schema information
        let schema = builder.schema();

        // Build projection mask from column names
        let projection = if let Some(names) = column_names {
            // Find column indices by name
            let mut indices = Vec::new();
            for name in names {
                if let Ok(idx) = schema.index_of(name) {
                    indices.push(idx);
                }
            }

            if indices.is_empty() {
                return Err(format!("None of the requested columns were found in the schema"));
            }

            ProjectionMask::leaves(builder.parquet_schema(), indices.into_iter())
        } else {
            ProjectionMask::all()
        };

        builder
            .with_projection(projection)
            .with_batch_size(65536)
            .build()
            .map_err(|e| format!("Failed to build record batch reader: {}", e))?
    } else {
        // Local file reader
        let file = File::open(file_path).map_err(|e| format!("Failed to open file: {}", e))?;

        let builder = ParquetRecordBatchReaderBuilder::try_new(file)
            .map_err(|e| format!("Failed to create parquet reader builder: {}", e))?;

        let schema = builder.schema();

        // Build projection mask from column names
        let projection = if let Some(names) = column_names {
            let mut indices = Vec::new();
            for name in names {
                if let Ok(idx) = schema.index_of(name) {
                    indices.push(idx);
                }
            }
            if indices.is_empty() {
                return Err(format!("None of the requested columns were found in the schema"));
            }
            ProjectionMask::leaves(builder.parquet_schema(), indices.into_iter())
        } else {
            ProjectionMask::all()
        };

        builder
            .with_projection(projection)
            .with_batch_size(65536)
            .build()
            .map_err(|e| format!("Failed to build record batch reader: {}", e))?
    };

    let handle = ReaderHandle {
        reader,
        current_batch: None,
        current_batch_row_offset: 0,
        file_path: file_path.to_string(),
        column_names: column_names.map(|names| names.to_vec()),
        last_step_returned: -1.0,
        reader_exhausted: false,
    };

    Ok(handle)
}

impl ReaderHandle {
    /// Recreate the reader from the stored file path
    /// This is necessary because ParquetRecordBatchReader is an iterator that gets exhausted
    fn recreate_reader(&mut self) -> Result<(), String> {
        // Recreate using stored column names for proper projection
        let new_reader = create_reader_internal(
            &self.file_path,
            self.column_names.as_deref(),
        )?;

        self.reader = new_reader.reader;
        self.last_step_returned = -1.0;
        self.reader_exhausted = false;
        self.current_batch = None;
        self.current_batch_row_offset = 0;

        Ok(())
    }
}

/// FFI-compatible struct for returning scan results
/// This struct is passed by pointer from Go, and Rust fills it in
#[repr(C)]
pub struct StepScanResult {
    pub vec_ptr: usize,           // Pointer to Vec<u8> for cleanup
    pub data_ptr: usize,          // Pointer to IPC stream buffer data
    pub data_len: u64,            // Length of IPC stream buffer (in bytes)
    pub num_rows_returned: u64,   // Total rows in result
}

/// Scan all records in a reader and return only those with step values between minStep and maxStep
///
/// If the reader is exhausted, or the last step the reader read is less than the min step,
/// the reader will be recreated internally to allow scanning records which have already been read.
///
/// Parameters:
/// - reader_ptr: Pointer to ReaderHandle
/// - min_step: Minimum step value (inclusive)
/// - max_step: Maximum step value (exclusive)
/// - out_result: resulting pointer to StepScanResult struct to fill.
///     This must be created by the caller and cannot be null.
///
/// Returns a C string error message on failure (must be freed with free_string)
///
/// # Safety
///
/// This function is unsafe because it:
/// - Dereferences raw pointers
/// - out_result must point to valid memory
/// - Returns a buffer (in out_result) that must be freed by caller using free_ipc_stream
#[no_mangle]
pub unsafe extern "C" fn reader_scan_step_range(
    reader_ptr: *mut ReaderHandle,
    min_step: f64,
    max_step: f64,
    out_result: *mut StepScanResult,
) -> *const libc::c_char {
    if reader_ptr.is_null() {
        return error_to_c_string("Null reader pointer provided");
    }
    if out_result.is_null() {
        return error_to_c_string("Null out result pointer provided");
    }

    let handle = unsafe { &mut *reader_ptr };

    // Only recreate the reader if:
    // 1. We're going backwards (min_step <= last_step_returned)
    // 2. The reader was exhausted in a previous call
    // Otherwise, continue from where we left off
    let needs_recreation = min_step <= handle.last_step_returned || handle.reader_exhausted;
    if needs_recreation {
        if let Err(e) = handle.recreate_reader() {
            return error_to_c_string(&format!("Failed to recreate reader: {}", e));
        }
    }

    // Create a buffer to hold the IPC stream
    let mut buffer = Vec::new();

    let mut total_rows_returned = 0;
    let mut actual_max_step_returned: Option<f64> = None;

    // Read batches and process row by row
    // Collecting the rows that fall within the step range
    let mut matching_rows: Vec<RecordBatch> = Vec::new();
    loop {
        // See if we already have a batch from a previous call
        let batch = if let Some(ref cached_batch) = handle.current_batch {
            cached_batch.clone()
        } else {
            // Fetch next batch from reader
            match handle.reader.next() {
                Some(Ok(batch)) => {
                    handle.current_batch = Some(batch.clone());
                    handle.current_batch_row_offset = 0;
                    batch
                }
                Some(Err(e)) => {
                    return error_to_c_string(&format!("Failed to read batch: {}", e));
                }
                // Reached end of file
                None => {
                    handle.reader_exhausted = true;
                    handle.current_batch = None;
                    break;
                }
            }
        };

        // Get the index of the step column
        let step_col_idx = match batch.schema().index_of(STEP_COLUMN_NAME) {
            Ok(idx) => idx,
            Err(_) => {
                return error_to_c_string(&format!(
                    "Step column '{}' not found in schema",
                    STEP_COLUMN_NAME
                ));
            }
        };
        let step_column = batch.column(step_col_idx);

        // Get step values as f64, supporting multiple numeric types
        // Steps can be stored as Float64, Int64, Int32, etc.
        let step_values: Vec<Option<f64>> = if let Some(arr) = step_column.as_any().downcast_ref::<Float64Array>() {
            (0..batch.num_rows())
                .map(|i| if arr.is_null(i) { None } else { Some(arr.value(i)) })
                .collect()
        } else if let Some(arr) = step_column.as_any().downcast_ref::<Int64Array>() {
            (0..batch.num_rows())
                .map(|i| if arr.is_null(i) { None } else { Some(arr.value(i) as f64) })
                .collect()
        } else {
            return error_to_c_string(&format!(
                "Step column '{}' is not a supported numeric type (Float64 or Int64)",
                STEP_COLUMN_NAME
            ));
        };

        // Filter rows that fall within the step range, using a filter mask.
        let mut filter_mask_vec = vec![false; batch.num_rows()];
        let mut should_stop_early = false;

        // Set matching rows to true in the mask
        for i in handle.current_batch_row_offset..batch.num_rows() {
            let step_value = match step_values[i] {
                Some(v) => v,
                None => continue,
            };

            // Check if we've reached or exceeded the max step
            // This assumes that step values are monotonically increasing.
            if step_value >= max_step {
                should_stop_early = true;
                handle.current_batch_row_offset = i;
                break;
            } else if step_value >= min_step {
                // Mark this row as matching
                filter_mask_vec[i] = true;

                // Track the actual max step value we're returning
                if let Some(current_max) = actual_max_step_returned {
                    if step_value > current_max {
                        actual_max_step_returned = Some(step_value);
                    }
                } else {
                    actual_max_step_returned = Some(step_value);
                }
            }
        }

        // Build the filter mask from the vec
        let filter_mask = arrow::array::BooleanArray::from(filter_mask_vec);

        // Apply the filter to get matching rows
        let filtered_batch = match arrow::compute::filter_record_batch(&batch, &filter_mask) {
            Ok(b) => b,
            Err(e) => {
                return error_to_c_string(&format!("Failed to filter batch: {}", e));
            }
        };

        if filtered_batch.num_rows() > 0 {
            matching_rows.push(filtered_batch);
        }

        if should_stop_early {
            break;
        } else {
            handle.current_batch = None;
            handle.current_batch_row_offset = 0;
        }
    }

    // Now write all matching rows to IPC stream
    if !matching_rows.is_empty() {
        let schema = matching_rows[0].schema();
        let mut writer = match StreamWriter::try_new(&mut buffer, &schema) {
            Ok(w) => w,
            Err(e) => {
                return error_to_c_string(&format!("Failed to create IPC writer: {}", e));
            }
        };

        for batch in &matching_rows {
            if let Err(e) = writer.write(batch) {
                return error_to_c_string(&format!("Failed to write batch: {}", e));
            }
            total_rows_returned += batch.num_rows();
        }

        if let Err(e) = writer.finish() {
            return error_to_c_string(&format!("Failed to finish IPC stream: {}", e));
        }
    }

    // If no rows were found, return empty result
    if total_rows_returned == 0 {
        unsafe {
            (*out_result).vec_ptr = 0;
            (*out_result).data_ptr = 0;
            (*out_result).data_len = 0;
            (*out_result).num_rows_returned = 0;
        }
        return std::ptr::null();
    }

    // Update the last step returned to the actual max step value we returned
    // This allows the next query to continue from where we left off
    if let Some(actual_max) = actual_max_step_returned {
        handle.last_step_returned = actual_max;
    }

    // Convert the buffer to a boxed pointer
    // This allows us to return the pointer to the buffer to the caller
    let data_len = buffer.len();
    let boxed_buffer = Box::new(buffer);
    let buffer_ptr = Box::into_raw(boxed_buffer);

    // Get pointer to the actual data inside the Vec
    let vec_ref = unsafe { &*buffer_ptr };
    let data_ptr = vec_ref.as_ptr();

    // Set the result output
    unsafe {
        (*out_result).vec_ptr = buffer_ptr as usize;
        (*out_result).data_ptr = data_ptr as usize;
        (*out_result).data_len = data_len as u64;
        (*out_result).num_rows_returned = total_rows_returned as u64;
    }
    std::ptr::null()
}

/// Free an IPC stream buffer allocated by Rust
///
/// # Safety
///
/// This function is unsafe because it:
/// - Takes ownership of a raw pointer to a Vec<u8>
/// - Must only be called with pointers returned from reader_scan_step_range
/// - Must only be called once per pointer
#[no_mangle]
pub unsafe extern "C" fn free_ipc_stream(buffer_ptr: *mut Vec<u8>) {
    if !buffer_ptr.is_null() {
        let _ = Box::from_raw(buffer_ptr);
    }
}

/// Free a string allocated by Rust
///
/// # Safety
///
/// This function is unsafe because it:
/// - Takes ownership of a raw pointer
/// - Must only be called with pointers returned from this library
/// - Must only be called once per pointer
#[no_mangle]
pub unsafe extern "C" fn free_string(s: *mut libc::c_char) {
    if !s.is_null() {
        let _ = CString::from_raw(s);
    }
}


/// Free a reader handle
///
/// # Safety
///
/// This function is unsafe because it:
/// - Takes ownership of a raw pointer
/// - Must only be called with pointers returned from create_reader
/// - Must only be called once per pointer
#[no_mangle]
pub unsafe extern "C" fn free_reader(reader_ptr: *mut ReaderHandle) {
    if !reader_ptr.is_null() {
        let _ = Box::from_raw(reader_ptr);
    }
}

fn error_to_c_string(error: &str) -> *mut libc::c_char {
    let error_json = format!(r#"{{"error":"{}"}}"#, error.replace('"', "\\\""));
    match CString::new(error_json) {
        Ok(cstring) => cstring.into_raw(),
        Err(e) => {
            eprintln!("Failed to create error CString: {}", e);
            std::ptr::null_mut()
        }
    }
}
