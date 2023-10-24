use image;
use numpy::PyReadonlyArrayDyn;
use pyo3::prelude::*;
use pythonize::depythonize;
use serde_json::Value as JsonValue;
use sha2::Digest;
use std::collections::HashMap;

use ::wandbinder::{run, session, settings, wandb};

fn normalize(data: &Vec<f64>) -> Vec<f64> {
    let min = data
        .iter()
        .cloned()
        .min_by(|a, b| a.partial_cmp(b).unwrap())
        .unwrap();
    let max = data
        .iter()
        .cloned()
        .max_by(|a, b| a.partial_cmp(b).unwrap())
        .unwrap();

    data.iter()
        .map(|&value| (value - min) / (max - min))
        .collect()
}

fn ndarray_to_image(arr: PyReadonlyArrayDyn<'_, f64>, path: &String) -> run::Media {
    let shape = arr.shape();
    // Convert the ndarray to a Vec<f64> for serialization
    let vec_data: Vec<f64> = arr.as_slice().unwrap().to_vec();
    // convert to Vec<u8> for image serialization
    let normalized = normalize(&vec_data);
    let byte_values: Vec<u8> = normalized.iter().map(|&v| (v * 255.0) as u8).collect();

    // compute sha256 of the image
    let mut hasher = sha2::Sha256::new();
    hasher.update(&byte_values);
    let image_sha256 = hasher.finalize();
    let image_sha256_str = format!("{:x}", image_sha256);

    let img: image::ImageBuffer<image::Rgb<u8>, Vec<u8>> =
        image::ImageBuffer::from_vec(shape[0] as u32, shape[1] as u32, byte_values).unwrap();

    std::fs::create_dir_all(format!("{}/media/images", path)).unwrap();
    // You can now save or manipulate the ImageBuffer
    // use sha256 as the filename.png
    let image_path = format!("media/images/{}.png", &image_sha256_str[..20]);
    let full_path = format!("{}/{}", path, image_path);
    img.save(&full_path).unwrap();

    run::Media {
        _type: "image-file".to_string(),
        path: image_path.to_string(),
        sha256: image_sha256_str.to_string(),
    }
}

#[derive(FromPyObject, Clone)]
pub enum PyValue<'py> {
    Py(Py<PyAny>),
    Ndarray(PyReadonlyArrayDyn<'py, f64>),
}

fn convert_map<'py>(
    dir: &String,
    input: HashMap<String, PyValue<'py>>,
) -> Result<HashMap<String, JsonValue>, serde_json::Error> {
    let mut output = HashMap::new();

    for (key, py_value) in input {
        let json_value = match py_value {
            PyValue::Py(py_any) => {
                Python::with_gil(|py| {
                    let value: &PyAny = py_any.as_ref(py);
                    // Use depythonize to get a serde_json::Value
                    depythonize::<JsonValue>(value).unwrap()
                })
            }
            PyValue::Ndarray(arr) => {
                // TODO: keep the shape intact
                let shape = arr.shape();
                if shape.len() == 3 {
                    let value_media = ndarray_to_image(arr, dir);
                    value_media.into()
                } else {
                    let vec_data: Vec<f64> = arr.as_slice().unwrap().to_vec();
                    vec_data.into()
                }
            }
        };

        output.insert(key, json_value);
    }

    Ok(output)
}

#[pyclass]
struct PySession {
    inner: session::Session,
}

#[pyclass]
struct PyRun {
    inner: run::Run,
}

#[pymethods]
impl PyRun {
    #[new]
    pub fn new(session: &PySession, run_id: Option<String>) -> Self {
        PyRun {
            inner: session.inner.init_run(run_id),
        }
    }

    pub fn finish(&mut self) {
        self.inner.finish();
    }

    pub fn log(&self, py: Python, data: HashMap<String, PyValue>) {
        // TODO: handle errors
        let data: HashMap<String, JsonValue> =
            convert_map(&self.inner.settings.files_dir(), data).unwrap();
        self.inner.log(data);
    }
}

#[pymodule]
fn wandbinder(_py: Python<'_>, m: &PyModule) -> PyResult<()> {
    let log_level = tracing::Level::INFO;
    // let log_level = tracing::Level::DEBUG;
    tracing_subscriber::fmt().with_max_level(log_level).init();

    m.add_function(wrap_pyfunction!(wandb::init, m)?)?;
    m.add_class::<settings::Settings>()?;
    m.add_class::<session::Session>()?;
    m.add_class::<run::Run>()?;
    Ok(())
}
