from datetime import datetime
from decimal import Decimal
from functools import cached_property

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from pypdf import PdfReader

from mainframe.finance.models import Payment, Timetable
from mainframe.finance.tasks import backup_finance_model

FROM_ACCOUNT = "Din contul"


class PaymentImportError(Exception): ...


def normalize_amount(amount):
    return Decimal(amount.replace(".", "").replace(",", "."))


def parse_date(day, month, year):
    months = [
        "ianuarie",
        "februarie",
        "martie",
        "aprilie",
        "mai",
        "iunie",
        "iulie",
        "august",
        "septembrie",
        "octombrie",
        "noiembrie",
        "decembrie",
    ]
    return datetime(year=int(year), month=months.index(month) + 1, day=int(day)).date()


def parse_installment(rows):
    payment_type = "Rata credit"
    row = rows.pop(0).replace(f"{payment_type}", "")
    day, month, year, total, remaining = row.split()
    validate_starts_with(rows.pop(0), payment_type, "Data", 1)
    principal = validate_starts_with(rows.pop(0), payment_type, "Principal", 2)
    interest = validate_starts_with(rows.pop(0), payment_type, "Dobanda", 3)
    additional_data = {
        "from": validate_starts_with(rows.pop(0), payment_type, FROM_ACCOUNT, 4)
    }
    return Payment(
        additional_data=additional_data,
        date=parse_date(day, month, year),
        interest=normalize_amount(interest),
        principal=normalize_amount(principal),
        remaining=normalize_amount(remaining),
        total=normalize_amount(total),
    )


def parse_interest(rows):
    payment_type = "Dobanda datorata"
    row = rows.pop(0).replace(f"{payment_type}", "")
    day, month, year, total, remaining = row.split()
    account = validate_starts_with(rows.pop(0), payment_type, FROM_ACCOUNT, 1)
    interest = validate_starts_with(rows.pop(0), payment_type, "Dobanda", 2)
    details = validate_starts_with(rows.pop(0), payment_type, "Detalii", 3)
    reference = validate_starts_with(rows.pop(0), payment_type, "Referinta", 4)
    return Payment(
        additional_data={"details": details, "from": account},
        date=parse_date(day, month, year),
        interest=normalize_amount(interest),
        reference=reference,
        remaining=normalize_amount(remaining),
        total=normalize_amount(total),
    )


class PaymentsImporter:
    def __init__(self, file, logger):
        self.file = file
        self.logger = logger

    @cached_property
    def timetables(self):
        return Timetable.objects.all()

    def extract_payments(self, pages):
        payments = []
        for page in pages:
            header = "BalantaDebit CreditDetalii tranzactieData"
            contents = page.extract_text().split(header)[1].strip().split("\n \n")[0]
            rows = [
                r for r in contents.split("\n")[:-1] if "Alocare fonduri" not in r and r
            ]
            payments.extend(self.parse_rows(rows))
        return payments

    def run(self):
        reader = PdfReader(self.file)
        try:
            payments = self.extract_payments(reader.pages)
        except (IndexError, ValueError) as e:
            raise PaymentImportError("Could not extract payments") from e
        try:
            Payment.objects.bulk_create(payments, ignore_conflicts=True)
        except (IntegrityError, ValidationError) as e:
            self.logger.error(str(e))
            raise PaymentImportError from e

        backup_finance_model(model="Payment")

    def parse_prepayment(self, rows):
        payment_type = "Rambursare anticipata de principal"
        row = rows.pop(0).replace(f"{payment_type}", "")
        day, month, year, total, remaining = row.split()
        date = parse_date(day, month, year)
        validate_starts_with(rows.pop(0), payment_type, "Data", 1)
        additional_data = {
            "from": validate_starts_with(rows.pop(0), payment_type, FROM_ACCOUNT, 2),
            "details": validate_starts_with(rows.pop(0), payment_type, "Detalii", 3),
        }
        reference = validate_starts_with(rows.pop(0), payment_type, "Referinta", 4)
        total = normalize_amount(total)
        return Payment(
            additional_data=additional_data,
            date=date,
            is_prepayment=True,
            principal=total,
            reference=reference,
            remaining=normalize_amount(remaining),
            saved=self.parse_saved(date, total),
            total=total,
        )

    def parse_rows(self, rows):
        payments = []
        while rows:
            if rows[0].startswith("Rata credit"):
                payments.append(parse_installment(rows))
            elif rows[0].startswith("Rambursare anticipata de principal"):
                payments.append(self.parse_prepayment(rows))
            elif rows[0].startswith("Dobanda datorata"):
                payments.append(parse_interest(rows))
            else:
                raise ValidationError(f"Unexpected row type: {rows[0]}")
        return payments

    def parse_saved(self, date, principal):
        timetable = None
        for t in self.timetables:  # timetables ordered by date descending
            if t.date < date:  # first timetable before this payment
                timetable = t
                break
        if not timetable:
            return 0

        amount, saved = Decimal(0), Decimal(0)
        for _, payment in enumerate(timetable.amortization_table):
            payment_principal = Decimal(payment["principal"])
            if amount + payment_principal > principal:
                break
            amount += payment_principal
            saved += Decimal(payment["interest"]) + Decimal(payment["insurance"])

        return saved


def validate_starts_with(row, payment_type, expected_field, line_no):
    if not row.startswith(f"{expected_field}:"):
        raise PaymentImportError(
            f"Expected <{payment_type}> line #{line_no} to be <{expected_field}...>."
            f" Found <{row}> instead"
        )
    return row.replace(f"{expected_field}:", "").strip()
