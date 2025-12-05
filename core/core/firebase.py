import firebase_admin
from firebase_admin import credentials, firestore
import os
import base64
import json

def get_db():
    if not firebase_admin._apps:
        # 1. Try Base64 env var (Best for Render/Production)
        firebase_base64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
        
        if firebase_base64:
            try:
                # Decode base64 to json string, then parse to dict
                cred_json = json.loads(base64.b64decode(firebase_base64))
                cred = credentials.Certificate(cred_json)
            except Exception as e:
                print(f"Error decoding FIREBASE_CREDENTIALS_BASE64: {e}")
                raise e
        else:
            # 2. Fallback to file path (Best for Local Development)
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if key_path and os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
            else:
                # If neither is found, we can't connect
                raise ValueError("No Firebase credentials found. Set FIREBASE_CREDENTIALS_BASE64 or GOOGLE_APPLICATION_CREDENTIALS.")

        firebase_admin.initialize_app(cred)

    return firestore.client()
