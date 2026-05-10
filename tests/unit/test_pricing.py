"""Unit tests for pure pricing functions in app.py — no DB, no network."""
import pytest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app import calculate_discounted_price, calculate_order_total, apply_vat, validate_stock


# --- calculate_discounted_price ---

def test_zero_discount_returns_original_price():
    assert calculate_discounted_price(100.0, 0) == 100.0


def test_ten_percent_discount():
    assert calculate_discounted_price(100.0, 10) == 90.0


def test_fifty_percent_discount():
    assert calculate_discounted_price(200.0, 50) == 100.0


def test_hundred_percent_discount_is_zero():
    assert calculate_discounted_price(100.0, 100) == 0.0


def test_discount_rounds_to_two_decimal_places():
    assert calculate_discounted_price(9.99, 10) == 8.99


def test_discount_below_zero_raises():
    with pytest.raises(ValueError, match="discount_pct"):
        calculate_discounted_price(100.0, -1)


def test_discount_above_100_raises():
    with pytest.raises(ValueError, match="discount_pct"):
        calculate_discounted_price(100.0, 101)


def test_discount_exactly_100_is_allowed():
    assert calculate_discounted_price(50.0, 100) == 0.0


def test_discount_fractional_percent():
    assert calculate_discounted_price(100.0, 7.5) == 92.5


def test_discount_on_zero_price():
    assert calculate_discounted_price(0.0, 20) == 0.0


# --- calculate_order_total ---

def test_order_total_single_unit():
    assert calculate_order_total(100.0, 0, 1) == 100.0


def test_order_total_multiple_units():
    assert calculate_order_total(50.0, 0, 3) == 150.0


def test_order_total_with_discount():
    assert calculate_order_total(100.0, 10, 2) == 180.0


def test_order_total_zero_quantity_raises():
    with pytest.raises(ValueError, match="quantity"):
        calculate_order_total(100.0, 0, 0)


def test_order_total_negative_quantity_raises():
    with pytest.raises(ValueError, match="quantity"):
        calculate_order_total(100.0, 0, -1)


def test_order_total_rounds_correctly():
    assert calculate_order_total(9.99, 10, 3) == 26.97


# --- apply_vat ---

def test_vat_default_rate_twenty_percent():
    assert apply_vat(100.0) == 120.0


def test_vat_zero_rate():
    assert apply_vat(100.0, 0.0) == 100.0


def test_vat_custom_rate():
    assert apply_vat(100.0, 0.10) == 110.0


def test_vat_negative_rate_raises():
    with pytest.raises(ValueError, match="VAT rate"):
        apply_vat(100.0, -0.01)


def test_vat_rounds_to_two_decimal_places():
    assert apply_vat(9.99) == 11.99


# --- validate_stock ---

def test_stock_sufficient_exact_match():
    assert validate_stock(10, 10) is True


def test_stock_more_than_enough():
    assert validate_stock(100, 1) is True


def test_stock_insufficient():
    assert validate_stock(5, 6) is False


def test_stock_zero_available():
    assert validate_stock(0, 1) is False


def test_stock_zero_requested_fails():
    assert validate_stock(10, 0) is False


def test_stock_negative_requested_fails():
    assert validate_stock(10, -1) is False
