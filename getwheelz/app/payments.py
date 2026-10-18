"""Helpers for the DEMO payment feature. No real money moves and no payment gateway is called.

Safety rules kept even in a demo:
  * the full card number and the CVV are validated and then thrown away, never stored or logged
  * only the method plus a masked detail ("Visa •••• 4242") is saved with the payment
"""
import re
import secrets
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_BILL = Decimal('1000000.00')

BANKS = [
    'State Bank of India', 'HDFC Bank', 'ICICI Bank', 'Axis Bank',
    'Kotak Mahindra Bank', 'Punjab National Bank', 'Bank of Baroda', 'Canara Bank',
]

METHODS = ('card', 'upi', 'netbanking')

# Demo "test" inputs that are declined on purpose, so the failure path can be tried.
DECLINE_CARD = '4000000000000002'
DECLINE_UPI = 'fail@upi'


# ----------------------------------------------------------------------------- money
def money(amount):
    """Decimal -> '₹1,250' (or '₹1,250.50'); None -> ''."""
    if amount is None:
        return ''
    amount = Decimal(amount)
    text = f'{amount:,.2f}'
    return '₹' + (text[:-3] if text.endswith('.00') else text)


def parse_price(text):
    """First number found in a free-text price such as '₹500–800' or 'Rs. 1,200' -> Decimal, else None."""
    match = re.search(r'\d[\d,]*(?:\.\d+)?', text or '')
    if not match:
        return None
    try:
        value = Decimal(match.group(0).replace(',', ''))
    except InvalidOperation:
        return None
    if not (0 < value <= MAX_BILL):
        return None
    return value.quantize(Decimal('0.01'))


def amount_due(bill, price_range):
    """What the customer pays: the owner's bill if set, else an estimate from the listed price.

    Returns (Decimal or None, 'bill' | 'estimate' | None).
    """
    if bill is not None:
        return Decimal(bill).quantize(Decimal('0.01')), 'bill'
    estimate = parse_price(price_range)
    if estimate is not None:
        return estimate, 'estimate'
    return None, None


def parse_bill_input(raw):
    """Owner typed an amount. '' -> (None, None) means "clear it". Returns (Decimal|None, error|None)."""
    raw = (raw or '').strip().replace(',', '')
    if raw == '':
        return None, None
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None, 'Please enter the bill as a number, for example 1500.'
    if not value.is_finite() or not (Decimal('1') <= value <= MAX_BILL):
        return None, 'The bill must be between ₹1 and ₹10,00,000.'
    return value.quantize(Decimal('0.01')), None


# ----------------------------------------------------------------------------- card
def luhn_ok(number):
    total, flip = 0, False
    for ch in reversed(number):
        d = int(ch)
        if flip:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        flip = not flip
    return total % 10 == 0


def card_brand(number):
    if number.startswith('4'):
        return 'Visa'
    if re.match(r'^(5[1-5]|2(2[2-9]|[3-6]\d|7[01]|720))', number):
        return 'Mastercard'
    if number[:2] in ('34', '37'):
        return 'Amex'
    if number.startswith(('60', '65', '81', '82')):
        return 'RuPay'
    return 'Card'


def validate_card(name, number, expiry, cvv, today=None):
    """Returns (errors dict, cleaned dict). `cleaned` holds only what is safe to keep."""
    today = today or date.today()
    errors = {}

    name = ' '.join((name or '').split())
    if len(name) < 2 or len(name) > 60 or sum(c.isalpha() for c in name) < 2 or any(c.isdigit() for c in name):
        errors['name'] = "Enter the name as it appears on the card."

    digits = re.sub(r'[\s-]', '', number or '')
    if not digits.isdigit() or not (13 <= len(digits) <= 19) or not luhn_ok(digits):
        errors['number'] = 'Enter a valid card number.'

    match = re.fullmatch(r'\s*(\d{1,2})\s*[/-]?\s*(\d{2}|\d{4})\s*', expiry or '')
    month = year = None
    if match:
        month, year = int(match.group(1)), int(match.group(2))
        year += 2000 if year < 100 else 0
    if not match or not (1 <= month <= 12) or (year, month) < (today.year, today.month) or year > today.year + 25:
        errors['expiry'] = 'Enter a valid, unexpired date as MM/YY.'

    cvv = (cvv or '').strip()
    expected = 4 if digits[:2] in ('34', '37') else 3
    if not cvv.isdigit() or len(cvv) != expected:
        errors['cvv'] = f'Enter the {expected}-digit security code.'

    cleaned = {}
    if not errors:
        cleaned = {'digits': digits, 'detail': f'{card_brand(digits)} •••• {digits[-4:]}'}
    return errors, cleaned


# ----------------------------------------------------------------------------- upi / net banking
def validate_upi(upi):
    upi = (upi or '').strip()
    if not re.fullmatch(r'[A-Za-z0-9._\-]{2,64}@[A-Za-z][A-Za-z0-9]{1,31}', upi):
        return {'upi': 'Enter a valid UPI ID, for example name@bank.'}, {}
    upi = upi.lower()
    name, handle = upi.split('@')
    return {}, {'upi': upi, 'detail': f'{name[:2]}•••@{handle}'}


def validate_bank(bank):
    if bank not in BANKS:
        return {'bank': 'Please choose your bank.'}, {}
    return {}, {'detail': bank}


# ----------------------------------------------------------------------------- the pretend gateway
def process_demo_payment(method, cleaned):
    """Pretend to charge. Returns (ok, message). Only the two test inputs above are declined."""
    if method == 'card' and cleaned.get('digits') == DECLINE_CARD:
        return False, 'Your card was declined. (Demo: this is the test card that always fails.)'
    if method == 'upi' and cleaned.get('upi') == DECLINE_UPI:
        return False, 'The UPI request was declined. (Demo: this is the test ID that always fails.)'
    return True, ''


def new_reference():
    return 'GW-' + secrets.token_hex(4).upper()