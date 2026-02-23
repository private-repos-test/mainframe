import logging

from django.db.models import Count, Q, Sum
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from mainframe.clients.finance.stocks import (
    StockImportError,
    StockPnLImporter,
    StockTransactionsImporter,
)
from mainframe.finance.models import PnL, StockTransaction
from mainframe.finance.serializers import PnLSerializer, StockTransactionSerializer
from mainframe.finance.viewsets.mixins import PnlActionModelViewSet

logger = logging.getLogger(__name__)


class StocksViewSet(PnlActionModelViewSet):
    permission_classes = (IsAdminUser,)
    pnl_importer_class = StockPnLImporter
    pnl_importer_error_class = StockImportError
    pnl_model_class = PnL
    pnl_serializer_class = PnLSerializer
    queryset = StockTransaction.objects.all()
    serializer_class = StockTransactionSerializer

    def create(self, request, *args, **kwargs):
        file = request.FILES["file"]
        try:
            StockTransactionsImporter(file, logger).run()
        except StockImportError as e:
            logger.error("Could not process file. (%s)", e)
            return Response(f"Invalid file: {file}", status.HTTP_400_BAD_REQUEST)
        return self.list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = super().get_queryset()
        if currency := self.request.query_params.getlist("currency"):
            queryset = queryset.filter(currency__in=currency)
        if ticker := self.request.query_params.getlist("ticker"):
            queryset = queryset.filter(ticker__in=ticker)
        if transaction_type := self.request.query_params.getlist("type"):
            queryset = queryset.filter(type__in=transaction_type)
        return queryset

    def list(self, request, *args, **kwargs):
        def normalize_type(type_display):
            return type_display.replace(" -", "").replace(" ", "_")

        response = super().list(request, *args, **kwargs)
        currencies = (
            StockTransaction.objects.values_list("currency", flat=True)
            .distinct("currency")
            .order_by("currency")
        )
        tickers = (
            StockTransaction.objects.filter(ticker__isnull=False)
            .values_list("ticker", flat=True)
            .distinct("ticker")
            .order_by("ticker")
        )
        response.data["currencies"] = currencies
        response.data["tickers"] = tickers
        aggregations = StockTransaction.objects.aggregate(
            **{
                f"{normalize_type(_type_display)}_total_{currency}": Sum(
                    "total_amount", filter=Q(type=_type, currency=currency)
                )
                for _type, _type_display in StockTransaction.TYPE_CHOICES
                for currency in currencies
            },
            **{
                f"{normalize_type(_type_display)}_count_{currency}": Count(
                    "id", filter=Q(type=_type, currency=currency)
                )
                for _type, _type_display in StockTransaction.TYPE_CHOICES
                for currency in currencies
            },
            count_EUR=Count("id", filter=Q(currency="EUR")),
            count_USD=Count("id", filter=Q(currency="USD")),
            **{
                f"{ticker}_quantity": Sum(
                    "quantity",
                    filter=Q(
                        ticker=ticker,
                        type=StockTransaction.TYPE_BUY_MARKET,
                        quantity__isnull=False,
                    ),
                    default=0,
                )
                - Sum(
                    "quantity",
                    filter=Q(
                        ticker=ticker,
                        type=StockTransaction.TYPE_SELL_MARKET,
                        quantity__isnull=False,
                    ),
                    default=0,
                )
                for ticker in tickers
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
                f"total_{currency}": Sum("total_amount", filter=Q(currency=currency))
                for currency in currencies
            }
        )
        response.data["aggregations"]["quantities"] = [
            {"ticker": k.replace("_quantity", ""), "value": v}
            for (k, v) in aggregations.items()
            if k.endswith("_quantity") and v
        ]
        response.data["transactions_count"] = StockTransaction.objects.count()
        response.data["types"] = StockTransaction.TYPE_CHOICES
        return response
