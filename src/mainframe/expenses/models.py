from django.db import models

from mainframe.core.models import TimeStampedModel
from mainframe.finance.models import DECIMAL_DEFAULT_KWARGS

USER_MODEL = "api_user.User"


class Car(TimeStampedModel):
    name = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name


class Debt(models.Model):
    amount = models.DecimalField(**DECIMAL_DEFAULT_KWARGS)
    currency = models.CharField(max_length=3)
    expense = models.ForeignKey(
        "expenses.Expense",
        on_delete=models.CASCADE,
        related_name="debts",
    )
    user = models.ForeignKey(
        USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name="debts",
    )

    def __str__(self):
        return f"{self.user} owes {self.amount} {self.currency}"


class Expense(TimeStampedModel):
    payer = models.ForeignKey(USER_MODEL, on_delete=models.DO_NOTHING)
    amount = models.DecimalField(**DECIMAL_DEFAULT_KWARGS)
    currency = models.CharField(max_length=3)
    date = models.DateField()
    description = models.CharField(max_length=256, default="")

    class Meta:
        ordering = ("-date",)


class ExpenseGroup(TimeStampedModel):
    created_by = models.ForeignKey(
        USER_MODEL,
        on_delete=models.DO_NOTHING,
        related_name="created_groups",
    )
    name = models.CharField(max_length=100, unique=True)
    users = models.ManyToManyField(
        USER_MODEL,
        blank=True,
        related_name="expense_groups",
    )


class ServiceEntry(TimeStampedModel):
    car = models.ForeignKey(
        Car, on_delete=models.CASCADE, related_name="service_entries"
    )
    currency = models.CharField(max_length=3, blank=True, default="RON")
    date = models.DateField()
    description = models.TextField()
    price = models.DecimalField(**DECIMAL_DEFAULT_KWARGS)

    class Meta:
        ordering = ("-date",)
        constraints = (
            models.UniqueConstraint(
                name="%(app_label)s_%(class)s_car_date_uniq",
                fields=("car", "date", "description"),
            ),
        )

    def __str__(self):
        return f"{self.car} - {self.date} {self.description}"
