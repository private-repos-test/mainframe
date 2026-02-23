import logging
from operator import itemgetter

from django.contrib.postgres.search import SearchVector
from django.db.models import Count, F, Sum
from django.http import JsonResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from mainframe.clients.finance.statement import StatementImportError, import_statement
from mainframe.finance.models import Account, Category, Transaction
from mainframe.finance.serializers import TransactionSerializer


class TransactionViewSet(viewsets.ModelViewSet):
    permission_classes = (IsAdminUser,)
    queryset = Transaction.objects.order_by("-started_at")
    serializer_class = TransactionSerializer

    @action(methods=["put"], detail=False, url_path="bulk-update")
    def bulk_update(self, request, *args, **kwargs):
        total = 0
        for item in self.request.data:
            total += Transaction.objects.filter(
                description=item["description"],
                category=Category.UNIDENTIFIED,
                confirmed_by=Transaction.CONFIRMED_BY_UNCONFIRMED,
            ).update(
                category=item["category"],
                category_suggestion_id=None,
                confirmed_by=Transaction.CONFIRMED_BY_ML,
            )
        response = self.list(request, *args, **kwargs)
        response.data["msg"] = {
            "message": f"Successfully updated {total} transaction categories"
        }
        return response

    @action(methods=["put"], detail=False, url_path="bulk-update-preview")
    def bulk_update_preview(self, request, *args, **kwargs):
        if not request.data:
            return JsonResponse(
                {"msg": "List of descriptions required"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        qs = (
            Transaction.objects.expenses()
            .filter(
                description__in=map(itemgetter("description"), request.data),
                category=Category.UNIDENTIFIED,
                confirmed_by=Transaction.CONFIRMED_BY_UNCONFIRMED,
            )
            .values("description")
            .annotate(count=Count("id"))
        )
        return JsonResponse(
            [{"description": t["description"], "count": t["count"]} for t in qs],
            safe=False,
        )

    @action(methods=["post"], detail=False, url_path="upload")
    def upload(self, request, *args, **kwargs):
        file = request.FILES["file"]
        logger = logging.getLogger(__name__)
        try:
            import_statement(file, logger)
        except StatementImportError as e:
            logger.error("Could not process file. (%s)", e)
            return Response(
                f"Invalid file: {file.name}", status=status.HTTP_400_BAD_REQUEST
            )
        response = self.list(request, *args, **kwargs)
        response.data["msg"] = {"message": "Payments uploaded successfully!"}
        return response

    def get_queryset(self):  # noqa: C901
        queryset = super().get_queryset()
        params = self.request.query_params
        if account_id := params.get("account_id"):
            queryset = queryset.filter(account_id=account_id)
        if category := params.get("category"):
            queryset = queryset.filter(category=category)
        if confirmed_by := params.get("confirmed_by"):
            queryset = queryset.filter(confirmed_by=confirmed_by)
        if description := params.get("description"):
            queryset = queryset.filter(description=description)
        if params.get("only_expenses") == "true":
            queryset = queryset.expenses()
        if month := params.get("month"):
            queryset = queryset.filter(started_at__month=month)
        if search_term := params.get("search_term"):
            queryset = queryset.annotate(
                search=SearchVector(
                    "description", "additional_data", "amount", "type", "started_at"
                ),
            ).filter(search=search_term)
        if types := params.getlist("type"):
            queryset = queryset.filter(type__in=types)
        if year := params.get("year"):
            queryset = queryset.filter(started_at__year=year)
        if params.get("unique") == "true":
            queryset = queryset.distinct("description").order_by("description")

        return queryset.select_related("account")

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        return self._populate_filters(response)

    def partial_update(self, request, *args, **kwargs):
        Category.objects.get_or_create(id=request.data["category"])
        response = super().partial_update(request, *args, **kwargs)
        response.data["msg"] = {"message": "Successfully updated 1 transaction"}
        return response

    @action(methods=["put"], detail=False, url_path="update-all")
    def update_all(self, request, *args, **kwargs):
        category = self.request.data["category"]
        queryset = Transaction.objects.expenses().filter(
            description=self.request.data["description"],
        )
        total = queryset.update(
            category=category,
            category_suggestion_id=(
                None
                if category != Category.UNIDENTIFIED
                else F("category_suggestion_id")
            ),
            confirmed_by=(
                Transaction.CONFIRMED_BY_ML
                if category != Category.UNIDENTIFIED
                else Transaction.CONFIRMED_BY_UNCONFIRMED
            ),
        )
        response = self.list(request, *args, **kwargs)
        response.data["msg"] = {
            "message": f"Successfully updated {total} transactions",
            "level": "success",
        }
        return response

    def _populate_filters(self, response):
        response.data["types"] = (
            Transaction.objects.expenses()
            .values_list("type", flat=True)
            .distinct("type")
            .order_by("type")
        )
        response.data["confirmed_by_choices"] = Transaction.CONFIRMED_BY_CHOICES
        response.data["categories"] = Category.objects.values_list(
            "id", flat=True
        ).order_by("id")
        response.data["accounts"] = Account.objects.values("id", "bank", "type")
        response.data["unidentified_count"] = (
            Transaction.objects.expenses()
            .filter(category=Category.UNIDENTIFIED)
            .count()
        )
        response.data["page_amount"] = self.get_queryset().aggregate(Sum("amount"))[
            "amount__sum"
        ]
        return response
