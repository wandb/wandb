# SPDX-License-Identifier: (Apache-2.0 OR MIT)
# Copyright ijl (2023-2025)

import pytest

import orjson

try:
    import pandas as pd
except ImportError:
    pd = None  # type: ignore

from .util import needs_data, read_fixture_bytes


class TestFragment:
    def test_fragment_fragment_eq(self):
        assert orjson.Fragment(b"{}") != orjson.Fragment(b"{}")

    def test_fragment_fragment_not_mut(self):
        fragment = orjson.Fragment(b"{}")
        with pytest.raises(AttributeError):
            fragment.contents = b"[]"
        assert orjson.dumps(fragment) == b"{}"

    def test_fragment_repr(self):
        assert repr(orjson.Fragment(b"{}")).startswith("<orjson.Fragment object at ")

    def test_fragment_fragment_bytes(self):
        assert orjson.dumps(orjson.Fragment(b"{}")) == b"{}"
        assert orjson.dumps(orjson.Fragment(b"[]")) == b"[]"
        assert orjson.dumps([orjson.Fragment(b"{}")]) == b"[{}]"
        assert orjson.dumps([orjson.Fragment(b'{}"a\\')]) == b'[{}"a\\]'

    def test_fragment_fragment_str(self):
        assert orjson.dumps(orjson.Fragment("{}")) == b"{}"
        assert orjson.dumps(orjson.Fragment("[]")) == b"[]"
        assert orjson.dumps([orjson.Fragment("{}")]) == b"[{}]"
        assert orjson.dumps([orjson.Fragment('{}"a\\')]) == b'[{}"a\\]'

    def test_fragment_fragment_str_empty(self):
        assert orjson.dumps(orjson.Fragment("")) == b""

    def test_fragment_fragment_str_str(self):
        assert orjson.dumps(orjson.Fragment('"str"')) == b'"str"'

    def test_fragment_fragment_str_emoji(self):
        assert orjson.dumps(orjson.Fragment('"🐈"')) == b'"\xf0\x9f\x90\x88"'

    def test_fragment_fragment_str_array(self):
        n = 8096
        obj = [orjson.Fragment('"🐈"')] * n
        ref = b"[" + b",".join(b'"\xf0\x9f\x90\x88"' for _ in range(n)) + b"]"
        assert orjson.dumps(obj) == ref

    def test_fragment_fragment_str_invalid(self):
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps(orjson.Fragment("\ud800"))  # type: ignore

    def test_fragment_fragment_bytes_invalid(self):
        assert orjson.dumps(orjson.Fragment(b"\\ud800")) == b"\\ud800"

    def test_fragment_fragment_none(self):
        with pytest.raises(orjson.JSONEncodeError):
            orjson.dumps([orjson.Fragment(None)])  # type: ignore

    def test_fragment_fragment_args_zero(self):
        with pytest.raises(TypeError):
            orjson.dumps(orjson.Fragment())

    def test_fragment_fragment_args_two(self):
        with pytest.raises(TypeError):
            orjson.dumps(orjson.Fragment(b"{}", None))  # type: ignore

    def test_fragment_fragment_keywords(self):
        with pytest.raises(TypeError):
            orjson.dumps(orjson.Fragment(contents=b"{}"))  # type: ignore

    def test_fragment_fragment_arg_and_keywords(self):
        with pytest.raises(TypeError):
            orjson.dumps(orjson.Fragment(b"{}", contents=b"{}"))  # type: ignore


@pytest.mark.skipif(pd is None, reason="pandas is not installed")
class TestFragmentPandas:
    def test_fragment_pandas(self):
        """
        Fragment pandas.DataFrame.to_json()
        """

        def default(value):
            if isinstance(value, pd.DataFrame):
                return orjson.Fragment(value.to_json(orient="records"))
            raise TypeError

        val = pd.DataFrame({"foo": [1, 2, 3], "bar": [4, 5, 6]})
        assert (
            orjson.dumps({"data": val}, default=default)
            == b'{"data":[{"foo":1,"bar":4},{"foo":2,"bar":5},{"foo":3,"bar":6}]}'
        )


