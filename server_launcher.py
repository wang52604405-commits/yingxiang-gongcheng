import mobile_sync_reconcile  # noqa: F401 - patch reconciliation before app import
import mobile_sync_preview_repair  # noqa: F401 - retry Pillow verify-order false failures
from app import run_lan_server


if __name__ == "__main__":
    run_lan_server()
