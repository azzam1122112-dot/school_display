import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.template.loader import render_to_string
from subscriptions.models import SubscriptionInvoice
from subscriptions.invoicing import _get_seller_info, _get_school_contact_info

def regenerate_snapshots():
    invoices = SubscriptionInvoice.objects.all()
    print(f"Found {invoices.count()} invoices. Regenerating snapshots...")
    
    seller = _get_seller_info()
    
    for inv in invoices:
        print(f"Updating Invoice #{inv.id} ({inv.invoice_number})...")

        c_name, c_mobile = _get_school_contact_info(inv.school)
        
        context = {
            "invoice": inv,
            "seller": seller,
            "school": inv.school,
            "subscription": inv.subscription,
            "plan": inv.plan,
            "contact_name": c_name,
            "contact_mobile": c_mobile,
        }
        
        try:
            html = render_to_string("invoices/subscription_invoice.html", context)
            inv.html_snapshot = html
            inv.save(update_fields=["html_snapshot"])
            print(f" > Success: Snapshot updated.")
        except Exception as e:
            print(f" > Error: {e}")

    print("Done.")

if __name__ == "__main__":
    regenerate_snapshots()
