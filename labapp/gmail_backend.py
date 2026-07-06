import base64
from email.message import EmailMessage

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"


class GmailApiEmailBackend(BaseEmailBackend):

    def _get_service(self):
        credentials = Credentials(
            token=None,
            refresh_token=settings.GMAIL_REFRESH_TOKEN,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.GMAIL_CLIENT_ID,
            client_secret=settings.GMAIL_CLIENT_SECRET,
            scopes=[GMAIL_SEND_SCOPE],
        )

        return build(
            "gmail",
            "v1",
            credentials=credentials,
            cache_discovery=False,
        )

    def send_messages(self, email_messages):
        if not email_messages:
            return 0

        service = self._get_service()
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

                # Include HTML version when Django supplies one
                if hasattr(email, "alternatives"):
                    for alternative in email.alternatives:
                        content = alternative[0]
                        mimetype = alternative[1]

                        if mimetype == "text/html":
                            message.add_alternative(
                                content,
                                subtype="html",
                            )

                raw = base64.urlsafe_b64encode(
                    message.as_bytes()
                ).decode()

                service.users().messages().send(
                    userId="me",
                    body={"raw": raw},
                ).execute()

                sent_count += 1

            except Exception:
                if not self.fail_silently:
                    raise

        return sent_count