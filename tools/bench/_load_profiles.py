#!/usr/bin/env python
from __future__ import annotations

import itertools

VARIANTS = {
    "mode=online": {},
    "mode=offline": {
        "mode": "offline",
    },
    "core=false": {},
    "core=true": {
        "core": "true",
    },
}

ALL_VARIANTS = {
    "mode": ("offline", "online"),
    "core": ("false", "true"),
}

PROFILES = {
    "v1-empty": {
        "variants": ALL_VARIANTS,
    },
    "v1-scalars": {
        "all": {
            "history_floats": 100,
            "num_parallel": 10,
            "num_history": 100,
        },
        "variants": ALL_VARIANTS,
    },
    "v1-tables": {
        "all": {
            "history_tables": 20,
            "num_history": 10,
        },
        "variants": ALL_VARIANTS,
    },
    "v1-images": {
        "all": {
            "history_images": 10,
            "history_images_dim": 16,
            "num_parallel": 10,
            "num_history": 50,
        },
        "variants": ALL_VARIANTS,
    },
}


def parse_profile(parser, old_args, copy_fields):
    profile = PROFILES[old_args.test_profile]
    all_attrs = profile.get("all", {})

    # get all variants in the form variant_dict which key is name of variant,
    # values are list of variants for that type
    # example {"mode": ["online", "offline"]}
    all_variants = profile.get("variants", {})
    groups = []
    for vname, vvals in all_variants.items():
        groups.append([f"{vname}={val}" for val in vvals])
    expanded = tuple(itertools.product(*groups)) or tuple(tuple())

    args_list = []
    for variant_list in expanded:
        args = parser.parse_args([])
        for field in copy_fields:
            setattr(args, field, getattr(old_args, field))
        for k, v in all_attrs.items():
            setattr(args, k, v)
        for variant in variant_list:
            variant_dict = VARIANTS[variant]
            for k, v in variant_dict.items():
                setattr(args, k, v)
        if variant_list:
            args.test_variant = ",".join(variant_list)
        args_list.append(args)
    return args_list
