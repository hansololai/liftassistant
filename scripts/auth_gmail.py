"""Interactive Gmail OAuth re-authorization script.
Generates a new token.json using Google's InstalledAppFlow.
"""

import os
import sys
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

def main():
    creds_file = "credentials.json"
    token_file = "token.json"

    if not os.path.exists(creds_file):
        print(f"Error: {creds_file} not found in working directory.")
        sys.exit(1)

    print("Launching OAuth flow...")
    print("A browser window will open. Please sign in to your Google account and grant read-only access to Gmail.")
    
    flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
    creds = flow.run_local_server(port=0)

    # Save credentials to token.json
    with open(token_file, "w") as token:
        token.write(creds.to_json())

    print(f"\nSUCCESS! New credentials saved to {token_file}.")

if __name__ == "__main__":
    main()
