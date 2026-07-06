import base64
from email.message import EmailMessage

import requests
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailApiEmailBackend(BaseEmailBackend):

    def _get_credentials(self):
        credentials = Credentials(
            token=None,
            refresh_token=settings.GMAIL_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            scopes=[GMAIL_SEND_SCOPE],
        )

        # Refresh using requests-based transport
        credentials.refresh(Request())

        return credentials

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        credentials = self._get_credentials()

        url = (
            "https://gmail.googleapis.com/"
            "gmail/v1/users/me/messages/send"
        )

        headers = {
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        }

        sent_count = 0

        for email in email_messages:
            try:
                message = EmailMessage()

                message["Subject"] = email.subject
                message["From"] = (
                    f"{settings.GMAIL_SENDER_NAME} "
                    f"<{settings.GMAIL_SENDER_EMAIL}>"
                )
                message["To"] = ", ".join(email.to)

                if email.cc:
                    message["Cc"] = ", ".join(email.cc)

                if email.reply_to:
                    message["Reply-To"] = ", ".join(email.reply_to)

                message.set_content(email.body or "")

                # Preserve Django HTML alternatives
                if hasattr(email, "alternatives"):
                    for alternative in email.alternatives:
                        content = alternative[0]
                        mimetype = alternative[1]

                        if mimetype == "text/html":
                            message.add_alternative(
                                content,
                                subtype="html",
                            )

                raw_message = base64.urlsafe_b64encode(
                    message.as_bytes()
                ).decode("utf-8")

                response = requests.post(
                    url,
                    headers=headers,
                    json={"raw": raw_message},
                    timeout=30,
                )

                if response.status_code >= 400:
                    raise RuntimeError(
                        f"Gmail API error "
                        f"{response.status_code}: "
                        f"{response.text}"
                    )

                sent_count += 1

            except Exception:
                if not self.fail_silently:
                    raise

        return sent_count