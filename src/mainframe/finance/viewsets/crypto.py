import logging

from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from mainframe.clients.finance.crypto import (
    CryptoImportError,
    CryptoPnLImporter,
    CryptoTransactionsImporter,
)
from mainframe.finance.models import CryptoPnL, CryptoTransaction
from mainframe.finance.serializers import (
    CryptoPnLSerializer,
    CryptoTransactionSerializer,
)
from mainframe.finance.viewsets.mixins import PnlActionModelViewSet


class CryptoViewSet(PnlActionModelViewSet):
    permission_classes = (IsAdminUser,)
    pnl_importer_class = CryptoPnLImporter
    pnl_importer_error_class = CryptoImportError
    pnl_model_class = CryptoPnL
    pnl_serializer_class = CryptoPnLSerializer
    queryset = CryptoTransaction.objects.all()
    serializer_class = CryptoTransactionSerializer

    def create(self, request, *args, **kwargs):
        file = request.FILES["file"]
        logger = logging.getLogger(__name__)
        try:
            CryptoTransactionsImporter(file, logger).run()
        except CryptoImportError as e:
            logger.error("Could not process file. (%s)", e)
            return Response(
                f"Invalid file: {file.name}", status=status.HTTP_400_BAD_REQUEST
            )
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if currency := self.request.query_params.getlist("currency"):
            queryset = queryset.filter(currency__in=currency)
        if symbol := self.request.query_params.getlist("symbol"):
            queryset = queryset.filter(symbol__in=symbol)
        if transaction_type := self.request.query_params.getlist("type"):
            queryset = queryset.filter(type__in=transaction_type)
        return queryset

    def list(self, request, *args, **kwargs):
        def normalize_type(type_display):
            return type_display.replace(" -", "").replace(" ", "_")

        response = super().list(request, *args, **kwargs)
        currencies = (
            CryptoTransaction.objects.values_list("currency", flat=True)
            .exclude(currency="")
            .distinct("currency")
            .order_by("currency")
        )
        symbols = (
            CryptoTransaction.objects.filter(symbol__isnull=False)
            .values_list("symbol", flat=True)
            .distinct("symbol")
            .order_by("symbol")
        )
        response.data["currencies"] = currencies
        response.data["symbols"] = symbols
        aggregations = CryptoTransaction.objects.aggregate(
            **{
                f"{normalize_type(_type_display)}_total_{currency}": Sum(
                    "value", filter=Q(type=_type, currency=currency)
                )
                for _type, _type_display in CryptoTransaction.TYPE_CHOICES
                for currency in currencies
            },
            **{
                f"{normalize_type(_type_display)}_count_{currency}": Count(
                    "id", filter=Q(type=_type, currency=currency)
                )
                for _type, _type_display in CryptoTransaction.TYPE_CHOICES
                for currency in currencies
            },
            count_EUR=Count("id", filter=Q(currency="EUR")),
            count_USD=Count("id", filter=Q(currency="USD")),
            count_RON=Count("id", filter=Q(currency="RON")),
            **{
                f"{symbol}_quantity": Sum(
                    "quantity",
                    filter=Q(
                        symbol=symbol,
                        type=CryptoTransaction.TYPE_LEARN_REWARD,
                        quantity__isnull=False,
                    ),
                    default=0,
                )
                - Sum(
                    "quantity",
                    filter=Q(
                        symbol=symbol,
                        type=CryptoTransaction.TYPE_RECEIVE,
                        quantity__isnull=False,
                    ),
                    default=0,
                )
                for symbol in symbols
            },
        )
        response.data["aggregations"] = {
            currency: {
                "counts": [
                    {"type": "total", "value": aggregations[f"count_{currency}"]},
                    *[
                        {"type": k.replace(f"_count_{currency}", ""), "value": v}
                        for (k, v) in aggregations.items()
                        if k.endswith(f"_count_{currency}")
                    ],
                ],
                "totals": [
                    {"type": k.replace(f"_total_{currency}", ""), "value": v}
                    for (k, v) in aggregations.items()
                    if k.endswith(f"_total_{currency}")
                ],
            }
            for currency in currencies
        }
        response.data["aggregations"]["current"] = self.filter_queryset(
            self.get_queryset()
        ).aggregate(
            **{
                f"total_{currency}": Sum("value", filter=Q(currency=currency))
                for currency in currencies
            }
        )
        response.data["aggregations"]["quantities"] = [
            {"symbol": k.replace("_quantity", ""), "value": v}
            for (k, v) in aggregations.items()
            if k.endswith("_quantity") and v
        ]
        response.data["transactions_count"] = CryptoTransaction.objects.count()
        response.data["types"] = CryptoTransaction.TYPE_CHOICES
        return response
