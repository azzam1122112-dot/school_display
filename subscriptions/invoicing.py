from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.template.loader import render_to_string
from django.utils import timezone

from .models import SubscriptionInvoice, SubscriptionPaymentOperation


@dataclass(frozen=True)
class SellerInfo:
    name: str
    vat: str
    cr: str
    address: str
    phone: str
    email: str


def _get_seller_info() -> SellerInfo:
    # يمكن ضبط هذه القيم من settings.py لاحقًا
    return SellerInfo(
        name=getattr(settings, "INVOICE_SELLER_NAME", "منصة شاشة العرض الذكية") or "منصة شاشة العرض الذكية",
        vat=getattr(settings, "INVOICE_SELLER_VAT", "") or "",
        cr=getattr(settings, "INVOICE_SELLER_CR", "") or "",
        address=getattr(settings, "INVOICE_SELLER_ADDRESS", "المالك: منصور محمد الغامدي") or "المالك: منصور محمد الغامدي",
        phone=getattr(settings, "INVOICE_SELLER_PHONE", "") or "",
        email=getattr(settings, "INVOICE_SELLER_EMAIL", "") or "",
    )


def build_invoice_from_operation(op: SubscriptionPaymentOperation) -> SubscriptionInvoice:
    """إنشاء فاتورة وربطها بعملية الدفع + حفظ نسخة HTML."""
    seller = _get_seller_info()
    plan = op.plan
    school = op.school
    subscription = op.subscription

    inv = SubscriptionInvoice(
        operation=op,
        school=school,
        subscription=subscription,
        plan=plan,
        amount=op.amount,
        payment_method=op.method,
        issued_at=timezone.now(),
        seller_name=seller.name,
        buyer_name=getattr(school, "name", "") or "",
    )
    inv.save()

    html = render_to_string(
        "invoices/subscription_invoice.html",
        {
            "invoice": inv,
            "seller": seller,
            "school": school,
            "subscription": subscription,
            "plan": plan,
        },
    )
    inv.html_snapshot = html
    inv.save(update_fields=["html_snapshot"])
    return inv
