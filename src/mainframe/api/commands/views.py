import itertools
import logging
import operator

from django.core.exceptions import ImproperlyConfigured
from django.core.management import (
    BaseCommand,
    CommandError,
    call_command,
    get_commands,
    load_command_class,
)
from django.http import JsonResponse
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser

from mainframe.core.exceptions import MainframeError
from mainframe.crons.models import Cron
from mainframe.crons.serializers import CronSerializer

logger = logging.getLogger(__name__)


def get_custom_arguments(app_name, command_name):
    command_class = load_command_class(app_name, command_name)

    parser = command_class.create_parser("manage.py", command_name)

    base_command = BaseCommand()
    base_parser = base_command.create_parser("manage.py", "base")
    default_options = {action.dest for action in base_parser._actions}

    return [
        {
            "choices": o.choices,
            "default": o.default,
            "dest": o.dest,
            "help": o.help,
            "nargs": o.nargs,
            "option_strings": o.option_strings,
            "required": o.required,
            "type": o.type.__name__ if o.type else None,
        }
        for o in parser._actions
        if o.dest not in default_options
    ]


class CommandsViewSet(viewsets.GenericViewSet):
    permission_classes = (IsAdminUser,)

    @staticmethod
    def list(request, *args, **kwargs):
        def filter_out(item):
            _, app = item
            return not (
                app in ["debug_toolbar", "huey.contrib.djhuey", "rest_framework"]
                or "django" in app
            )

        commands = sorted(
            filter(filter_out, get_commands().items()), key=operator.itemgetter(1)
        )
        results = [
            {
                "app": app,
                "commands": [
                    {
                        "name": cmd[0],
                        "args": get_custom_arguments(app, cmd[0]),
                    }
                    for cmd in cmds
                ],
            }
            for (app, cmds) in itertools.groupby(commands, key=operator.itemgetter(1))
        ]
        data = {"results": results}
        return JsonResponse(data=data, status=status.HTTP_200_OK)

    @action(detail=True, methods=["put"])
    def run(self, request, pk, **kwargs):
        cmd_args = request.data.get("args") or []
        cmd_kwargs = request.data.get("kwargs") or {}
        try:
            call_command(pk, *cmd_args, **cmd_kwargs)
        except (CommandError, MainframeError) as e:
            return JsonResponse(
                data={"detail": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (
            AttributeError,
            ImproperlyConfigured,
            KeyError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception(e)
            return JsonResponse(
                data={"detail": "Command failed. Check logs"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return JsonResponse(data={}, status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["put"], url_path="delete-cron")
    def delete_cron(self, request, pk, **kwargs):
        if cron_id := request.data.get("cron_id"):
            Cron.objects.get(id=cron_id).delete()
        else:
            Cron.objects.get(command=pk).delete()
        return self.list(request)

    @action(detail=True, methods=["put"], url_path="set-cron")
    def set_cron(self, request, pk, **kwargs):
        serializer_kwargs = {"data": {"command": pk, **request.data}}
        if cron_id := request.data.get("cron_id"):
            serializer_kwargs["instance"] = Cron.objects.get(id=cron_id)
        serializer = CronSerializer(**serializer_kwargs)
        if not serializer.is_valid():
            return JsonResponse(
                data=serializer.errors, status=status.HTTP_400_BAD_REQUEST
            )
        serializer.save()
        return self.list(request)
