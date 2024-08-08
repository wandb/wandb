/*!
Internal macro used in [nvml-wrapper](https://github.com/Cldfire/nvml-wrapper).

This macro is tied to the crate and is not meant for use by the general public.

Its purpose is to auto-generate both a `TryFrom` implementation converting an `i32`
into a Rust enum (specifically for converting a C enum represented as an integer that
has come over FFI) and an `as_c` method for converting the Rust enum back into an `i32`.

It wouldn't take much effort to turn this into something usable by others; if you're
interested feel free to contribute or file an issue asking me to put some work into it.
*/

use proc_macro2::{Ident, Span, TokenStream};
use quote::{quote, ToTokens};
use syn;

use darling::{ast, FromVariant, FromDeriveInput};

/// Handles parsing attributes on the enum itself
#[derive(Debug, FromDeriveInput)]
#[darling(attributes(wrap), supports(enum_any))]
struct EnumReceiver {
    ident: Ident,
    data: ast::Data<VariantReceiver, ()>,
    /// The ident of the C enum to be wrapped
    c_enum: String,
}

impl ToTokens for EnumReceiver {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let EnumReceiver {
            ref ident,
            ref data,
            ref c_enum,
        } = *self;

        let join_c_name_and_variant = |name: &str, variant: &str| {
            Ident::new(&format!("{}_{}", &name, variant), Span::call_site())
        };

        let c_name = Ident::new(c_enum, Span::call_site());
        let rust_name = ident;

        let variants = data
            .as_ref()
            .take_enum()
            .expect("should never be a struct");

        let as_arms = variants
            .iter()
            .map(|v| {
                let c_joined = join_c_name_and_variant(&c_name.to_string(), &v.c_variant);
                let v_ident = &v.ident;

                quote! {
                    #rust_name::#v_ident => #c_joined,
                }
            })
            .collect::<Vec<_>>();

        let try_from_arms = variants
            .into_iter()
            .map(|v| {
                let c_joined = join_c_name_and_variant(&c_name.to_string(), &v.c_variant);
                let v_ident = &v.ident;

                quote! {
                    #c_joined => Ok(#rust_name::#v_ident),
                }
            })
            .collect::<Vec<_>>();

        tokens.extend(quote! {
            impl #rust_name {
                /// Returns the C enum variant equivalent for the given Rust enum variant
                pub fn as_c(&self) -> #c_name {
                    match *self {
                        #(#as_arms)*
                    }
                }
            }

            impl ::std::convert::TryFrom<#c_name> for #rust_name {
                type Error = NvmlError;

                fn try_from(data: #c_name) -> Result<Self, Self::Error> {
                    match data {
                        #(#try_from_arms)*
                        _ => Err(NvmlError::UnexpectedVariant(data)),
                    }
                }
            }
        });
    }
}

/// Handles parsing attributes on enum variants
#[derive(Debug, FromVariant)]
#[darling(attributes(wrap))]
struct VariantReceiver {
    ident: Ident,
    /// The ident of the C enum variant this Rust variant maps to
    c_variant: String
}

#[proc_macro_derive(EnumWrapper, attributes(wrap))]
pub fn wrapcenum_derive(input: proc_macro::TokenStream) -> proc_macro::TokenStream {
    let ast = syn::parse(input).unwrap();
    let receiver = EnumReceiver::from_derive_input(&ast).unwrap();

    quote!(#receiver).into()
}
