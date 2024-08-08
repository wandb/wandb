use proc_macro2::Ident;
use syn::Path;

use crate::ast::NestedMeta;
use crate::util::PathList;
use crate::{Error, FromField, FromMeta, Result};

use super::ParseAttribute;

/// The `attrs` magic field and attributes that influence its behavior.
#[derive(Debug, Clone)]
pub struct AttrsField {
    /// The ident of the field that will receive the forwarded attributes.
    pub ident: Ident,
    /// Path of the function that will be called to convert the `Vec` of
    /// forwarded attributes into the type expected by the field in `ident`.
    pub with: Option<Path>,
}

impl FromField for AttrsField {
    fn from_field(field: &syn::Field) -> crate::Result<Self> {
        let result = Self {
            ident: field.ident.clone().ok_or_else(|| {
                Error::custom("attributes receiver must be named field").with_span(field)
            })?,
            with: None,
        };

        result.parse_attributes(&field.attrs)
    }
}

impl ParseAttribute for AttrsField {
    fn parse_nested(&mut self, mi: &syn::Meta) -> crate::Result<()> {
        if mi.path().is_ident("with") {
            if self.with.is_some() {
                return Err(Error::duplicate_field_path(mi.path()).with_span(mi));
            }

            self.with = FromMeta::from_meta(mi)?;
            Ok(())
        } else {
            Err(Error::unknown_field_path_with_alts(mi.path(), &["with"]).with_span(mi))
        }
    }
}

/// A rule about which attributes to forward to the generated struct.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ForwardAttrsFilter {
    All,
    Only(PathList),
}

impl ForwardAttrsFilter {
    /// Returns `true` if this will not forward any attributes.
    pub fn is_empty(&self) -> bool {
        match *self {
            ForwardAttrsFilter::All => false,
            ForwardAttrsFilter::Only(ref list) => list.is_empty(),
        }
    }
}

impl FromMeta for ForwardAttrsFilter {
    fn from_word() -> Result<Self> {
        Ok(ForwardAttrsFilter::All)
    }

    fn from_list(nested: &[NestedMeta]) -> Result<Self> {
        Ok(ForwardAttrsFilter::Only(PathList::from_list(nested)?))
    }
}
