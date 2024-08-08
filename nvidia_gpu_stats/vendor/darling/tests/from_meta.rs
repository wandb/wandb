use darling::{Error, FromMeta};
use syn::parse_quote;

#[derive(Debug, FromMeta)]
struct Meta {
    #[darling(default)]
    meta1: Option<String>,
    #[darling(default)]
    meta2: bool,
}

#[test]
fn nested_meta_meta_value() {
    let meta = Meta::from_list(&[parse_quote! {
        meta1 = "thefeature"
    }])
    .unwrap();
    assert_eq!(meta.meta1, Some("thefeature".to_string()));
    assert!(!meta.meta2);
}

#[test]
fn nested_meta_meta_bool() {
    let meta = Meta::from_list(&[parse_quote! {
        meta2
    }])
    .unwrap();
    assert_eq!(meta.meta1, None);
    assert!(meta.meta2);
}

#[test]
fn nested_meta_lit_string_errors() {
    let err = Meta::from_list(&[parse_quote! {
        "meta2"
    }])
    .unwrap_err();
    assert_eq!(
        err.to_string(),
        Error::unsupported_format("literal").to_string()
    );
}

#[test]
fn nested_meta_lit_integer_errors() {
    let err = Meta::from_list(&[parse_quote! {
        2
    }])
    .unwrap_err();
    assert_eq!(
        err.to_string(),
        Error::unsupported_format("literal").to_string()
    );
}

#[test]
fn nested_meta_lit_bool_errors() {
    let err = Meta::from_list(&[parse_quote! {
        true
    }])
    .unwrap_err();
    assert_eq!(
        err.to_string(),
        Error::unsupported_format("literal").to_string()
    );
}

/// Tests behavior of FromMeta implementation for enums.
mod enum_impl {
    use darling::{Error, FromMeta};
    use syn::parse_quote;

    /// A playback volume.
    #[derive(Debug, Clone, Copy, PartialEq, Eq, FromMeta)]
    enum Volume {
        Normal,
        Low,
        High,
        #[darling(rename = "dB")]
        Decibels(u8),
    }

    #[test]
    fn string_for_unit_variant() {
        let volume = Volume::from_string("low").unwrap();
        assert_eq!(volume, Volume::Low);
    }

    #[test]
    fn single_value_list() {
        let unit_variant = Volume::from_list(&[parse_quote!(high)]).unwrap();
        assert_eq!(unit_variant, Volume::High);

        let newtype_variant = Volume::from_list(&[parse_quote!(dB = 100)]).unwrap();
        assert_eq!(newtype_variant, Volume::Decibels(100));
    }

    #[test]
    fn empty_list_errors() {
        let err = Volume::from_list(&[]).unwrap_err();
        assert_eq!(err.to_string(), Error::too_few_items(1).to_string());
    }

    #[test]
    fn multiple_values_list_errors() {
        let err = Volume::from_list(&[parse_quote!(low), parse_quote!(dB = 20)]).unwrap_err();
        assert_eq!(err.to_string(), Error::too_many_items(1).to_string());
    }
}
