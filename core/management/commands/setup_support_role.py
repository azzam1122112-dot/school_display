from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand


SUPPORT_GROUP_NAME = "Support"


@dataclass(frozen=True)
class ModelPermSpec:
    app_label: str
    model_name: str
    actions: tuple[str, ...] = ("view", "add", "change")


def _resolve_model(app_label: str, model_name: str):
    try:
        return apps.get_model(app_label, model_name)
    except Exception:
        return None


def _get_permissions_for_model(model_cls, actions: Iterable[str]) -> list[Permission]:
    perms: list[Permission] = []
    model_name = model_cls._meta.model_name

    try:
        ct = ContentType.objects.get_for_model(model_cls)
    except Exception:
        ct = None

    for action in actions:
        codename = f"{action}_{model_name}"
        try:
            if ct is not None:
                perms.append(Permission.objects.get(content_type=ct, codename=codename))
            else:
                # best-effort fallback
                perms.append(Permission.objects.filter(codename=codename).first())
        except Permission.DoesNotExist:
            # Some projects disable default permissions or are mid-migration.
            continue

    # drop any Nones from best-effort fallback
    return [p for p in perms if p is not None]


class Command(BaseCommand):
    help = "Create/Update the Support staff group with safe default permissions."

    def handle(self, *args, **options):
        group, created = Group.objects.get_or_create(name=SUPPORT_GROUP_NAME)
        self.stdout.write(self.style.SUCCESS(
            f"Group '{SUPPORT_GROUP_NAME}' {'created' if created else 'loaded'}."
        ))

        specs: list[ModelPermSpec] = [
            # Support tickets
            ModelPermSpec("core", "SupportTicket"),
            ModelPermSpec("core", "TicketComment"),

            # Subscriptions
            ModelPermSpec("subscriptions", "SchoolSubscription"),
            ModelPermSpec("subscriptions", "SubscriptionScreenAddon"),
            ModelPermSpec("subscriptions", "SubscriptionRequest"),

            # Schools / Users
            ModelPermSpec("core", "School"),
            ModelPermSpec("core", "UserProfile", actions=("view", "change")),
        ]

        # auth.User (or custom user)
        UserModel = get_user_model()
        specs.append(ModelPermSpec(UserModel._meta.app_label, UserModel.__name__))

        added = 0
        skipped = 0

        for spec in specs:
            model_cls = _resolve_model(spec.app_label, spec.model_name)
            if model_cls is None:
                skipped += 1
                continue

            perms = _get_permissions_for_model(model_cls, spec.actions)
            if not perms:
                skipped += 1
                continue

            group.permissions.add(*perms)
            added += len(perms)

        self.stdout.write(self.style.SUCCESS(f"Permissions added: {added}"))
        if skipped:
            self.stdout.write(self.style.WARNING(f"Specs skipped (model/perms missing): {skipped}"))
