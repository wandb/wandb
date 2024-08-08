use darling::{util::parse_expr, FromDeriveInput};
use syn::{parse_quote, Expr};

#[derive(FromDeriveInput)]
#[darling(attributes(demo))]
pub struct Receiver {
    #[darling(with = parse_expr::preserve_str_literal, map = Some)]
    example1: Option<Expr>,
}

fn main() {
    let input = Receiver::from_derive_input(&parse_quote! {
        #[demo(example1 = test::path)]
        struct Example;
    })
    .unwrap();

    assert_eq!(input.example1, Some(parse_quote!(test::path)));
}
