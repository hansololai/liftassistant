"""CLI Tool for Managing Authorized Family Devices and Magic Enrollment Links.
Usage:
    python -m liftassistant.scripts.manage_devices
    python -m liftassistant.scripts.manage_devices create "Dad's iPad"
    python -m liftassistant.scripts.manage_devices revoke dev_dad
"""

import argparse
import sys
from liftassistant.services.auth_service import DeviceAuthService


def main() -> None:
    parser = argparse.ArgumentParser(description="LiftAssistant Family Device Manager")
    parser.add_argument(
        "action",
        nargs="?",
        default="list",
        choices=["list", "create", "revoke"],
        help="Action to perform (default: list)",
    )
    parser.add_argument("name_or_id", nargs="?", help="Device name (for create) or Device ID (for revoke)")
    parser.add_argument(
        "--base-url",
        default="http://localhost:5173",
        help="Base URL for the frontend application (default: http://localhost:5173)",
    )

    args = parser.parse_args()
    service = DeviceAuthService()

    if args.action == "list":
        devices = service.list_devices()
        print("\n========================================================")
        print("  LiftAssistant - Authorized Family Devices & Magic Links")
        print("========================================================\n")
        if not devices:
            print("No devices found.")
            return

        for idx, d in enumerate(devices, 1):
            status_str = "REVOKED" if d["is_revoked"] else ("ACTIVE (Enrolled)" if d["is_enrolled"] else "PENDING ENROLLMENT")
            print(f"[{idx}] {d['device_name']} (ID: {d['id']})")
            print(f"    Status:      {status_str}")
            if not d["is_revoked"]:
                if not d["is_enrolled"]:
                    magic_link = f"{args.base_url.rstrip('/')}/?enroll_token={d['enroll_token']}"
                    print(f"    Magic Link:  {magic_link}")
                else:
                    print(f"    Enrolled At: {d['enrolled_at']}")
                    print(f"    Last Seen:   {d['last_seen_at'] or 'Never'}")
            print()
        print("Tip: Send the Magic Link via SMS/iMessage to Mom or Dad. When tapped, their phone is permanently enrolled.")
        print("========================================================\n")

    elif args.action == "create":
        if not args.name_or_id:
            print("Error: Please provide a device name, e.g.: python -m liftassistant.scripts.manage_devices create \"Dad's iPad\"")
            sys.exit(1)
        res = service.create_device(args.name_or_id)
        magic_link = f"{args.base_url.rstrip('/')}/?enroll_token={res['enroll_token']}"
        print(f"\nCreated new device '{res['device_name']}' (ID: {res['id']})")
        print(f"Magic Enrollment Link:\n{magic_link}\n")

    elif args.action == "revoke":
        if not args.name_or_id:
            print("Error: Please provide a device ID to revoke, e.g.: python -m liftassistant.scripts.manage_devices revoke dev_dad")
            sys.exit(1)
        ok = service.revoke_device(args.name_or_id)
        if ok:
            print(f"Device '{args.name_or_id}' revoked successfully.")
        else:
            print(f"Device '{args.name_or_id}' not found.")


if __name__ == "__main__":
    main()
