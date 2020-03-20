'''
plot_summary_metrics
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "data": {
    "name": "${history-table:rows:x-axis,key}"
  },
  "title": "Summary Metrics",
  "encoding": {
    "y": {"field": "metric_name", "type": "nominal"},
    "x": {"field": "metric_value", "type": "quantitative"},
    "color": {"field": "metric_name", "type": "nominal",
    "scale": {
      "range": ["#AB47BC", "#3498DB", "#5C6BC0", "#3F51B5"]
    }},
    "opacity": {"value": 0.8}
  },
  "layer": [{
    "mark": "bar"
  }, {
    "mark": {
      "type": "text",
      "align": "left",
      "baseline": "middle",
      "dx": 3
    },
    "encoding": {
      "text": {"field": "metric_value", "type": "quantitative"}
    }
  }]
}

plot_learning_curve
l2k2/sklearn_learningcurve

{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "padding": 5,
  "width": "500",
  "height": "500",
  "data":
    {
      "name": "${history-table:rows:x-axis,key}"
    },
    "title": {
      "text": "Learning Curve"
    },
  "layer": [
    {
      "encoding": {
        "x": {"field": "train_size", "type": "quantitative"},
        "y": {"field": "score", "type": "quantitative"},
        "color": {"field": "dataset", "type": "nominal"},
        "opacity": {"value": 0.7}
      },
      "layer": [
        {"mark": "line"},
        {
          "selection": {
            "label": {
              "type": "single",
              "nearest": true,
              "on": "mouseover",
              "encodings": ["x"],
              "empty": "none"
            }
          },
          "mark": "point",
          "encoding": {
            "opacity": {
              "condition": {"selection": "label", "value": 1},
              "value": 0
            }
          }
        }
      ]
    },
    {
      "transform": [{"filter": {"selection": "label"}}],
      "layer": [
        {
          "mark": {"type": "rule", "color": "gray"},
          "encoding": {
            "x": {"type": "quantitative", "field": "train_size"}
          }
        },
        {
          "encoding": {
            "text": {"type": "quantitative", "field": "score"},
            "x": {"type": "quantitative", "field": "train_size"},
            "y": {"type": "quantitative", "field": "score"}
          },
          "layer": [
            {
              "mark": {
                "type": "text",
                "stroke": "white",
                "strokeWidth": 2,
                "align": "left",
                "dx": 5,
                "dy": -5
              }
            },
            {
              "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
              "encoding": {
                "color": {
                  "type": "nominal", "field": "dataset", "scale": {
                  "domain": ["train", "test"],
                  "range": ["#3498DB", "#AB47BC"]
                  },
                  "legend": {
                  "title": " "
                  }
                }
              }
            }
          ]
        }
      ]
    }
  ]
}

plot_roc
{
    "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
    "padding": 5,
    "width": "500",
    "height": "500",
    "data":
      {
        "name": "${history-table:rows:x-axis,key}"
      },
    "title": {
      "text": "ROC Curve"
    },"layer": [
      {
        "encoding": {
          "x": {"field": "fpr", "type": "quantitative", "axis": {"title": "False Positive Rate"}},
          "y": {"field": "tpr", "type": "quantitative", "axis": {"title": "True Positive Rate"}},
          "color": {"field": "class", "type": "nominal"},
          "opacity": {"value": 0.7}
        },
        "layer": [
          {"mark": "line"},
          {
            "selection": {
              "label": {
                "type": "single",
                "nearest": true,
                "on": "mouseover",
                "encodings": ["x"],
                "empty": "none"
              }
            },
            "mark": "point",
            "encoding": {
              "opacity": {
                "condition": {"selection": "label", "value": 1},
                "value": 0
              }
            }
          }
        ]
      },
      {
        "transform": [{"filter": {"selection": "label"}}],
        "layer": [
          {
            "mark": {"type": "rule", "color": "gray"},
            "encoding": {
              "x": {"type": "quantitative", "field": "train_size"}
            }
          },
          {
            "encoding": {
              "text": {"type": "quantitative", "field": "fpr"},
              "x": {"type": "quantitative", "field": "fpr"}
            },
            "layer": [
              {
                "mark": {
                  "type": "text",
                  "stroke": "white",
                  "strokeWidth": 2,
                  "align": "left",
                  "dx": 5,
                  "dy": -5
                }
              },
              {
                "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
                "encoding": {
                  "color": {
                    "type": "nominal", "field": "class", "scale": {
                    "range": ["#3498DB", "#AB47BC"]
                    },
                    "legend": {
                    "title": " "
                    }
                  }
                }
              }
            ]
          }
        ]
      }
    ]
}

plot_confusion_matrix
{
    "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
    "padding": 5,
    "width": 500,
    "height": 500,
    "data":
      {
        "name": "${history-table:rows:x-axis,key}"
      },
    "title": {
      "text": "Confusion Matrix"
    },
      "mark": "circle",
    "encoding": {
      "x": {
        "field": "Predicted",
        "type": "nominal",
        "axis": {
          "maxExtent": 50,
          "labelLimit": 40,
          "labelAngle": -45
        }
      },
      "y": {
        "field": "Actual",
        "type": "nominal"

      },
      "size": {
        "field": "Count",
        "type": "quantitative"
      },
      "color": {
        "value": "#3498DB"
      }
    }
}

plot_precision_recall
{
    "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
    "padding": 5,
    "width": 500,
    "height": 500,
    "data":
      {
        "name": "${history-table:rows:x-axis,key}"
      },
    "title": {
      "text": "Precision Recall"
    },"layer": [
      {
        "encoding": {
          "x": {"field": "precision", "type": "quantitative"},
          "y": {"field": "recall", "type": "quantitative"},
          "color": {"field": "class", "type": "nominal"},
          "opacity": {"value": 0.7}
        },
        "layer": [
          {"mark": "line"},
          {
            "selection": {
              "label": {
                "type": "single",
                "nearest": true,
                "on": "mouseover",
                "encodings": ["x"],
                "empty": "none"
              }
            },
            "mark": "point",
            "encoding": {
              "opacity": {
                "condition": {"selection": "label", "value": 1},
                "value": 0
              }
            }
          }
        ]
      },
      {
        "transform": [{"filter": {"selection": "label"}}],
        "layer": [
          {
            "encoding": {
              "text": {"type": "nominal", "field": "class"},
              "x": {"type": "quantitative", "field": "precision"},
              "y": {"type": "quantitative", "field": "recall"}
            },
            "layer": [
              {
                "mark": {
                  "type": "text",
                  "stroke": "white",
                  "strokeWidth": 2,
                  "align": "left",
                  "dx": 5,
                  "dy": -5
                }
              },
              {
                "mark": {"type": "text", "align": "left", "dx": 5, "dy": -5},
                "encoding": {
                  "color": {
                    "type": "nominal", "field": "class", "scale": {
                    "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955"]
                    },
                    "legend": {
                    "title": " "
                    }
                  }
                }
              }
            ]
          }
        ]
      }
    ]
}

plot_feature_importances
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "data": {
    "name": "${history-table:rows:x-axis,key}"
  },
  "title": "Feature Importances",
  "mark": "bar",
  "encoding": {
    "y": {"field": "feature_names", "type": "nominal", "axis": {"title":"Features"},"sort": "-x"},
    "x": {"field": "importances", "type": "quantitative", "axis": {"title":"Importances"}},
    "color": {"value": "#3498DB"},
    "opacity": {"value": 0.9}
  }
}

plot_elbow_curve
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "description": "A dual axis chart, created by setting y's scale resolution to `\"independent\"`",
  "width": 400, "height": 300,
  "data": {
    "name": "${history-table:rows:x-axis,key}"
  },
  "title": "Elbow Plot - Errors vs Cluster Size",
  "encoding": {
    "x": {
        "field": "cluster_ranges",
        "bin": true,
        "axis": {"title": "Number of Clusters"},
        "type": "quantitative"
    }
  },
  "layer": [
    {
      "mark": {"opacity": 0.5, "type": "line", "color": "#AB47BC"},
      "encoding": {
        "y": {
          "field": "errors",
          "type": "quantitative",
          "axis": {"title": "Sum of Squared Errors", "titleColor": "#AB47BC"}
        }
      }
    },
    {
      "mark": {"opacity": 0.3, "stroke": "#3498DB", "strokeDash": [6, 4], "type": "line"},
      "encoding": {
        "y": {
          "field": "clustering_time",
          "type": "quantitative",
          "axis": {"title": "Clustering Time", "titleColor":"#3498DB"}
        }
      }
    }
  ],
  "resolve": {"scale": {"y": "independent"}}
}

plot_silhouette
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "data": {"name": "${history-table:rows:x-axis,key}"},
  "title": "Silhouette analysis of cluster centers",
  "hconcat": [
  {
    "width": 400,
    "height": 400,
    "layer": [
    {
    "mark": "area",
    "encoding": {
      "x": {
      "field": "x1",
      "type": "quantitative",
      "axis": {"title":"Silhouette Coefficients"}
      },
      "x2": {
      "field": "x2"
      },
      "y": {
        "title": "Cluster Label",
        "field": "y_sil",
        "type": "quantitative",
      "axis": {"title":"Clusters", "labels": false}
      },
      "color": {
        "field": "color_sil",
        "type": "nominal",
        "axis": {"title":"Cluster Labels"},
        "scale": {
          "range": ["#AB47BC", "#3498DB", "#55BBBB", "#5C6BC0", "#FBC02D", "#3F51B5"]}
    },
      "opacity": { "value": 0.7 }
    }},
    {

      "mark": {
        "type":"rule",
      "strokeDash": [6, 4],
      "stroke":"#f88c99"},
      "encoding": {
        "x": {
          "field": "silhouette_avg",
          "type": "quantitative"
        },
        "color": {"value": "red"},
        "size": {"value": 1},
      "opacity": { "value": 0.5 }
      }
    }]
  },
  {
    "width": 400,
    "height": 400,
    "layer": [
      {
        "mark": "circle",
        "encoding": {
          "x": {"field": "x", "type": "quantitative", "scale": {"zero": false}, "axis": {"title":"Feature Space for 1st Feature"}},
          "y": {"field": "y", "type": "quantitative", "scale": {"zero": false}}, "axis": {"title":"Feature Space for 2nd Feature"},
          "color": {"field": "colors", "type": "nominal", "axis": {"title":"Cluster Labels"}}
        }
      },
      {
        "mark": "point",
        "encoding": {
          "x": {"field": "centerx", "type": "quantitative", "scale": {"zero": false}, "axis": {"title":"Feature Space for 1st Feature"}},
          "y": {"field": "centery", "type": "quantitative", "scale": {"zero": false}, "axis": {"title":"Feature Space for 2nd Feature"}},
          "color": {"field": "colors", "type": "nominal", "axis": {"title":"Cluster Labels"}},
          "size": {"value": 80}
        }
      }
    ]
  }
  ]
}

plot_class_balance
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "width": 500,
  "height": 500,
  "title": "Class Proportions in Target Variable",
  "data": {
    "name": "${history-table:rows:x-axis,key}"
  },
  "selection": {
    "highlight": {"type": "single", "empty": "none", "on": "mouseover"},
    "select": {"type": "multi"}
  },
  "mark": {
    "type": "bar",
    "stroke": "black",
    "cursor": "pointer"
  },
  "encoding": {
    "x": {"field": "class", "type": "ordinal", "axis": {"title": "Class"}},
    "y": {"field": "count", "type": "quantitative", "axis": {"title": "Number of instances"}},
    "fillOpacity": {
      "condition": {"selection": "select", "value": 1},
      "value": 0.3
    },
    "opacity": {"value": 0.9},
    "color": {
      "field": "dataset",
      "type": "nominal",
      "scale": {
        "domain": ["train", "test"],
        "range": ["#3498DB", "#4DB6AC"]
      },
      "legend": {"title": "Dataset"}
    },
    "strokeWidth": {
      "condition": [
        {
          "test": {
            "and": [
              {"selection": "select"},
              "length(data(\"select_store\"))"
            ]
          },
          "value": 2
        },
        {"selection": "highlight", "value": 1}
      ],
      "value": 0
    }
  },
  "config": {
    "scale": {
      "bandPaddingInner": 0.2
    }
  }
}

plot_calibration_curve
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "padding": 5,
  "data":
    {
      "name": "${history-table:rows:x-axis,key}"
    },
  "title": "Calibration Curve",
  "vconcat": [
    {
      "layer": [
      {
        "encoding": {
          "x": {"field": "mean_predicted_value", "type": "quantitative", "axis": {"title": "Mean predicted value"}},
          "y": {"field": "fraction_of_positives", "type": "quantitative", "axis": {"title": "Fraction of positives"}},
          "color": {
            "field": "model",
            "type": "nominal",
            "axis": {"title": "Models"},
            "scale": {
              "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955", "#FBC02D"]
            }
          }
        },
        "layer": [
          {
            "mark": {
              "type": "line",
              "point": {
                "filled": false,
                "fill": "white"
              }
            }
          }
        ]
      }]
    },
    {
    "mark": {"type": "tick"},
    "encoding": {
      "x": {"field": "edge_dict", "type": "quantitative","bin":true, "axis": {"title": "Mean predicted value"}},
      "y": {"field": "hist_dict", "type": "quantitative", "axis": {"title": "Counts"}},
      "strokeWidth": {
        "value": 2
      },
      "color": {
        "field": "model",
        "type": "nominal",
        "axis": {"title": "Models"},
        "scale": {
          "range": ["#3498DB", "#AB47BC", "#55BBBB", "#BB9955"]
        }
      }
    }
    }
  ]
}

plot_outlier_candidates
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "padding": 5,
  "data":
    {
      "name": "${history-table:rows:x-axis,key}"
    },
  "title": {
    "text": "Cook's Distance Outlier Detection"
  },
 "layer": [{
    "mark": "bar",
    "encoding": {
      "x": {
        "field": "instance_indicies",
        "type": "quantitative",
        "axis": {"title": "Instances"}
      },
      "y": {
        "field": "distance",
        "type": "quantitative",
        "axis": {"title": "Influence (Cook's Distance)"}
      },
      "color":  {"value": "#3498DB"},
      "opacity":  {"value": 0.4}
    }
  },{
    "mark": {
      "type":"rule",
      "strokeDash": [6, 4],
      "stroke":"#f88c99"},
    "encoding": {
      "y": {
        "field": "influence_threshold",
        "type": "quantitative"
      },
      "color": {"value": "red"},
      "size": {"value": 1}
    }
  }, {
    "mark": {
      "type": "text",
      "align": "left",
      "baseline": "top",
      "dx": 0
    }
  }]
}

plot_residuals
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "width": "container",
  "data":
    {
      "name": "${history-table:rows:x-axis,key}"
    },
  "title": "Residuals Plot",
  "vconcat": [
    {
      "layer": [
      {
        "encoding": {
          "y": {"field": "y_pred", "type": "quantitative", "axis": {"title": "Predicted Value"}},
          "x": {"field": "residuals", "type": "quantitative", "axis": {"title": "Residuals"}},
          "color": {
            "field": "dataset",
            "type": "nominal",
            "axis": {"title": "Dataset"}
          }
        },
        "layer": [
          {
            "mark": {
              "type": "point",
              "opacity": 0.5,
              "filled" : true
            }
          }
        ]
      }]
    },
    {
    "mark": {"type": "bar",
            "opacity": 0.8},
    "encoding": {
      "x": {"field": "residuals", "type": "quantitative", "bin": true, "axis": {"title": "Residuals"}},
      "y": {
        "aggregate": "count", "field": "residuals", "type": "quantitative", "axis": {"title": "Distribution"}},
      "strokeWidth": {
        "value": 1
      },
      "color": {
        "field": "dataset",
        "type": "nominal",
        "axis": {"title": "Dataset"},
        "scale": {
          "range": ["#AB47BC", "#3498DB"]
        }
      }
    }
    }
  ]
}

plot_decision_boundaries
{
  "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
  "data": {"name": "${history-table:rows:x-axis,key}"},
  "title": "Decision Boundary - Projected Into 2D Space",
  "width": 300,
  "height": 200,
  "layer": [
    {
      "mark": {"type" :"point", "opacity": 0.5},
      "encoding": {
        "x": {"field": "x", "type": "quantitative", "scale": {"zero": false}, "axis": {"title":"Principle Component Dimension 1"}},
        "y": {"field": "y", "type": "quantitative", "scale": {"zero": false}, "axis": {"title":"Principle Component Dimension 2"}},
        "color": {
          "field": "color",
          "type": "nominal",
          "axis": {"title":"Cluster Labels"},
          "scale": {
            "range": ["#5C6BC0", "#AB47BC", "#4aa3df", "#3498DB", "#55BBBB"]
          }
        }
      }
    }
  ]
}
'''

'''
heatmap/v1
{
    "$schema": "https://vega.github.io/schema/vega-lite/v4.json",
    "padding": 5,
    "width": 500,
    "height": 500,
    "data":
      {
        "name": "${history-table:rows:x-axis,key}"
      },
    "title": {
      "text": {"value": ""}
    },
    "encoding": {
      "x": {
        "field": "x_axis",
        "type": "nominal",
        "axis": { "title": "" }
      },
      "y": {
        "field": "y_axis",
        "type": "nominal",
        "axis": { "title": "" }
      }
    },
    "layer": [
      {
        "mark": "rect",
        "encoding": {
          "color": {
            "field": "values",
            "type": "quantitative",
            "title": "Values",
            "scale": {
              "scheme": "tealblues"
            }
          }
        }
      },
      {
        "mark": "text",
        "encoding": {
          "text": {"field": "values", "type": "quantitative"}
        }
      }
    ]
}
'''
