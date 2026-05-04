import os
from dotenv import load_dotenv

load_dotenv()

RENIEC_API_TOKEN = os.getenv("RENIEC_API_TOKEN")
RENIEC_API_URL = os.getenv("RENIEC_API_URL")

MERCADOPAGO_ACCESS_TOKEN = os.getenv("MERCADOPAGO_ACCESS_TOKEN")
MERCADOPAGO_PUBLIC_KEY = os.getenv("MERCADOPAGO_PUBLIC_KEY")