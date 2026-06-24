import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend


class BrevoEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        if not settings.BREVO_API_KEY:
            if self.fail_silently:
                return 0
            raise Exception("BREVO_API_KEY is missing")

        sent_count = 0

        for email in email_messages:
            html_content = None

            if hasattr(email, "alternatives"):
                for content, mimetype in email.alternatives:
                    if mimetype == "text/html":
                        html_content = content
                        break

            payload = {
                "sender": {
                    "name": settings.BREVO_SENDER_NAME,
                    "email": settings.BREVO_SENDER_EMAIL,
                },
                "to": [{"email": addr} for addr in email.to],
                "subject": email.subject.replace("\n", " ").replace("\r", " "),
            }

            if html_content:
                payload["htmlContent"] = html_content
                payload["textContent"] = email.body or ""
            else:
                payload["textContent"] = email.body or ""

            response = requests.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "accept": "application/json",
                    "api-key": settings.BREVO_API_KEY,
                    "content-type": "application/json",
                },
                json=payload,
                timeout=20,
            )

            if response.status_code >= 400:
                if self.fail_silently:
                    continue
                raise Exception(f"Brevo API error {response.status_code}: {response.text}")

            sent_count += 1

        return sent_count