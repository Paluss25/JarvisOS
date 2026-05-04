from pydantic import BaseModel, Field


class AccountConfig(BaseModel):
    name: str = Field(min_length=1)
    imap_host: str = Field(min_length=1)
    imap_port: int
    imap_secure: bool = False
    imap_user: str = Field(min_length=1)
    imap_pass: str = Field(min_length=1)
    smtp_host: str = Field(min_length=1)
    smtp_port: int
    smtp_secure: bool = False
    smtp_starttls: bool = False
    smtp_user: str = Field(min_length=1)
    smtp_pass: str = Field(min_length=1)
    smtp_from: str = Field(min_length=1)
