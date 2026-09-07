from typing import Literal
import re
import unicodedata
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


def safe_name(value):
    value = unicodedata.normalize('NFC', value).strip()
    if not value or len(value) > 100 or value in {'.', '..'} or re.search(r'[<>:"/\\|?*\x00-\x1f\x7f]', value) or value.endswith(('.', ' ')):
        raise ValueError('名称不可为空或含路径及文件名禁用字符（最多100字符）')
    if value.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('名称是系统保留文件名')
    return value


class Model(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)


class PrintSettings(Model):
    paper_width_mm: float = Field(210, ge=50, le=600)
    paper_height_mm: float = Field(297, ge=50, le=600)
    long_edge_mm: float = Field(85, ge=10, le=300)
    margin_mm: float = Field(10, ge=0, le=80)
    gap_mm: float = Field(10, ge=0, le=80)
    dpi: int = Field(300, ge=72, le=600)
    brightness: bool = False
    color_balance: bool = False

    @model_validator(mode='after')
    def validate_layout(self):
        if self.long_edge_mm > min(self.paper_width_mm, self.paper_height_mm) - self.margin_mm * 2:
            raise ValueError('单张长边及页边距超出纸张尺寸')
        if self.paper_width_mm * self.paper_height_mm * (self.dpi / 25.4) ** 2 > 40_000_000:
            raise ValueError('纸张像素总量超限，请降低DPI或纸张尺寸')
        return self


class Credentials(Model):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[A-Za-z0-9_.-]+$')
    password: str = Field(min_length=10, max_length=200)


class Signup(Credentials):
    display_name: str = Field(min_length=1, max_length=80)
    invite: str | None = None

    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, value):
        if not value.strip():
            raise ValueError('显示名不能仅含空白字符')
        return value.strip()


class UploadInit(Model):
    filename: str
    size: int = Field(gt=0, le=25 * 1024 * 1024)
    sha256: str = Field(pattern=r'^[0-9a-fA-F]{64}$')
    _filename = field_validator('filename')(safe_name)


class OrderCreate(Model):
    upload_id: str
    name: str
    template_ids: list[str] = Field(min_length=1, max_length=30)
    print_settings: PrintSettings = Field(default_factory=PrintSettings)
    client_token: str = Field(min_length=1, max_length=120)
    _name = field_validator('name')(safe_name)


class AccountPatch(Model):
    display_name: str | None = Field(None, min_length=1, max_length=80)
    watermark: str | None = Field(None, max_length=100)
    print_defaults: PrintSettings | None = None


    @field_validator('display_name')
    @classmethod
    def validate_display_name(cls, value):
        if value is not None and not value.strip():
            raise ValueError('显示名不能仅含空白字符')
        return value.strip() if value is not None else value


class PasswordChange(Model):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class SettingsPatch(Model):
    max_inflight: int | None = Field(None, ge=1, le=40)
    prompt: str | None = Field(None, min_length=20, max_length=10000)
    fal_api_key: str | None = Field(None, max_length=500)
    cutout_api_key: str | None = Field(None, max_length=500)


class ActivePatch(Model):
    active: bool


class AccountConcurrencyPatch(Model):
    generation_concurrency: int = Field(ge=1, le=40, strict=True)
    expected_limit: int = Field(ge=1, le=40, strict=True)


class AccountDeleteConfirm(Model):
    username: str = Field(min_length=3, max_length=40)
    preview_token: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]


class Repack(Model):
    print_settings: PrintSettings


class ResolveUnknown(Model):
    confirmed_ended: Literal[True]


class CleanupPreview(Model):
    before: AwareDatetime


class CleanupConfirm(CleanupPreview):
    preview_token: str = Field(pattern=r'^[0-9a-f]{64}$')
    confirmed: Literal[True]


class AdminCreateUser(Model):
    username: str = Field(min_length=3, max_length=40, pattern=r'^[A-Za-z0-9_.-]+$')
    display_name: str = Field(min_length=1, max_length=80)
    @field_validator('display_name')
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip(): raise ValueError('显示名不能为空')
        return value.strip()


class CreditReason(Model):
    reason: str = Field(min_length=1, max_length=200)

    @field_validator('reason')
    @classmethod
    def nonblank_reason(cls, value):
        if not value.strip(): raise ValueError('请填写调整或核对原因')
        return value.strip()


class CreditAdjustment(CreditReason):
    operation: Literal['add','set']
    amount: int = Field(ge=0, le=1_000_000_000, strict=True)
    reason: str = Field(min_length=1, max_length=200)
    client_token: str = Field(min_length=1, max_length=120)
    expected_version: int = Field(ge=0, strict=True)


class CreditSettlement(CreditReason):
    outcome: Literal['charge','release']
    reason: str = Field(min_length=1, max_length=200)
    client_token: str = Field(min_length=1, max_length=120)


class RerunRequest(Model):
    client_token: str = Field(min_length=1, max_length=120)
