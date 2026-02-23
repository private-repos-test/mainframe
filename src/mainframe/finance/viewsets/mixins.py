import logging

from django.db.models import Q, Sum
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from mainframe.finance.models import CryptoPnL


class PnlActionModelViewSet(viewsets.ModelViewSet):
    pnl_model_class = NotImplemented
    pnl_serializer_class = NotImplemented
    pnl_importer_class = NotImplemented
    pnl_importer_error_class = NotImplementedError

    @action(methods=["get", "post"], detail=False)
    def pnl(self, request, *args, **kwargs):
        if request.method == "GET":
            queryset = self.filter_queryset(self.pnl_model_class.objects.all())
            if currency := request.query_params.getlist("currency"):
                queryset = queryset.filter(currency__in=currency)
            if ticker := request.query_params.getlist("ticker"):
                queryset = queryset.filter(ticker__in=ticker)

            page = self.paginate_queryset(queryset)
            if page is not None:
                serializer = self.pnl_serializer_class(page, many=True)
                response = self.get_paginated_response(serializer.data)
            else:
                response = Response(self.pnl_serializer_class(queryset, many=True).data)

            currencies = (
                self.pnl_model_class.objects.values_list("currency", flat=True)
                .distinct("currency")
                .order_by("currency")
            )
            tickers = (
                self.pnl_model_class.objects.filter(ticker__isnull=False)
                .values_list("ticker", flat=True)
                .distinct("ticker")
                .order_by("ticker")
            )
            response.data["currencies"] = currencies
            response.data["tickers"] = tickers
            pnl_field = "net_pnl" if self.pnl_model_class == CryptoPnL else "pnl"
            aggregations = queryset.aggregate(
                **{
                    f"total_{currency}": Sum(pnl_field, filter=Q(currency=currency))
                    for currency in currencies
                }
            )
            response.data["total"] = {
                currency: aggregations[f"total_{currency}"] for currency in currencies
            }
            return response

        if request.method == "POST":
            file = request.FILES["file"]
            logger = logging.getLogger(__name__)
            try:
                self.pnl_importer_class(file, logger).run()
            except self.pnl_importer_error_class as e:
                logger.error("Could not process file. (%s)", e)
                return Response(f"Invalid file: {file}", status.HTTP_400_BAD_REQUEST)
            request.method = "GET"
            return self.pnl(request, *args, **kwargs)
