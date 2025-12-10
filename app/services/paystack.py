import hashlib
import hmac

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings


class PaystackClient:
    def __init__(self) -> None:
        self.settings = get_settings()

    async def initialize_transaction(self, *, email: str, amount: int, reference: str) -> dict:
        payload = {"email": email, "amount": amount, "reference": reference}
        async with httpx.AsyncClient(base_url=str(self.settings.paystack_base_url)) as client:
            response = await client.post(
                "/transaction/initialize",
                json=payload,
                headers=self._headers,
                timeout=15,
            )
        data = self._handle_response(response)
        return data["data"]

    async def verify_transaction(self, reference: str) -> dict:
        async with httpx.AsyncClient(base_url=str(self.settings.paystack_base_url)) as client:
            response = await client.get(
                f"/transaction/verify/{reference}",
                headers=self._headers,
                timeout=10,
            )
        data = self._handle_response(response)
        return data["data"]

    def verify_signature(self, body: bytes, signature: str | None) -> bool:
        if not signature:
            return False
        digest = hmac.new(
            self.settings.paystack_webhook_secret.encode("utf-8"),
            msg=body,
            digestmod=hashlib.sha512,
        ).hexdigest()
        return hmac.compare_digest(digest, signature)

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.paystack_secret_key}"}

    def _handle_response(self, response: httpx.Response) -> dict:
        if response.status_code >= 400:
            raise HTTPException(status_code=response.status_code, detail=response.text)
        payload = response.json()
        if not payload.get("status"):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=payload.get("message"))
        return payload
