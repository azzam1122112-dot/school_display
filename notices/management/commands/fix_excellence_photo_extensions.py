from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Optional

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.core.files.storage import default_storage


@dataclass(frozen=True)
class FixPlan:
    pk: int
    old_name: str
    new_name: str
    detected_ext: str


def _detect_image_extension(file_bytes: bytes) -> str:
    """Detect extension from bytes using Pillow (available if ImageField is used).

    Falls back to .jpg if detection fails.
    """
    try:
        from PIL import Image  # type: ignore

        with Image.open(ContentFile(file_bytes)) as img:
            fmt = (img.format or "").upper().strip()

        if fmt in ("JPEG", "JPG"):
            return ".jpg"
        if fmt == "PNG":
            return ".png"
        if fmt == "WEBP":
            return ".webp"
    except Exception:
        pass

    return ".jpg"


def _choose_new_name(old_name: str, ext: str) -> str:
    candidate = f"{old_name}{ext}"
    if not default_storage.exists(candidate):
        return candidate

    # avoid collision
    base = old_name
    return f"{base}_{uuid.uuid4().hex}{ext}"


class Command(BaseCommand):
    help = (
        "Fix Excellence.photo files that were saved without an extension by copying "
        "them to a new name with a detected extension and updating DB references."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Apply changes (default is dry-run).",
        )
        parser.add_argument(
            "--delete-old",
            action="store_true",
            help="Delete the old file after copying (only with --apply).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=0,
            help="Optional limit of records to process (0 = no limit).",
        )

    def handle(self, *args, **options):
        from notices.models import Excellence

        apply: bool = bool(options["apply"])
        delete_old: bool = bool(options["delete_old"])
        limit: int = int(options["limit"] or 0)

        if delete_old and not apply:
            self.stderr.write("--delete-old requires --apply")
            return

        qs = Excellence.objects.exclude(photo="").exclude(photo__isnull=True)

        plans: list[FixPlan] = []
        for obj in qs.iterator(chunk_size=200):
            old_name = getattr(obj.photo, "name", "") or ""
            if not old_name:
                continue

            _, ext = os.path.splitext(old_name)
            if ext:
                continue  # already has extension

            # read bytes to detect
            try:
                with default_storage.open(old_name, "rb") as fh:
                    data = fh.read()
            except Exception as exc:
                self.stderr.write(
                    f"SKIP pk={obj.pk}: cannot open '{old_name}' ({exc})"
                )
                continue

            detected_ext = _detect_image_extension(data)
            new_name = _choose_new_name(old_name, detected_ext)

            plans.append(
                FixPlan(
                    pk=obj.pk,
                    old_name=old_name,
                    new_name=new_name,
                    detected_ext=detected_ext,
                )
            )

            if limit and len(plans) >= limit:
                break

        if not plans:
            self.stdout.write("No Excellence photos without extension found.")
            return

        self.stdout.write(
            f"Found {len(plans)} Excellence photo file(s) without extension."  # noqa: T201
        )
        for p in plans[:20]:
            self.stdout.write(
                f"- pk={p.pk}: {p.old_name} -> {p.new_name} ({p.detected_ext})"
            )
        if len(plans) > 20:
            self.stdout.write(f"(and {len(plans) - 20} more)")

        if not apply:
            self.stdout.write("Dry-run only. Re-run with --apply to perform changes.")
            return

        changed = 0
        for p in plans:
            obj = Excellence.objects.filter(pk=p.pk).first()
            if not obj:
                self.stderr.write(f"SKIP pk={p.pk}: record no longer exists")
                continue

            # Re-check current name (avoid stomping concurrent edits)
            current_name = getattr(obj.photo, "name", "") or ""
            if current_name != p.old_name:
                self.stderr.write(
                    f"SKIP pk={p.pk}: photo changed ({current_name} != {p.old_name})"
                )
                continue

            try:
                with default_storage.open(p.old_name, "rb") as fh:
                    data = fh.read()
                default_storage.save(p.new_name, ContentFile(data))
            except Exception as exc:
                self.stderr.write(
                    f"FAIL pk={p.pk}: cannot copy to '{p.new_name}' ({exc})"
                )
                continue

            obj.photo.name = p.new_name
            obj.save(update_fields=["photo"])
            changed += 1

            if delete_old:
                try:
                    default_storage.delete(p.old_name)
                except Exception as exc:
                    self.stderr.write(
                        f"WARN pk={p.pk}: copied but cannot delete '{p.old_name}' ({exc})"
                    )

        self.stdout.write(f"Done. Updated {changed}/{len(plans)} record(s).")
