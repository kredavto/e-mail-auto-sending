"""SMTP encryption options shared by campaign and notification delivery."""


def smtp_security_options(port: int, enabled: bool) -> dict[str, bool]:
    # Port 465 starts TLS immediately; STARTTLS is for submission on other ports.
    # Keep Mailpit's explicitly unencrypted transport unchanged.
    implicit_tls = enabled and port == 465
    return {"use_tls": implicit_tls, "start_tls": enabled and not implicit_tls}
