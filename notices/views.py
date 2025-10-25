# notices/views.py
from __future__ import annotations

from typing import Optional

from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

# نحاول استخدام دكوريتر الصلاحيات الخاص بك؛ وإلا نستبدله بـ login_required
try:
    from dashboard.permissions import manager_required  # عدّل المسار لو مختلف
except Exception:  # pragma: no cover
    from django.contrib.auth.decorators import login_required as manager_required

from .forms import AnnouncementForm, ExcellenceForm
from .models import Announcement, Excellence


# =========================
# التنبيهات (Announcements)
# =========================

@manager_required
def ann_list(request: HttpRequest) -> HttpResponse:
    """
    قائمة التنبيهات مع ترقيم صفحات.
    يدعم فلترة بسيطة بالمستقبل (مثلاً ?q= ... ).
    """
    qs = Announcement.objects.order_by("-starts_at")
    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    return render(request, "notices/ann_list.html", {"page": page})


@manager_required
def ann_create(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        form = AnnouncementForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إنشاء التنبيه.")
            return redirect("notices:ann_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AnnouncementForm()
    return render(
        request,
        "notices/ann_form.html",
        {"form": form, "title": "إنشاء تنبيه"},
    )


@manager_required
def ann_edit(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(Announcement, pk=pk)
    if request.method == "POST":
        form = AnnouncementForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث التنبيه.")
            return redirect("notices:ann_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = AnnouncementForm(instance=obj)
    return render(
        request,
        "notices/ann_form.html",
        {"form": form, "title": "تعديل تنبيه"},
    )


@manager_required
def ann_delete(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")
    obj = get_object_or_404(Announcement, pk=pk)
    obj.delete()
    messages.success(request, "تم حذف التنبيه.")
    return redirect("notices:ann_list")


# =========================
# بطاقات التميّز (Excellence)
# =========================

@manager_required
def exc_list(request: HttpRequest) -> HttpResponse:
    """
    قائمة بطاقات التميز مع ترقيم صفحات.
    """
    qs = Excellence.objects.order_by("priority", "-start_at")
    page = Paginator(qs, 12).get_page(request.GET.get("page"))
    return render(request, "notices/exc_list.html", {"page": page})


@manager_required
def exc_create(request: HttpRequest) -> HttpResponse:
    """
    إنشاء بطاقة تميّز — يدعم رفع الصورة (multipart/form-data).
    """
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES)
        if form.is_valid():
            form.save()
            messages.success(request, "تم إضافة بطاقة التميز.")
            return redirect("notices:exc_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = ExcellenceForm()
    return render(
        request,
        "notices/exc_form.html",
        {"form": form, "title": "إضافة تميز"},
    )


@manager_required
def exc_edit(request: HttpRequest, pk: int) -> HttpResponse:
    """
    تعديل بطاقة تميّز — يدعم استبدال الصورة مع تنظيف القديمة (model.save يتكفل).
    """
    obj = get_object_or_404(Excellence, pk=pk)
    if request.method == "POST":
        form = ExcellenceForm(request.POST, request.FILES, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "تم تحديث بطاقة التميز.")
            return redirect("notices:exc_list")
        messages.error(request, "الرجاء تصحيح الأخطاء.")
    else:
        form = ExcellenceForm(instance=obj)
    return render(
        request,
        "notices/exc_form.html",
        {"form": form, "title": "تعديل تميز"},
    )


@manager_required
def exc_delete(request: HttpRequest, pk: int) -> HttpResponse:
    if request.method != "POST":
        return HttpResponseBadRequest("طريقة غير مدعومة.")
    obj = get_object_or_404(Excellence, pk=pk)
    obj.delete()
    messages.success(request, "تم حذف البطاقة.")
    return redirect("notices:exc_list")
