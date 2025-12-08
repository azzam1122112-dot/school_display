import firebase_admin
from firebase_admin import credentials, firestore
import os
import base64
import json

def get_db():
    if not firebase_admin._apps:
        firebase_base64 = os.getenv("FIREBASE_CREDENTIALS_BASE64")
        
        if firebase_base64:
            try:
                cred_json = json.loads(base64.b64decode(firebase_base64))
                cred = credentials.Certificate(cred_json)
            except Exception as e:
                raise e
        else:
            key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
            if key_path and os.path.exists(key_path):
                cred = credentials.Certificate(key_path)
            else:
                raise ValueError("Missing Firebase credentials.")
        
        firebase_admin.initialize_app(cred)

    return firestore.client()
