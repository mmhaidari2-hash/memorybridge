import os

import stripe
from fastapi import HTTPException


SUPPORTED_PAID_PLANS = {"pro", "team"}


def configure_stripe() -> None:
    secret_key = os.getenv("STRIPE_SECRET_KEY", "").strip()
    if not secret_key:
        raise HTTPException(status_code=503, detail="Billing is not configured")
    stripe.api_key = secret_key


def price_id_for_plan(plan: str) -> str:
    if plan not in SUPPORTED_PAID_PLANS:
        raise HTTPException(status_code=400, detail="Unsupported paid plan")
    env_name = f"STRIPE_PRICE_{plan.upper()}"
    price_id = os.getenv(env_name, "").strip()
    if not price_id:
        raise HTTPException(status_code=503, detail=f"Billing price is not configured for {plan}")
    return price_id


def webhook_secret() -> str:
    secret = os.getenv("STRIPE_WEBHOOK_SECRET", "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Billing webhook is not configured")
    return secret
