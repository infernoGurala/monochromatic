import os
import sys
import json
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly"
]

def main():
    if len(sys.argv) < 3:
        print("Usage: python get_token.py <path_to_client_secret.json> <account_id>")
        print("Example: python get_token.py /path/to/client_secret.json 1")
        sys.exit(1)

    client_secret_path = sys.argv[1]
    account_id = sys.argv[2]

    try:
        account_id = int(account_id)
        if account_id not in [1, 2]:
            raise ValueError()
    except ValueError:
        print("Error: Account ID must be 1 or 2")
        sys.exit(1)

    if not os.path.exists(client_secret_path):
        print(f"Error: Client secret file not found at '{client_secret_path}'")
        sys.exit(1)

    # Initialize flow
    flow = InstalledAppFlow.from_client_secrets_file(
        client_secret_path,
        scopes=SCOPES
    )

    # Run local server to authenticate
    print(f"Starting authentication flow for Account {account_id}...")
    print("A browser window will open to authorize this application. Please log in with your Google/YouTube account.")
    
    # We can use run_local_server which will open browser and handle redirect
    creds = flow.run_local_server(
        port=0,
        authorization_prompt_message="Please go to this URL: {url}",
        success_message="Authorization complete! You can close this window."
    )

    # Save credentials to token file
    token_filename = f".youtube_token_{account_id}.json"
    with open(token_filename, "w") as f:
        f.write(creds.to_json())

    print(f"\nSuccess! Token saved to: {token_filename}")
    print(f"Account {account_id} is now authenticated and ready for YouTube uploads.")

if __name__ == "__main__":
    main()