@needs_data
class TestFragmentParsing:
    def _run_test(self, filename: str):
        data = read_fixture_bytes(filename, "parsing")
        orjson.dumps(orjson.Fragment(data))

    def test_fragment_y_array_arraysWithSpace(self):
        self._run_test("y_array_arraysWithSpaces.json")

    def test_fragment_y_array_empty_string(self):
        self._run_test("y_array_empty-string.json")

    def test_fragment_y_array_empty(self):
        self._run_test("y_array_empty.json")

    def test_fragment_y_array_ending_with_newline(self):
        self._run_test("y_array_ending_with_newline.json")

    def test_fragment_y_array_false(self):
        self._run_test("y_array_false.json")

    def test_fragment_y_array_heterogeneou(self):
        self._run_test("y_array_heterogeneous.json")

    def test_fragment_y_array_null(self):
        self._run_test("y_array_null.json")

    def test_fragment_y_array_with_1_and_newline(self):
        self._run_test("y_array_with_1_and_newline.json")

    def test_fragment_y_array_with_leading_space(self):
        self._run_test("y_array_with_leading_space.json")

    def test_fragment_y_array_with_several_null(self):
        self._run_test("y_array_with_several_null.json")

    def test_fragment_y_array_with_trailing_space(self):
        self._run_test("y_array_with_trailing_space.json")

    def test_fragment_y_number(self):
        self._run_test("y_number.json")

    def test_fragment_y_number_0e_1(self):
        self._run_test("y_number_0e+1.json")

    def test_fragment_y_number_0e1(self):
        self._run_test("y_number_0e1.json")

    def test_fragment_y_number_after_space(self):
        self._run_test("y_number_after_space.json")

    def test_fragment_y_number_double_close_to_zer(self):
        self._run_test("y_number_double_close_to_zero.json")

    def test_fragment_y_number_int_with_exp(self):
        self._run_test("y_number_int_with_exp.json")

    def test_fragment_y_number_minus_zer(self):
        self._run_test("y_number_minus_zero.json")

    def test_fragment_y_number_negative_int(self):
        self._run_test("y_number_negative_int.json")

    def test_fragment_y_number_negative_one(self):
        self._run_test("y_number_negative_one.json")

    def test_fragment_y_number_negative_zer(self):
        self._run_test("y_number_negative_zero.json")

    def test_fragment_y_number_real_capital_e(self):
        self._run_test("y_number_real_capital_e.json")

    def test_fragment_y_number_real_capital_e_neg_exp(self):
        self._run_test("y_number_real_capital_e_neg_exp.json")

    def test_fragment_y_number_real_capital_e_pos_exp(self):
        self._run_test("y_number_real_capital_e_pos_exp.json")

    def test_fragment_y_number_real_exponent(self):
        self._run_test("y_number_real_exponent.json")

    def test_fragment_y_number_real_fraction_exponent(self):
        self._run_test("y_number_real_fraction_exponent.json")

    def test_fragment_y_number_real_neg_exp(self):
        self._run_test("y_number_real_neg_exp.json")

    def test_fragment_y_number_real_pos_exponent(self):
        self._run_test("y_number_real_pos_exponent.json")

    def test_fragment_y_number_simple_int(self):
        self._run_test("y_number_simple_int.json")

    def test_fragment_y_number_simple_real(self):
        self._run_test("y_number_simple_real.json")

    def test_fragment_y_object(self):
        self._run_test("y_object.json")

    def test_fragment_y_object_basic(self):
        self._run_test("y_object_basic.json")

    def test_fragment_y_object_duplicated_key(self):
        self._run_test("y_object_duplicated_key.json")

    def test_fragment_y_object_duplicated_key_and_value(self):
        self._run_test("y_object_duplicated_key_and_value.json")

    def test_fragment_y_object_empty(self):
        self._run_test("y_object_empty.json")

    def test_fragment_y_object_empty_key(self):
        self._run_test("y_object_empty_key.json")

    def test_fragment_y_object_escaped_null_in_key(self):
        self._run_test("y_object_escaped_null_in_key.json")

    def test_fragment_y_object_extreme_number(self):
        self._run_test("y_object_extreme_numbers.json")

    def test_fragment_y_object_long_string(self):
        self._run_test("y_object_long_strings.json")

    def test_fragment_y_object_simple(self):
        self._run_test("y_object_simple.json")

    def test_fragment_y_object_string_unicode(self):
        self._run_test("y_object_string_unicode.json")

    def test_fragment_y_object_with_newline(self):
        self._run_test("y_object_with_newlines.json")

    def test_fragment_y_string_1_2_3_bytes_UTF_8_sequence(self):
        self._run_test("y_string_1_2_3_bytes_UTF-8_sequences.json")

    def test_fragment_y_string_accepted_surrogate_pair(self):
        self._run_test("y_string_accepted_surrogate_pair.json")

    def test_fragment_y_string_accepted_surrogate_pairs(self):
        self._run_test("y_string_accepted_surrogate_pairs.json")

    def test_fragment_y_string_allowed_escape(self):
        self._run_test("y_string_allowed_escapes.json")

    def test_fragment_y_string_backslash_and_u_escaped_zer(self):
        self._run_test("y_string_backslash_and_u_escaped_zero.json")

    def test_fragment_y_string_backslash_doublequote(self):
        self._run_test("y_string_backslash_doublequotes.json")

    def test_fragment_y_string_comment(self):
        self._run_test("y_string_comments.json")

    def test_fragment_y_string_double_escape_a(self):
        self._run_test("y_string_double_escape_a.json")

    def test_fragment_y_string_double_escape_(self):
        self._run_test("y_string_double_escape_n.json")

    def test_fragment_y_string_escaped_control_character(self):
        self._run_test("y_string_escaped_control_character.json")

    def test_fragment_y_string_escaped_noncharacter(self):
        self._run_test("y_string_escaped_noncharacter.json")

    def test_fragment_y_string_in_array(self):
        self._run_test("y_string_in_array.json")

    def test_fragment_y_string_in_array_with_leading_space(self):
        self._run_test("y_string_in_array_with_leading_space.json")

    def test_fragment_y_string_last_surrogates_1_and_2(self):
        self._run_test("y_string_last_surrogates_1_and_2.json")

    def test_fragment_y_string_nbsp_uescaped(self):
        self._run_test("y_string_nbsp_uescaped.json")

    def test_fragment_y_string_nonCharacterInUTF_8_U_10FFFF(self):
        self._run_test("y_string_nonCharacterInUTF-8_U+10FFFF.json")

    def test_fragment_y_string_nonCharacterInUTF_8_U_FFFF(self):
        self._run_test("y_string_nonCharacterInUTF-8_U+FFFF.json")

    def test_fragment_y_string_null_escape(self):
        self._run_test("y_string_null_escape.json")

    def test_fragment_y_string_one_byte_utf_8(self):
        self._run_test("y_string_one-byte-utf-8.json")

    def test_fragment_y_string_pi(self):
        self._run_test("y_string_pi.json")

    def test_fragment_y_string_reservedCharacterInUTF_8_U_1BFFF(self):
        self._run_test("y_string_reservedCharacterInUTF-8_U+1BFFF.json")

    def test_fragment_y_string_simple_ascii(self):
        self._run_test("y_string_simple_ascii.json")

    def test_fragment_y_string_space(self):
        self._run_test("y_string_space.json")

    def test_fragment_y_string_surrogates_U_1D11E_MUSICAL_SYMBOL_G_CLEF(self):
        self._run_test("y_string_surrogates_U+1D11E_MUSICAL_SYMBOL_G_CLEF.json")

    def test_fragment_y_string_three_byte_utf_8(self):
        self._run_test("y_string_three-byte-utf-8.json")

    def test_fragment_y_string_two_byte_utf_8(self):
        self._run_test("y_string_two-byte-utf-8.json")

    def test_fragment_y_string_u_2028_line_sep(self):
        self._run_test("y_string_u+2028_line_sep.json")

    def test_fragment_y_string_u_2029_par_sep(self):
        self._run_test("y_string_u+2029_par_sep.json")

    def test_fragment_y_string_uEscape(self):
        self._run_test("y_string_uEscape.json")

    def test_fragment_y_string_uescaped_newline(self):
        self._run_test("y_string_uescaped_newline.json")

    def test_fragment_y_string_unescaped_char_delete(self):
        self._run_test("y_string_unescaped_char_delete.json")

    def test_fragment_y_string_unicode(self):
        self._run_test("y_string_unicode.json")

    def test_fragment_y_string_unicodeEscapedBackslash(self):
        self._run_test("y_string_unicodeEscapedBackslash.json")

    def test_fragment_y_string_unicode_2(self):
        self._run_test("y_string_unicode_2.json")

    def test_fragment_y_string_unicode_U_10FFFE_nonchar(self):
        self._run_test("y_string_unicode_U+10FFFE_nonchar.json")

    def test_fragment_y_string_unicode_U_1FFFE_nonchar(self):
        self._run_test("y_string_unicode_U+1FFFE_nonchar.json")

    def test_fragment_y_string_unicode_U_200B_ZERO_WIDTH_SPACE(self):
        self._run_test("y_string_unicode_U+200B_ZERO_WIDTH_SPACE.json")

    def test_fragment_y_string_unicode_U_2064_invisible_plu(self):
        self._run_test("y_string_unicode_U+2064_invisible_plus.json")

    def test_fragment_y_string_unicode_U_FDD0_nonchar(self):
        self._run_test("y_string_unicode_U+FDD0_nonchar.json")

    def test_fragment_y_string_unicode_U_FFFE_nonchar(self):
        self._run_test("y_string_unicode_U+FFFE_nonchar.json")

    def test_fragment_y_string_unicode_escaped_double_quote(self):
        self._run_test("y_string_unicode_escaped_double_quote.json")

    def test_fragment_y_string_utf8(self):
        self._run_test("y_string_utf8.json")

    def test_fragment_y_string_with_del_character(self):
        self._run_test("y_string_with_del_character.json")

    def test_fragment_y_structure_lonely_false(self):
        self._run_test("y_structure_lonely_false.json")

    def test_fragment_y_structure_lonely_int(self):
        self._run_test("y_structure_lonely_int.json")

    def test_fragment_y_structure_lonely_negative_real(self):
        self._run_test("y_structure_lonely_negative_real.json")

    def test_fragment_y_structure_lonely_null(self):
        self._run_test("y_structure_lonely_null.json")

    def test_fragment_y_structure_lonely_string(self):
        self._run_test("y_structure_lonely_string.json")

    def test_fragment_y_structure_lonely_true(self):
        self._run_test("y_structure_lonely_true.json")

    def test_fragment_y_structure_string_empty(self):
        self._run_test("y_structure_string_empty.json")

    def test_fragment_y_structure_trailing_newline(self):
        self._run_test("y_structure_trailing_newline.json")

    def test_fragment_y_structure_true_in_array(self):
        self._run_test("y_structure_true_in_array.json")

    def test_fragment_y_structure_whitespace_array(self):
        self._run_test("y_structure_whitespace_array.json")

    def test_fragment_n_array_1_true_without_comma(self):
        self._run_test("n_array_1_true_without_comma.json")

    def test_fragment_n_array_a_invalid_utf8(self):
        self._run_test("n_array_a_invalid_utf8.json")

    def test_fragment_n_array_colon_instead_of_comma(self):
        self._run_test("n_array_colon_instead_of_comma.json")

    def test_fragment_n_array_comma_after_close(self):
        self._run_test("n_array_comma_after_close.json")

    def test_fragment_n_array_comma_and_number(self):
        self._run_test("n_array_comma_and_number.json")

    def test_fragment_n_array_double_comma(self):
        self._run_test("n_array_double_comma.json")

    def test_fragment_n_array_double_extra_comma(self):
        self._run_test("n_array_double_extra_comma.json")

    def test_fragment_n_array_extra_close(self):
        self._run_test("n_array_extra_close.json")

    def test_fragment_n_array_extra_comma(self):
        self._run_test("n_array_extra_comma.json")

    def test_fragment_n_array_incomplete(self):
        self._run_test("n_array_incomplete.json")

    def test_fragment_n_array_incomplete_invalid_value(self):
        self._run_test("n_array_incomplete_invalid_value.json")

    def test_fragment_n_array_inner_array_no_comma(self):
        self._run_test("n_array_inner_array_no_comma.json")

    def test_fragment_n_array_invalid_utf8(self):
        self._run_test("n_array_invalid_utf8.json")

    def test_fragment_n_array_items_separated_by_semicol(self):
        self._run_test("n_array_items_separated_by_semicolon.json")

    def test_fragment_n_array_just_comma(self):
        self._run_test("n_array_just_comma.json")

    def test_fragment_n_array_just_minu(self):
        self._run_test("n_array_just_minus.json")

    def test_fragment_n_array_missing_value(self):
        self._run_test("n_array_missing_value.json")

    def test_fragment_n_array_newlines_unclosed(self):
        self._run_test("n_array_newlines_unclosed.json")

    def test_fragment_n_array_number_and_comma(self):
        self._run_test("n_array_number_and_comma.json")

    def test_fragment_n_array_number_and_several_comma(self):
        self._run_test("n_array_number_and_several_commas.json")

    def test_fragment_n_array_spaces_vertical_tab_formfeed(self):
        self._run_test("n_array_spaces_vertical_tab_formfeed.json")

    def test_fragment_n_array_star_inside(self):
        self._run_test("n_array_star_inside.json")

    def test_fragment_n_array_unclosed(self):
        self._run_test("n_array_unclosed.json")

    def test_fragment_n_array_unclosed_trailing_comma(self):
        self._run_test("n_array_unclosed_trailing_comma.json")

    def test_fragment_n_array_unclosed_with_new_line(self):
        self._run_test("n_array_unclosed_with_new_lines.json")

    def test_fragment_n_array_unclosed_with_object_inside(self):
        self._run_test("n_array_unclosed_with_object_inside.json")

    def test_fragment_n_incomplete_false(self):
        self._run_test("n_incomplete_false.json")

    def test_fragment_n_incomplete_null(self):
        self._run_test("n_incomplete_null.json")

    def test_fragment_n_incomplete_true(self):
        self._run_test("n_incomplete_true.json")

    def test_fragment_n_multidigit_number_then_00(self):
        self._run_test("n_multidigit_number_then_00.json")

    def test_fragment_n_number__(self):
        self._run_test("n_number_++.json")

    def test_fragment_n_number_1(self):
        self._run_test("n_number_+1.json")

    def test_fragment_n_number_Inf(self):
        self._run_test("n_number_+Inf.json")

    def test_fragment_n_number_01(self):
        self._run_test("n_number_-01.json")

    def test_fragment_n_number_1_0(self):
        self._run_test("n_number_-1.0..json")

    def test_fragment_n_number_2(self):
        self._run_test("n_number_-2..json")

    def test_fragment_n_number_negative_NaN(self):
        self._run_test("n_number_-NaN.json")

    def test_fragment_n_number_negative_1(self):
        self._run_test("n_number_.-1.json")

    def test_fragment_n_number_2e_3(self):
        self._run_test("n_number_.2e-3.json")

    def test_fragment_n_number_0_1_2(self):
        self._run_test("n_number_0.1.2.json")

    def test_fragment_n_number_0_3e_(self):
        self._run_test("n_number_0.3e+.json")

    def test_fragment_n_number_0_3e(self):
        self._run_test("n_number_0.3e.json")

    def test_fragment_n_number_0_e1(self):
        self._run_test("n_number_0.e1.json")

    def test_fragment_n_number_0_capital_E_(self):
        self._run_test("n_number_0_capital_E+.json")

    def test_fragment_n_number_0_capital_E(self):
        self._run_test("n_number_0_capital_E.json")

    def test_fragment_n_number_0e_(self):
        self._run_test("n_number_0e+.json")

    def test_fragment_n_number_0e(self):
        self._run_test("n_number_0e.json")

    def test_fragment_n_number_1_0e_(self):
        self._run_test("n_number_1.0e+.json")

    def test_fragment_n_number_1_0e_2(self):
        self._run_test("n_number_1.0e-.json")

    def test_fragment_n_number_1_0e(self):
        self._run_test("n_number_1.0e.json")

    def test_fragment_n_number_1_000(self):
        self._run_test("n_number_1_000.json")

    def test_fragment_n_number_1eE2(self):
        self._run_test("n_number_1eE2.json")

    def test_fragment_n_number_2_e_3(self):
        self._run_test("n_number_2.e+3.json")

    def test_fragment_n_number_2_e_3_2(self):
        self._run_test("n_number_2.e-3.json")

    def test_fragment_n_number_2_e3_3(self):
        self._run_test("n_number_2.e3.json")

    def test_fragment_n_number_9_e_(self):
        self._run_test("n_number_9.e+.json")

    def test_fragment_n_number_negative_Inf(self):
        self._run_test("n_number_Inf.json")

    def test_fragment_n_number_NaN(self):
        self._run_test("n_number_NaN.json")

    def test_fragment_n_number_U_FF11_fullwidth_digit_one(self):
        self._run_test("n_number_U+FF11_fullwidth_digit_one.json")

    def test_fragment_n_number_expressi(self):
        self._run_test("n_number_expression.json")

    def test_fragment_n_number_hex_1_digit(self):
        self._run_test("n_number_hex_1_digit.json")

    def test_fragment_n_number_hex_2_digit(self):
        self._run_test("n_number_hex_2_digits.json")

    def test_fragment_n_number_infinity(self):
        self._run_test("n_number_infinity.json")

    def test_fragment_n_number_invalid_(self):
        self._run_test("n_number_invalid+-.json")

    def test_fragment_n_number_invalid_negative_real(self):
        self._run_test("n_number_invalid-negative-real.json")

    def test_fragment_n_number_invalid_utf_8_in_bigger_int(self):
        self._run_test("n_number_invalid-utf-8-in-bigger-int.json")

    def test_fragment_n_number_invalid_utf_8_in_exponent(self):
        self._run_test("n_number_invalid-utf-8-in-exponent.json")

    def test_fragment_n_number_invalid_utf_8_in_int(self):
        self._run_test("n_number_invalid-utf-8-in-int.json")

    def test_fragment_n_number_minus_infinity(self):
        self._run_test("n_number_minus_infinity.json")

    def test_fragment_n_number_minus_sign_with_trailing_garbage(self):
        self._run_test("n_number_minus_sign_with_trailing_garbage.json")

    def test_fragment_n_number_minus_space_1(self):
        self._run_test("n_number_minus_space_1.json")

    def test_fragment_n_number_neg_int_starting_with_zer(self):
        self._run_test("n_number_neg_int_starting_with_zero.json")

    def test_fragment_n_number_neg_real_without_int_part(self):
        self._run_test("n_number_neg_real_without_int_part.json")

    def test_fragment_n_number_neg_with_garbage_at_end(self):
        self._run_test("n_number_neg_with_garbage_at_end.json")

    def test_fragment_n_number_real_garbage_after_e(self):
        self._run_test("n_number_real_garbage_after_e.json")

    def test_fragment_n_number_real_with_invalid_utf8_after_e(self):
        self._run_test("n_number_real_with_invalid_utf8_after_e.json")

    def test_fragment_n_number_real_without_fractional_part(self):
        self._run_test("n_number_real_without_fractional_part.json")

    def test_fragment_n_number_starting_with_dot(self):
        self._run_test("n_number_starting_with_dot.json")

    def test_fragment_n_number_with_alpha(self):
        self._run_test("n_number_with_alpha.json")

    def test_fragment_n_number_with_alpha_char(self):
        self._run_test("n_number_with_alpha_char.json")

    def test_fragment_n_number_with_leading_zer(self):
        self._run_test("n_number_with_leading_zero.json")

    def test_fragment_n_object_bad_value(self):
        self._run_test("n_object_bad_value.json")

    def test_fragment_n_object_bracket_key(self):
        self._run_test("n_object_bracket_key.json")

    def test_fragment_n_object_comma_instead_of_col(self):
        self._run_test("n_object_comma_instead_of_colon.json")

    def test_fragment_n_object_double_col(self):
        self._run_test("n_object_double_colon.json")

    def test_fragment_n_object_emoji(self):
        self._run_test("n_object_emoji.json")

    def test_fragment_n_object_garbage_at_end(self):
        self._run_test("n_object_garbage_at_end.json")

    def test_fragment_n_object_key_with_single_quote(self):
        self._run_test("n_object_key_with_single_quotes.json")

    def test_fragment_n_object_lone_continuation_byte_in_key_and_trailing_comma(self):
        self._run_test("n_object_lone_continuation_byte_in_key_and_trailing_comma.json")

    def test_fragment_n_object_missing_col(self):
        self._run_test("n_object_missing_colon.json")

    def test_fragment_n_object_missing_key(self):
        self._run_test("n_object_missing_key.json")

    def test_fragment_n_object_missing_semicol(self):
        self._run_test("n_object_missing_semicolon.json")

    def test_fragment_n_object_missing_value(self):
        self._run_test("n_object_missing_value.json")

    def test_fragment_n_object_no_col(self):
        self._run_test("n_object_no-colon.json")

    def test_fragment_n_object_non_string_key(self):
        self._run_test("n_object_non_string_key.json")

    def test_fragment_n_object_non_string_key_but_huge_number_instead(self):
        self._run_test("n_object_non_string_key_but_huge_number_instead.json")

    def test_fragment_n_object_repeated_null_null(self):
        self._run_test("n_object_repeated_null_null.json")

    def test_fragment_n_object_several_trailing_comma(self):
        self._run_test("n_object_several_trailing_commas.json")

    def test_fragment_n_object_single_quote(self):
        self._run_test("n_object_single_quote.json")

    def test_fragment_n_object_trailing_comma(self):
        self._run_test("n_object_trailing_comma.json")

    def test_fragment_n_object_trailing_comment(self):
        self._run_test("n_object_trailing_comment.json")

    def test_fragment_n_object_trailing_comment_ope(self):
        self._run_test("n_object_trailing_comment_open.json")

    def test_fragment_n_object_trailing_comment_slash_ope(self):
        self._run_test("n_object_trailing_comment_slash_open.json")

    def test_fragment_n_object_trailing_comment_slash_open_incomplete(self):
        self._run_test("n_object_trailing_comment_slash_open_incomplete.json")

    def test_fragment_n_object_two_commas_in_a_row(self):
        self._run_test("n_object_two_commas_in_a_row.json")

    def test_fragment_n_object_unquoted_key(self):
        self._run_test("n_object_unquoted_key.json")

    def test_fragment_n_object_unterminated_value(self):
        self._run_test("n_object_unterminated-value.json")

    def test_fragment_n_object_with_single_string(self):
        self._run_test("n_object_with_single_string.json")

    def test_fragment_n_object_with_trailing_garbage(self):
        self._run_test("n_object_with_trailing_garbage.json")

    def test_fragment_n_single_space(self):
        self._run_test("n_single_space.json")

    def test_fragment_n_string_1_surrogate_then_escape(self):
        self._run_test("n_string_1_surrogate_then_escape.json")

    def test_fragment_n_string_1_surrogate_then_escape_u(self):
        self._run_test("n_string_1_surrogate_then_escape_u.json")

    def test_fragment_n_string_1_surrogate_then_escape_u1(self):
        self._run_test("n_string_1_surrogate_then_escape_u1.json")

    def test_fragment_n_string_1_surrogate_then_escape_u1x(self):
        self._run_test("n_string_1_surrogate_then_escape_u1x.json")

    def test_fragment_n_string_accentuated_char_no_quote(self):
        self._run_test("n_string_accentuated_char_no_quotes.json")

    def test_fragment_n_string_backslash_00(self):
        self._run_test("n_string_backslash_00.json")

    def test_fragment_n_string_escape_x(self):
        self._run_test("n_string_escape_x.json")

    def test_fragment_n_string_escaped_backslash_bad(self):
        self._run_test("n_string_escaped_backslash_bad.json")

    def test_fragment_n_string_escaped_ctrl_char_tab(self):
        self._run_test("n_string_escaped_ctrl_char_tab.json")

    def test_fragment_n_string_escaped_emoji(self):
        self._run_test("n_string_escaped_emoji.json")

    def test_fragment_n_string_incomplete_escape(self):
        self._run_test("n_string_incomplete_escape.json")

    def test_fragment_n_string_incomplete_escaped_character(self):
        self._run_test("n_string_incomplete_escaped_character.json")

    def test_fragment_n_string_incomplete_surrogate(self):
        self._run_test("n_string_incomplete_surrogate.json")

    def test_fragment_n_string_incomplete_surrogate_escape_invalid(self):
        self._run_test("n_string_incomplete_surrogate_escape_invalid.json")

    def test_fragment_n_string_invalid_utf_8_in_escape(self):
        self._run_test("n_string_invalid-utf-8-in-escape.json")

    def test_fragment_n_string_invalid_backslash_esc(self):
        self._run_test("n_string_invalid_backslash_esc.json")

    def test_fragment_n_string_invalid_unicode_escape(self):
        self._run_test("n_string_invalid_unicode_escape.json")

    def test_fragment_n_string_invalid_utf8_after_escape(self):
        self._run_test("n_string_invalid_utf8_after_escape.json")

    def test_fragment_n_string_leading_uescaped_thinspace(self):
        self._run_test("n_string_leading_uescaped_thinspace.json")

    def test_fragment_n_string_no_quotes_with_bad_escape(self):
        self._run_test("n_string_no_quotes_with_bad_escape.json")

    def test_fragment_n_string_single_doublequote(self):
        self._run_test("n_string_single_doublequote.json")

    def test_fragment_n_string_single_quote(self):
        self._run_test("n_string_single_quote.json")

    def test_fragment_n_string_single_string_no_double_quote(self):
        self._run_test("n_string_single_string_no_double_quotes.json")

    def test_fragment_n_string_start_escape_unclosed(self):
        self._run_test("n_string_start_escape_unclosed.json")

    def test_fragment_n_string_unescaped_crtl_char(self):
        self._run_test("n_string_unescaped_crtl_char.json")

    def test_fragment_n_string_unescaped_newline(self):
        self._run_test("n_string_unescaped_newline.json")

    def test_fragment_n_string_unescaped_tab(self):
        self._run_test("n_string_unescaped_tab.json")

    def test_fragment_n_string_unicode_CapitalU(self):
        self._run_test("n_string_unicode_CapitalU.json")

    def test_fragment_n_string_with_trailing_garbage(self):
        self._run_test("n_string_with_trailing_garbage.json")

    def test_fragment_n_structure_100000_opening_array(self):
        self._run_test("n_structure_100000_opening_arrays.json.xz")

    def test_fragment_n_structure_U_2060_word_joined(self):
        self._run_test("n_structure_U+2060_word_joined.json")

    def test_fragment_n_structure_UTF8_BOM_no_data(self):
        self._run_test("n_structure_UTF8_BOM_no_data.json")

    def test_fragment_n_structure_angle_bracket_(self):
        self._run_test("n_structure_angle_bracket_..json")

    def test_fragment_n_structure_angle_bracket_null(self):
        self._run_test("n_structure_angle_bracket_null.json")

    def test_fragment_n_structure_array_trailing_garbage(self):
        self._run_test("n_structure_array_trailing_garbage.json")

    def test_fragment_n_structure_array_with_extra_array_close(self):
        self._run_test("n_structure_array_with_extra_array_close.json")

    def test_fragment_n_structure_array_with_unclosed_string(self):
        self._run_test("n_structure_array_with_unclosed_string.json")

    def test_fragment_n_structure_ascii_unicode_identifier(self):
        self._run_test("n_structure_ascii-unicode-identifier.json")

    def test_fragment_n_structure_capitalized_True(self):
        self._run_test("n_structure_capitalized_True.json")

    def test_fragment_n_structure_close_unopened_array(self):
        self._run_test("n_structure_close_unopened_array.json")

    def test_fragment_n_structure_comma_instead_of_closing_brace(self):
        self._run_test("n_structure_comma_instead_of_closing_brace.json")

    def test_fragment_n_structure_double_array(self):
        self._run_test("n_structure_double_array.json")

    def test_fragment_n_structure_end_array(self):
        self._run_test("n_structure_end_array.json")

    def test_fragment_n_structure_incomplete_UTF8_BOM(self):
        self._run_test("n_structure_incomplete_UTF8_BOM.json")

    def test_fragment_n_structure_lone_invalid_utf_8(self):
        self._run_test("n_structure_lone-invalid-utf-8.json")

    def test_fragment_n_structure_lone_open_bracket(self):
        self._run_test("n_structure_lone-open-bracket.json")

    def test_fragment_n_structure_no_data(self):
        self._run_test("n_structure_no_data.json")

    def test_fragment_n_structure_null_byte_outside_string(self):
        self._run_test("n_structure_null-byte-outside-string.json")

    def test_fragment_n_structure_number_with_trailing_garbage(self):
        self._run_test("n_structure_number_with_trailing_garbage.json")

    def test_fragment_n_structure_object_followed_by_closing_object(self):
        self._run_test("n_structure_object_followed_by_closing_object.json")

    def test_fragment_n_structure_object_unclosed_no_value(self):
        self._run_test("n_structure_object_unclosed_no_value.json")

    def test_fragment_n_structure_object_with_comment(self):
        self._run_test("n_structure_object_with_comment.json")

    def test_fragment_n_structure_object_with_trailing_garbage(self):
        self._run_test("n_structure_object_with_trailing_garbage.json")

    def test_fragment_n_structure_open_array_apostrophe(self):
        self._run_test("n_structure_open_array_apostrophe.json")

    def test_fragment_n_structure_open_array_comma(self):
        self._run_test("n_structure_open_array_comma.json")

    def test_fragment_n_structure_open_array_object(self):
        self._run_test("n_structure_open_array_object.json.xz")

    def test_fragment_n_structure_open_array_open_object(self):
        self._run_test("n_structure_open_array_open_object.json")

    def test_fragment_n_structure_open_array_open_string(self):
        self._run_test("n_structure_open_array_open_string.json")

    def test_fragment_n_structure_open_array_string(self):
        self._run_test("n_structure_open_array_string.json")

    def test_fragment_n_structure_open_object(self):
        self._run_test("n_structure_open_object.json")

    def test_fragment_n_structure_open_object_close_array(self):
        self._run_test("n_structure_open_object_close_array.json")

    def test_fragment_n_structure_open_object_comma(self):
        self._run_test("n_structure_open_object_comma.json")

    def test_fragment_n_structure_open_object_open_array(self):
        self._run_test("n_structure_open_object_open_array.json")

    def test_fragment_n_structure_open_object_open_string(self):
        self._run_test("n_structure_open_object_open_string.json")

    def test_fragment_n_structure_open_object_string_with_apostrophe(self):
        self._run_test("n_structure_open_object_string_with_apostrophes.json")

    def test_fragment_n_structure_open_ope(self):
        self._run_test("n_structure_open_open.json")

    def test_fragment_n_structure_single_eacute(self):
        self._run_test("n_structure_single_eacute.json")

    def test_fragment_n_structure_single_star(self):
        self._run_test("n_structure_single_star.json")

    def test_fragment_n_structure_trailing_(self):
        self._run_test("n_structure_trailing_#.json")

    def test_fragment_n_structure_uescaped_LF_before_string(self):
        self._run_test("n_structure_uescaped_LF_before_string.json")

    def test_fragment_n_structure_unclosed_array(self):
        self._run_test("n_structure_unclosed_array.json")

    def test_fragment_n_structure_unclosed_array_partial_null(self):
        self._run_test("n_structure_unclosed_array_partial_null.json")

    def test_fragment_n_structure_unclosed_array_unfinished_false(self):
        self._run_test("n_structure_unclosed_array_unfinished_false.json")

    def test_fragment_n_structure_unclosed_array_unfinished_true(self):
        self._run_test("n_structure_unclosed_array_unfinished_true.json")

    def test_fragment_n_structure_unclosed_object(self):
        self._run_test("n_structure_unclosed_object.json")

    def test_fragment_n_structure_unicode_identifier(self):
        self._run_test("n_structure_unicode-identifier.json")

    def test_fragment_n_structure_whitespace_U_2060_word_joiner(self):
        self._run_test("n_structure_whitespace_U+2060_word_joiner.json")

    def test_fragment_n_structure_whitespace_formfeed(self):
        self._run_test("n_structure_whitespace_formfeed.json")

    def test_fragment_i_number_double_huge_neg_exp(self):
        self._run_test("i_number_double_huge_neg_exp.json")

    def test_fragment_i_number_huge_exp(self):
        self._run_test("i_number_huge_exp.json")

    def test_fragment_i_number_neg_int_huge_exp(self):
        self._run_test("i_number_neg_int_huge_exp.json")

    def test_fragment_i_number_pos_double_huge_exp(self):
        self._run_test("i_number_pos_double_huge_exp.json")

    def test_fragment_i_number_real_neg_overflow(self):
        self._run_test("i_number_real_neg_overflow.json")

    def test_fragment_i_number_real_pos_overflow(self):
        self._run_test("i_number_real_pos_overflow.json")

    def test_fragment_i_number_real_underflow(self):
        self._run_test("i_number_real_underflow.json")

    def test_fragment_i_number_too_big_neg_int(self):
        self._run_test("i_number_too_big_neg_int.json")

    def test_fragment_i_number_too_big_pos_int(self):
        self._run_test("i_number_too_big_pos_int.json")

    def test_fragment_i_number_very_big_negative_int(self):
        self._run_test("i_number_very_big_negative_int.json")

    def test_fragment_i_object_key_lone_2nd_surrogate(self):
        self._run_test("i_object_key_lone_2nd_surrogate.json")

    def test_fragment_i_string_1st_surrogate_but_2nd_missing(self):
        self._run_test("i_string_1st_surrogate_but_2nd_missing.json")

    def test_fragment_i_string_1st_valid_surrogate_2nd_invalid(self):
        self._run_test("i_string_1st_valid_surrogate_2nd_invalid.json")

    def test_fragment_i_string_UTF_16LE_with_BOM(self):
        self._run_test("i_string_UTF-16LE_with_BOM.json")

    def test_fragment_i_string_UTF_8_invalid_sequence(self):
        self._run_test("i_string_UTF-8_invalid_sequence.json")

    def test_fragment_i_string_UTF8_surrogate_U_D800(self):
        self._run_test("i_string_UTF8_surrogate_U+D800.json")

    def test_fragment_i_string_incomplete_surrogate_and_escape_valid(self):
        self._run_test("i_string_incomplete_surrogate_and_escape_valid.json")

    def test_fragment_i_string_incomplete_surrogate_pair(self):
        self._run_test("i_string_incomplete_surrogate_pair.json")

    def test_fragment_i_string_incomplete_surrogates_escape_valid(self):
        self._run_test("i_string_incomplete_surrogates_escape_valid.json")

    def test_fragment_i_string_invalid_lonely_surrogate(self):
        self._run_test("i_string_invalid_lonely_surrogate.json")

    def test_fragment_i_string_invalid_surrogate(self):
        self._run_test("i_string_invalid_surrogate.json")

    def test_fragment_i_string_invalid_utf_8(self):
        self._run_test("i_string_invalid_utf-8.json")

    def test_fragment_i_string_inverted_surrogates_U_1D11E(self):
        self._run_test("i_string_inverted_surrogates_U+1D11E.json")

    def test_fragment_i_string_iso_latin_1(self):
        self._run_test("i_string_iso_latin_1.json")

    def test_fragment_i_string_lone_second_surrogate(self):
        self._run_test("i_string_lone_second_surrogate.json")

    def test_fragment_i_string_lone_utf8_continuation_byte(self):
        self._run_test("i_string_lone_utf8_continuation_byte.json")

    def test_fragment_i_string_not_in_unicode_range(self):
        self._run_test("i_string_not_in_unicode_range.json")

    def test_fragment_i_string_overlong_sequence_2_byte(self):
        self._run_test("i_string_overlong_sequence_2_bytes.json")

    def test_fragment_i_string_overlong_sequence_6_byte(self):
        self._run_test("i_string_overlong_sequence_6_bytes.json")

    def test_fragment_i_string_overlong_sequence_6_bytes_null(self):
        self._run_test("i_string_overlong_sequence_6_bytes_null.json")

    def test_fragment_i_string_truncated_utf_8(self):
        self._run_test("i_string_truncated-utf-8.json")

    def test_fragment_i_string_utf16BE_no_BOM(self):
        self._run_test("i_string_utf16BE_no_BOM.json")

    def test_fragment_i_string_utf16LE_no_BOM(self):
        self._run_test("i_string_utf16LE_no_BOM.json")

    def test_fragment_i_structure_500_nested_array(self):
        self._run_test("i_structure_500_nested_arrays.json.xz")

    def test_fragment_i_structure_UTF_8_BOM_empty_object(self):
        self._run_test("i_structure_UTF-8_BOM_empty_object.json")
